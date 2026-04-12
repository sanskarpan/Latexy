'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient, type ConfidenceScoreResponse } from '@/lib/api-client'

const DEBOUNCE_MS = 15_000   // 15 seconds after last change
const MIN_CONTENT_LEN = 200  // skip tiny/empty content

export function useConfidenceScore(latexContent: string) {
  const [result, setResult] = useState<ConfidenceScoreResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Debounced auto-score on content change
  useEffect(() => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const res = await apiClient.confidenceScore(latexContent)
        setResult(res)
      } catch {
        // silent — score is optional enhancement
      } finally {
        setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [latexContent])

  // Immediate refetch (e.g. triggered by badge click)
  const refetch = useCallback(async () => {
    if (!latexContent || latexContent.length < MIN_CONTENT_LEN) return
    if (timerRef.current) clearTimeout(timerRef.current)

    setLoading(true)
    try {
      const res = await apiClient.confidenceScore(latexContent)
      setResult(res)
    } catch {
      // silent
    } finally {
      setLoading(false)
    }
  }, [latexContent])

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  return { result, loading, refetch }
}
