'use client'

import { useEffect, useState, useCallback } from 'react'

const AUTO_COMPILE_STORAGE_KEY = 'latexy_auto_compile'

/**
 * Manages auto-compile enabled/disabled state with localStorage persistence.
 */
export function useAutoCompile() {
  const [enabled, setEnabled] = useState(false)

  useEffect(() => {
    setEnabled(localStorage.getItem(AUTO_COMPILE_STORAGE_KEY) === 'true')
  }, [])

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev
      localStorage.setItem(AUTO_COMPILE_STORAGE_KEY, String(next))
      return next
    })
  }, [])

  return { enabled, toggle }
}
