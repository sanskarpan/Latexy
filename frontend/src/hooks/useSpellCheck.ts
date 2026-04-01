'use client'

import { useEffect, useRef, useState } from 'react'
import { apiClient, type SpellCheckIssue } from '@/lib/api-client'

const DICT_KEY = 'latexy_spell_dictionary'

export function getPersonalDict(): Set<string> {
  if (typeof window === 'undefined') return new Set()
  try {
    return new Set(JSON.parse(localStorage.getItem(DICT_KEY) || '[]'))
  } catch {
    return new Set()
  }
}

export function addWordToDict(word: string): void {
  const dict = getPersonalDict()
  dict.add(word.toLowerCase())
  if (typeof window !== 'undefined') {
    localStorage.setItem(DICT_KEY, JSON.stringify([...dict]))
  }
}

export function useSpellCheck(
  latexContent: string,
  enabled: boolean,
  language = 'en-US',
  debounceMs = 5000,
) {
  const [issues, setIssues] = useState<SpellCheckIssue[]>([])
  const [loading, setLoading] = useState(false)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled || !latexContent || latexContent.length < 100) {
      setIssues([])
      return
    }

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(async () => {
      setLoading(true)
      try {
        const resp = await apiClient.checkSpelling(latexContent, language)
        setIssues(resp.issues)
      } catch {
        setIssues([])
      } finally {
        setLoading(false)
      }
    }, debounceMs)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [latexContent, enabled, language, debounceMs])

  // Clear issues when disabled
  useEffect(() => {
    if (!enabled) setIssues([])
  }, [enabled])

  return { issues, loading }
}
