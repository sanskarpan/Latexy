'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type QuickScoreResponse } from '@/lib/api-client'

const DEBOUNCE_MS = 10_000   // 10 seconds after last change
const MIN_CONTENT_LEN = 200  // skip tiny content

export function useQuickATSScore(
  latexContent: string,
  jobDescription?: string,
) {
  const [result, setResult] = useState<QuickScoreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Monotonic request token: only the most recent request may commit state.
  // Guards against out-of-order resolution and setState after unmount.
  const requestIdRef = useRef(0)
  const mountedRef = useRef(true)

  const runScore = useCallback(async () => {
    const reqId = ++requestIdRef.current
    const isCurrent = () => mountedRef.current && reqId === requestIdRef.current
    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.quickScoreATS(latexContent, jobDescription)
      if (isCurrent()) setResult(res)
    } catch {
      if (isCurrent()) setError('Quick score failed')
    } finally {
      if (isCurrent()) setLoading(false)
    }
  }, [latexContent, jobDescription])

  // Debounced auto-score on content change
  useEffect(() => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(() => {
      runScore()
    }, DEBOUNCE_MS)

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
