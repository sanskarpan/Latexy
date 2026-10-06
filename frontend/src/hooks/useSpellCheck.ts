'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, type SpellCheckIssue } from '@/lib/api-client'

const LEGACY_DICT_KEY = 'latexy_spell_dictionary'
const ANONYMOUS_DICT_KEY = `${LEGACY_DICT_KEY}:anonymous`
const ACCOUNT_DICT_PREFIX = `${LEGACY_DICT_KEY}:account:`
export const PERSONAL_DICTIONARY_EVENT = 'latexy:spell-dictionary-change'
const MAX_DICTIONARY_WORDS = 500

export interface PersonalDictionaryScope {
    ownerId: string | null
    /** Auth token captured by the owning session hook; memory-only. */
    authToken: string | null
    confirmed: boolean
}

export interface PersonalDictionaryController {
  words: ReadonlySet<string>
  loading: boolean
  error: string | null
    sync: () => Promise<ReadonlySet<string>>
    getWords: () => ReadonlySet<string>
    addWord: (word: string) => void
    removeWord: (word: string) => void
}

interface DictionaryRuntime {
    scopeKey: string
    epoch: number
    words: Set<string>
    revision: number
    pendingRemovals: Set<string>
    syncPromise: Promise<ReadonlySet<string>> | null
    lifetime: object | null
}

function accountDictionaryKey(ownerId: string): string {
    return `${ACCOUNT_DICT_PREFIX}${encodeURIComponent(ownerId)}`
}

function scopeKey(scope: PersonalDictionaryScope): string {
    if (!scope.confirmed) return 'unconfirmed'
    return scope.ownerId ? accountDictionaryKey(scope.ownerId) : ANONYMOUS_DICT_KEY
}

export function personalDictionaryStorageKey(scope: PersonalDictionaryScope): string {
    return scopeKey(scope)
}

function readStoredDictionary(key: string, allowLegacyAnonymous = false): Set<string> {
    if (typeof window === 'undefined' || key === 'unconfirmed') return new Set()
    try {
        const stored = localStorage.getItem(key)
        if (stored !== null) return normalizedDictionary(JSON.parse(stored))
        if (allowLegacyAnonymous) {
            return normalizedDictionary(JSON.parse(localStorage.getItem(LEGACY_DICT_KEY) || '[]'))
        }
    } catch {
        return new Set()
    }
    return new Set()
}

function storeDictionary(key: string, dictionary: Set<string>): void {
  if (typeof window === 'undefined' || key === 'unconfirmed') return
  try {
    localStorage.setItem(key, JSON.stringify([...dictionary]))
    window.dispatchEvent(new CustomEvent(PERSONAL_DICTIONARY_EVENT, { detail: { scopeKey: key } }))
  } catch {
    // Keep the in-memory dictionary usable when browser storage is unavailable.
  }
}

export function normalizeDictionaryWord(word: string): string | null {
    const normalized = word.trim().toLowerCase()
    if (
        !normalized ||
        normalized.length > 64 ||
        [...normalized].some(character => /\s/u.test(character) || character.charCodeAt(0) < 32)
    )
        return null
    return normalized
}

export function normalizedDictionary(words: unknown): Set<string> {
    const dictionary = new Set<string>()
    if (!Array.isArray(words)) return dictionary
    for (const value of words) {
        if (typeof value !== 'string') continue
        const word = normalizeDictionaryWord(value)
        if (word) dictionary.add(word)
        if (dictionary.size >= MAX_DICTIONARY_WORDS) break
    }
    return dictionary
}

function createRuntime(key: string, epoch: number): DictionaryRuntime {
    return {
        scopeKey: key,
        epoch,
        words: readStoredDictionary(key, key === ANONYMOUS_DICT_KEY),
        revision: 0,
        pendingRemovals: new Set(),
        syncPromise: null,
        lifetime: null,
    }
}

function sameWords(left: Iterable<string>, right: Iterable<string>): boolean {
    const a = [...left]
    const b = [...right]
    return a.length === b.length && a.every((word, index) => word === b[index])
}

export function wordAtIssue(content: string, issue: SpellCheckIssue): string {
    const line = content.split('\n')[issue.line - 1] ?? ''
    return line.slice(issue.column_start - 1, issue.column_end - 1).toLowerCase()
}

