'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type QuickScoreResponse } from '@/lib/api-client'

const DEBOUNCE_MS = 600
const MIN_INTERVAL_MS = 2_000 // bound background requests while typing
const MIN_CONTENT_LEN = 200  // skip tiny content

export function useQuickATSScore(
  latexContent: string,
  jobDescription?: string,
) {
  const inputKey = JSON.stringify([latexContent, jobDescription ?? null])
  const [result, setResult] = useState<QuickScoreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Monotonic request token: only the most recent request may commit state.
  // Guards against out-of-order resolution and setState after unmount.
  const requestIdRef = useRef(0)
  const mountedRef = useRef(true)
  const lastStartedRef = useRef<number | null>(null)
  const activeRef = useRef<{ key: string; controller: AbortController; promise: Promise<void> } | null>(null)
  const completedRef = useRef<{ key: string; result: QuickScoreResponse } | null>(null)
  const currentInputRef = useRef(inputKey)
  currentInputRef.current = inputKey

  const runScore = useCallback(async () => {
    if (!mountedRef.current || currentInputRef.current !== inputKey) return
    if (completedRef.current?.key === inputKey) {
      setResult(completedRef.current.result)
      return
    }
    if (activeRef.current?.key === inputKey) return activeRef.current.promise
    activeRef.current?.controller.abort()
    const reqId = ++requestIdRef.current
    const controller = new AbortController()
    lastStartedRef.current = Date.now()
    const isCurrent = () => mountedRef.current && reqId === requestIdRef.current && currentInputRef.current === inputKey
    setLoading(true)
    setError(null)
    const promise = (async () => {
      try {
        const res = await apiClient.quickScoreATS(latexContent, jobDescription, controller.signal)
        if (isCurrent()) {
          completedRef.current = { key: inputKey, result: res }
          setResult(res)
        }
      } catch {
        if (isCurrent()) setError('Quick score failed')
      } finally {
        if (activeRef.current?.controller === controller) activeRef.current = null
        if (isCurrent()) setLoading(false)
      }
    })()
    activeRef.current = { key: inputKey, controller, promise }
    return promise
  }, [latexContent, jobDescription, inputKey])

  // Debounced auto-score on content change
  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    // Changing either input immediately invalidates the displayed result and
    // any request already in flight. Waiting until the next debounced request
    // starts leaves a window where an old response can overwrite the
    // badge for the new document.
    requestIdRef.current += 1
    activeRef.current?.controller.abort()
    activeRef.current = null
    setResult(null)
    setLoading(false)
    setError(null)

    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return

    const delay = lastStartedRef.current === null ? 0
      : Math.max(DEBOUNCE_MS, MIN_INTERVAL_MS - (Date.now() - lastStartedRef.current))
    timerRef.current = setTimeout(() => {
      void runScore()
    }, delay)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [latexContent, jobDescription, runScore])

  // Immediate refetch (e.g. after compile completes)
  const refetch = useCallback(async () => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return
    if (timerRef.current) clearTimeout(timerRef.current)
    await runScore()
  }, [latexContent, runScore])

  // Cleanup on unmount — invalidate any in-flight request.
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      requestIdRef.current += 1
      activeRef.current?.controller.abort()
      activeRef.current = null
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return {
    score: result?.score ?? null,
    grade: result?.grade ?? null,
    sectionsFound: result?.sections_found ?? [],
    missingSections: result?.missing_sections ?? [],
    keywordMatchPercent: result?.keyword_match_percent ?? null,
    loading,
    error,
    refetch,
  }
}
