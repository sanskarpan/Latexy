'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { apiClient, type SpellCheckIssue } from '@/lib/api-client'

const DICT_KEY = 'latexy_spell_dictionary'
export const PERSONAL_DICTIONARY_EVENT = 'latexy:spell-dictionary-change'
const MAX_DICTIONARY_WORDS = 500
let dictionarySync: Promise<Set<string>> | null = null
const pendingDictionaryRemovals = new Set<string>()

export function normalizeDictionaryWord(word: string): string | null {
  const normalized = word.trim().toLowerCase()
  if (
    !normalized
    || normalized.length > 64
    || [...normalized].some((character) => /\s/u.test(character) || character.charCodeAt(0) < 32)
  ) return null
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

function storePersonalDict(dictionary: Set<string>): void {
  if (typeof window === 'undefined') return
  localStorage.setItem(DICT_KEY, JSON.stringify([...dictionary]))
  window.dispatchEvent(new CustomEvent(PERSONAL_DICTIONARY_EVENT))
}

export function getPersonalDict(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  try {
    return normalizedDictionary(JSON.parse(localStorage.getItem(DICT_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

export async function syncPersonalDictionary(): Promise<Set<string>> {
  if (dictionarySync) return dictionarySync
  dictionarySync = (async () => {
    const local = getPersonalDict()
    try {
      const me = await apiClient.getMe()
      const remote = normalizedDictionary(me.preferences.spell_dictionary)
      const merged = new Set(
        [...remote, ...local]
          .filter((word) => !pendingDictionaryRemovals.has(word))
          .slice(0, MAX_DICTIONARY_WORDS),
      )
      storePersonalDict(merged)
      const remoteWords = [...remote]
      const mergedWords = [...merged]
      if (JSON.stringify(remoteWords) !== JSON.stringify(mergedWords)) {
        await apiClient.updateMePreferences({ spell_dictionary: mergedWords })
        pendingDictionaryRemovals.clear()
      }
      return merged
    } catch {
      return local
    } finally {
      dictionarySync = null
    }
  })()
  return dictionarySync
}

export function addWordToDict(word: string): void {
  const normalized = normalizeDictionaryWord(word)
  if (!normalized) return
  const dict = getPersonalDict()
  if (dict.size >= MAX_DICTIONARY_WORDS && !dict.has(normalized)) return
  pendingDictionaryRemovals.delete(normalized)
  dict.add(normalized)
  storePersonalDict(dict)
  void syncPersonalDictionary()
}

export function removeWordFromDict(word: string): void {
  const normalized = normalizeDictionaryWord(word)
  if (!normalized) return
  const dict = getPersonalDict()
  if (!dict.delete(normalized)) return
  pendingDictionaryRemovals.add(normalized)
  storePersonalDict(dict)
  void syncPersonalDictionary()
}

export function wordAtIssue(content: string, issue: SpellCheckIssue): string {
  const line = content.split('\n')[issue.line - 1] ?? ''
  return line.slice(issue.column_start - 1, issue.column_end - 1).toLowerCase()
}

export function useSpellCheck(
  latexContent: string,
  enabled: boolean,
  language = 'en-US',
  debounceMs = 5000,
) {
  const [rawIssues, setRawIssues] = useState<SpellCheckIssue[]>([])
  const [dictionary, setDictionary] = useState<Set<string>>(() => getPersonalDict())
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

  // Clear issues when disabled
  useEffect(() => {
    if (!enabled) setRawIssues([])
  }, [enabled])

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return
    const refresh = () => setDictionary(getPersonalDict())
    window.addEventListener(PERSONAL_DICTIONARY_EVENT, refresh)
    void syncPersonalDictionary().then(setDictionary)
    return () => window.removeEventListener(PERSONAL_DICTIONARY_EVENT, refresh)
  }, [enabled])

  const issues = useMemo(
    () => rawIssues.filter((issue) => !dictionary.has(wordAtIssue(latexContent, issue))),
    [dictionary, latexContent, rawIssues],
  )

  return { issues, loading }
}
