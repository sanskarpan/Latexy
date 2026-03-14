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
  const abortRef = useRef<AbortController | null>(null)

  // Debounced auto-score on content change
  useEffect(() => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(async () => {
      setLoading(true)
      setError(null)
      try {
        const res = await apiClient.quickScoreATS(latexContent, jobDescription)
        setResult(res)
      } catch {
        setError('Quick score failed')
      } finally {
        setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [latexContent, jobDescription])

  // Immediate refetch (e.g. after compile completes)
  const refetch = useCallback(async () => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return
    if (timerRef.current) clearTimeout(timerRef.current)

    setLoading(true)
    setError(null)
    try {
      const res = await apiClient.quickScoreATS(latexContent, jobDescription)
      setResult(res)
    } catch {
      setError('Quick score failed')
    } finally {
      setLoading(false)
    }
  }, [latexContent, jobDescription])

  // Cleanup on unmount
  useEffect(() => {
    const abortController = abortRef.current
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      abortController?.abort()
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
