'use client'

import { useState, useCallback } from 'react'

/**
 * Manages auto-compile enabled/disabled state with localStorage persistence.
 */
export function useAutoCompile() {
  const [enabled, setEnabled] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_auto_compile') === 'true'
  })

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev
      localStorage.setItem('latexy_auto_compile', String(next))
      return next
    })
  }, [])

  return { enabled, toggle }
}
