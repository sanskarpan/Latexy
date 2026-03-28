'use client'

import { useEffect, useRef, useState } from 'react'
import { lintLatex, autoFixAll as runAutoFixAll, type LintIssue } from '@/lib/latex-linter'

export function useLatexLinter(latexContent: string, enabled: boolean) {
  const [issues, setIssues] = useState<LintIssue[]>([])
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!enabled) {
      setIssues([])
      return
    }

    if (timerRef.current) clearTimeout(timerRef.current)

    timerRef.current = setTimeout(() => {
      setIssues(lintLatex(latexContent))
    }, 3000)

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [latexContent, enabled])

  function autoFixAll(latex: string): string {
    return runAutoFixAll(latex)
  }

  return { issues, autoFixAll }
}