export function usePersonalDictionary(
    scope: PersonalDictionaryScope,
    shouldSync = true
): PersonalDictionaryController {
    const key = scopeKey(scope)
    const identityRef = useRef({ key, epoch: 0 })
    if (identityRef.current.key !== key) {
        identityRef.current = { key, epoch: identityRef.current.epoch + 1 }
    }

    const runtimeRef = useRef<DictionaryRuntime>(createRuntime(key, identityRef.current.epoch))
    const renderWordsRef = useRef<Set<string>>(runtimeRef.current.words)
    if (runtimeRef.current.scopeKey !== key) {
        runtimeRef.current = createRuntime(key, identityRef.current.epoch)
        renderWordsRef.current = runtimeRef.current.words
    }
    const scopeRef = useRef(scope)
    scopeRef.current = scope
  const [, rerender] = useState(0)
  const [loading, setLoading] = useState(false)
  const [syncError, setSyncError] = useState<string | null>(null)

    const isCurrentIdentity = useCallback(
        (
            runtime: DictionaryRuntime,
            lifetime: object | null,
            authToken: string | null
        ): boolean => {
            const currentScope = scopeRef.current
            return (
                runtimeRef.current === runtime &&
                runtime.lifetime === lifetime &&
                lifetime !== null &&
                runtime.scopeKey === scopeKey(currentScope) &&
                identityRef.current.epoch === runtime.epoch &&
                currentScope.authToken === authToken &&
                currentScope.confirmed
            )
        },
        []
    )

    const publish = useCallback((runtime: DictionaryRuntime) => {
        renderWordsRef.current = new Set(runtime.words)
        rerender(value => value + 1)
    }, [])

    const sync = useCallback(async (): Promise<ReadonlySet<string>> => {
        const runtime = runtimeRef.current
        const currentScope = scopeRef.current
        if (!currentScope.confirmed || !currentScope.ownerId) {
            return new Set(runtime.words)
        }
        if (runtime.syncPromise) return runtime.syncPromise

        const token = currentScope.authToken
        if (!token) return new Set(runtime.words)
        const ownerId = currentScope.ownerId
        const lifetime = runtime.lifetime
        if (!lifetime) return new Set(runtime.words)
        const requestContext = {
            authToken: token,
            isCurrent: () => isCurrentIdentity(runtime, lifetime, token),
        }

        let promise!: Promise<ReadonlySet<string>>
        promise = (async () => {
            setLoading(true)
            setSyncError(null)
            let dispatchedRevision: number | null = null
            try {
        // Reconcile again if a same-owner edit lands while a request is in flight.
        for (;;) {
                    if (!isCurrentIdentity(runtime, lifetime, token)) return new Set(runtime.words)
                    const response = await apiClient.getMe(requestContext)
                    if (!isCurrentIdentity(runtime, lifetime, token) || response.id !== ownerId) {
                        return new Set(runtime.words)
                    }

                    const remote = normalizedDictionary(response.preferences.spell_dictionary)
                    const merged = new Set(
                        [...remote, ...runtime.words]
                            .filter(word => !runtime.pendingRemovals.has(word))
                            .slice(0, MAX_DICTIONARY_WORDS)
                    )
                    runtime.words = merged
                    storeDictionary(runtime.scopeKey, merged)
                    publish(runtime)

                    const patchRevision = runtime.revision
                    dispatchedRevision = patchRevision
                    const remoteWords = [...remote]
                    const mergedWords = [...merged]
                    if (sameWords(remoteWords, mergedWords)) {
                        runtime.pendingRemovals.clear()
                        return new Set(merged)
                    }
                    if (
                        !isCurrentIdentity(runtime, lifetime, token) ||
                        runtime.revision !== patchRevision
                    )
                        continue

                    await apiClient.updateMePreferences(
                        { spell_dictionary: mergedWords },
                        {
                            ...requestContext,
                            isCurrent: () =>
                                isCurrentIdentity(runtime, lifetime, token) &&
                                runtime.revision === patchRevision,
                        }
                    )
                    if (!isCurrentIdentity(runtime, lifetime, token)) return new Set(runtime.words)
                    if (runtime.revision !== patchRevision) continue
                    runtime.pendingRemovals.clear()
                    return new Set(runtime.words)
                }
            } catch {
                if (
                    dispatchedRevision !== null
                    && runtime.revision !== dispatchedRevision
                    && isCurrentIdentity(runtime, lifetime, token)
                ) {
                    runtime.syncPromise = null
                    return sync()
                }
                if (isCurrentIdentity(runtime, lifetime, token)) {
                    setSyncError('Your saved dictionary could not be synchronized. Local changes remain on this device.')
                }
                return new Set(runtime.words)
            } finally {
                if (runtime.syncPromise === promise) {
                    runtime.syncPromise = null
                    if (isCurrentIdentity(runtime, lifetime, token)) setLoading(false)
                }
            }
        })()
        runtime.syncPromise = promise
        return runtime.syncPromise
    }, [isCurrentIdentity, publish])

    const mutate = useCallback(
        (word: string, remove: boolean) => {
            const normalized = normalizeDictionaryWord(word)
            const runtime = runtimeRef.current
            if (!normalized || !scopeRef.current.confirmed) return
            if (
                !remove &&
                runtime.words.size >= MAX_DICTIONARY_WORDS &&
                !runtime.words.has(normalized)
            )
                return
            if (remove) runtime.pendingRemovals.add(normalized)
            else runtime.pendingRemovals.delete(normalized)
            if (remove) runtime.words.delete(normalized)
            else runtime.words.add(normalized)
            runtime.revision += 1
            storeDictionary(runtime.scopeKey, runtime.words)
            publish(runtime)
            void sync()
        },
        [publish, sync]
    )

    const addWord = useCallback((word: string) => mutate(word, false), [mutate])
    const removeWord = useCallback((word: string) => mutate(word, true), [mutate])
    const getWords = useCallback(() => new Set(renderWordsRef.current), [])

    useEffect(() => {
        const runtime = runtimeRef.current
        const lifetime = {}
        runtime.lifetime = lifetime
        renderWordsRef.current = new Set(runtime.words)
        publish(runtime)
        setLoading(false)
        if (shouldSync) void sync()

        const handleChange = (event: Event) => {
            const detail = (event as CustomEvent<{ scopeKey?: string }>).detail
            if (
                detail?.scopeKey !== runtime.scopeKey ||
                !isCurrentIdentity(runtime, lifetime, scopeRef.current.authToken)
            )
                return
            const incoming = readStoredDictionary(
                runtime.scopeKey,
                runtime.scopeKey === ANONYMOUS_DICT_KEY
            )
            for (const word of incoming) runtime.pendingRemovals.delete(word)
            for (const word of runtime.words) {
                if (!incoming.has(word)) runtime.pendingRemovals.add(word)
            }
            if (
                [...incoming].some(word => !runtime.words.has(word)) ||
                [...runtime.words].some(word => !incoming.has(word))
            ) {
                runtime.revision += 1
            }
            runtime.words = incoming
            publish(runtime)
        }
        if (typeof window !== 'undefined')
            window.addEventListener(PERSONAL_DICTIONARY_EVENT, handleChange)
        return () => {
            if (runtime.lifetime === lifetime) {
                runtime.lifetime = null
                runtime.syncPromise = null
            }
            if (typeof window !== 'undefined')
                window.removeEventListener(PERSONAL_DICTIONARY_EVENT, handleChange)
        }
    }, [isCurrentIdentity, key, publish, shouldSync, sync, scope.authToken])

    const words = runtimeRef.current.scopeKey === key ? renderWordsRef.current : new Set<string>()
  return { words, loading, error: syncError, sync, getWords, addWord, removeWord }
}

