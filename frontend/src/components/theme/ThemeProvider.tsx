'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'

/**
 * Light/dark mode runtime (redesign, PRD 2026-08-03).
 *
 * The pre-paint inline script in the root layout already sets `data-mode` before
 * first paint (no flash), reading the `latexy-theme` cookie or the OS preference.
 * This provider owns *user* toggles from then on: it reflects the current mode,
 * and `setMode` writes the cookie (for SSR on the next load) + the `data-mode`
 * attribute. Aesthetic (typeset/compiler) is handled separately by route.
 */

type Mode = 'light' | 'dark'

interface ThemeCtx {
  mode: Mode
  setMode: (m: Mode) => void
  toggle: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)

function readInitialMode(): Mode {
  if (typeof document === 'undefined') return 'light'
  const attr = document.documentElement.getAttribute('data-mode')
  if (attr === 'light' || attr === 'dark') return attr
  const m = document.cookie.match(/(?:^|; )latexy-theme=(light|dark)/)
  if (m) return m[1] as Mode
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<Mode>('light')

  // Sync from what the bootstrap script already applied (avoids a flash).
  useEffect(() => {
    setModeState(readInitialMode())
  }, [])

  const setMode = useCallback((m: Mode) => {
    setModeState(m)
    document.documentElement.setAttribute('data-mode', m)
    // 1-year cookie so SSR matches on the next load; Lax is fine (not sensitive).
    document.cookie = `latexy-theme=${m}; path=/; max-age=31536000; SameSite=Lax`
  }, [])

  const toggle = useCallback(() => setMode(mode === 'dark' ? 'light' : 'dark'), [mode, setMode])

  return <Ctx.Provider value={{ mode, setMode, toggle }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
