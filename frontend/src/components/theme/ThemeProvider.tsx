'use client'

import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useSession } from '@/lib/auth-client'
import { apiClient } from '@/lib/api-client'

/**
 * Light/dark mode runtime (redesign, PRD 2026-08-03).
 *
 * The pre-paint inline script in the root layout already sets `data-mode` before
 * first paint (no flash), reading the `latexy-theme` cookie or the OS preference.
 * This provider owns *user* toggles from then on: it reflects the current mode,
 * and `setMode` writes the cookie (for SSR on the next load) + the `data-mode`
 * attribute. Aesthetic (typeset/compiler) is handled separately by route.
 *
 * Signed-in account preferences are fetched and updated through the account
 * API. A per-account localStorage value is applied first as a fast cache; the
 * cookie keeps server-rendered routes aligned on this device.
 */

type Mode = 'light' | 'dark'
type Contrast = 'normal' | 'high'

interface ThemeCtx {
  ready: boolean
  mode: Mode
  setMode: (m: Mode) => void
  toggle: () => void
  contrast: Contrast
  setContrast: (contrast: Contrast) => void
  toggleContrast: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)

function acctKey(userId: string) {
  return `latexy-theme:acct:${userId}`
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // The pre-paint script applies the saved/OS theme before styling. Keep state
  // deterministic during SSR and first hydration, then synchronize controls
  // from those already-applied root attributes in the effect below.
  const [mode, setModeState] = useState<Mode>('light')
  const [contrast, setContrastState] = useState<Contrast>('normal')
  const [ready, setReady] = useState(false)
  const { data: session } = useSession()
  const userId = session?.user?.id

  // The bootstrap has already set these attributes, so adopting them does not
  // change the colors users see. It only brings the React state behind the
  // theme controls into sync after hydration.
  useEffect(() => {
    const modeAttr = document.documentElement.getAttribute('data-mode')
    if (modeAttr === 'light' || modeAttr === 'dark') setModeState(modeAttr)

    const contrastAttr = document.documentElement.getAttribute('data-contrast')
    if (contrastAttr === 'normal' || contrastAttr === 'high') {
      setContrastState(contrastAttr)
    }
    // Controls are server-rendered before React can attach their handlers.
    // Keep them disabled until this synchronization completes so a click
    // during a slow hydration cannot appear to succeed while being discarded.
    setReady(true)
  }, [])

  const applyMode = useCallback((m: Mode) => {
    setModeState(m)
    document.documentElement.setAttribute('data-mode', m)
    // 1-year cookie so SSR matches on the next load; Lax is fine (not sensitive).
    document.cookie = `latexy-theme=${m}; path=/; max-age=31536000; SameSite=Lax`
  }, [])

  // Hydrate from the signed-in account's cached preference (if any) once the
  // session resolves, so a user who set dark mode elsewhere and logs in here
  // picks it up instead of staying on this device's local/OS default.
  useEffect(() => {
    if (!userId) return
    // Fast path: this device's cached account preference (avoids a flash while
    // the network request is in flight).
    try {
      const cached = window.localStorage.getItem(acctKey(userId))
      if (cached === 'light' || cached === 'dark') {
        applyMode(cached)
      }
    } catch {
      // localStorage unavailable (private mode, etc.) — fall back to device-local only.
    }
    // Source of truth: the account's synced theme, so a user who set dark mode
    // on another device sees it here too (true cross-device sync).
    apiClient.getMe()
      .then((me) => {
        const t = me.preferences?.theme
        if (t === 'light' || t === 'dark') {
          try { window.localStorage.setItem(acctKey(userId), t) } catch { /* ignore */ }
          applyMode(t)
        }
      })
      .catch(() => { /* anonymous/offline — device-local value stands */ })
  }, [applyMode, userId])

  const setMode = useCallback(
    (m: Mode) => {
      applyMode(m)
      if (userId) {
        try {
          window.localStorage.setItem(acctKey(userId), m)
        } catch {
          // Best-effort only — device-local cookie already covers this device.
        }
        // Persist to the account so the choice follows the user across devices.
        apiClient.updateMePreferences({ theme: m }).catch(() => { /* best-effort */ })
      }
    },
    [applyMode, userId],
  )

  const toggle = useCallback(() => {
    const appliedMode = document.documentElement.getAttribute('data-mode')
    setMode(appliedMode === 'dark' ? 'light' : 'dark')
  }, [setMode])

  const setContrast = useCallback((nextContrast: Contrast) => {
    setContrastState(nextContrast)
    document.documentElement.setAttribute('data-contrast', nextContrast)
    document.cookie = `latexy-contrast=${nextContrast}; path=/; max-age=31536000; SameSite=Lax`
  }, [])

  const toggleContrast = useCallback(() => {
    const appliedContrast = document.documentElement.getAttribute('data-contrast')
    setContrast(appliedContrast === 'high' ? 'normal' : 'high')
  }, [setContrast])

  return (
    <Ctx.Provider value={{ ready, mode, setMode, toggle, contrast, setContrast, toggleContrast }}>
      {children}
    </Ctx.Provider>
  )
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