export function useSpellCheck(
    latexContent: string,
    enabled: boolean,
    language = 'en-US',
    debounceMs = 5000,
    scope: PersonalDictionaryScope = { ownerId: null, authToken: null, confirmed: true }
) {
    const dictionaryController = usePersonalDictionary(scope, enabled)
    const [rawIssues, setRawIssues] = useState<SpellCheckIssue[]>([])
    const [loading, setLoading] = useState(false)
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
    const requestGenerationRef = useRef(0)

    useEffect(() => {
        const generation = ++requestGenerationRef.current
        setLoading(false)
        setRawIssues([])

        if (!enabled || !latexContent.trim()) {
            return () => {
                if (requestGenerationRef.current === generation) requestGenerationRef.current += 1
            }
        }

        if (timerRef.current) clearTimeout(timerRef.current)
        timerRef.current = setTimeout(async () => {
            if (requestGenerationRef.current !== generation) return
            setLoading(true)
            try {
                const resp = await apiClient.checkSpelling(latexContent, language)
                if (requestGenerationRef.current === generation) setRawIssues(resp.issues)
            } catch {
                if (requestGenerationRef.current === generation) setRawIssues([])
            } finally {
                if (requestGenerationRef.current === generation) setLoading(false)
            }
        }, debounceMs)

        return () => {
            if (timerRef.current) clearTimeout(timerRef.current)
            if (requestGenerationRef.current === generation) requestGenerationRef.current += 1
        }
    }, [latexContent, enabled, language, debounceMs])

    useEffect(() => {
        if (!enabled) setRawIssues([])
    }, [enabled])

    const issues = useMemo(
        () =>
            rawIssues.filter(
                issue => !dictionaryController.words.has(wordAtIssue(latexContent, issue))
            ),
        [dictionaryController.words, latexContent, rawIssues]
    )

    return {
        issues,
        loading,
        personalDictionary: dictionaryController,
        getPersonalDictionary: dictionaryController.getWords,
        addWordToDictionary: dictionaryController.addWord,
        removeWordFromDictionary: dictionaryController.removeWord,
    }
}
