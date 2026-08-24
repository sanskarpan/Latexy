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
 * Account sync: there is currently no backend endpoint for a persisted user
 * theme preference (checked `api-client.ts` — the closest analogue,
 * `updateNotificationPrefs`, is a different feature). Until that endpoint
 * exists, mode is additionally cached per-account in localStorage
 * (`latexy-theme:acct:{userId}`) so at least a signed-in user gets a
 * consistent preference across browsers/devices *that have already seen*
 * that account locally, and a real cross-device sync should replace this
 * with a proper `PATCH /users/me` (or similar) call once one is added.
 */

type Mode = 'light' | 'dark'

interface ThemeCtx {
  mode: Mode
  setMode: (m: Mode) => void
  toggle: () => void
}

const Ctx = createContext<ThemeCtx | null>(null)

function acctKey(userId: string) {
  return `latexy-theme:acct:${userId}`
}

// Reads the mode the pre-paint bootstrap script already applied to
// `data-mode`, so `mode` reflects the real theme from the first client
// render onward (used to drive things like the toggle's own icon once
// mounted — see ModeToggle, which intentionally renders the SSR-default
// icon until then, since `mode` itself can only resolve to 'light' during
// SSR and reading the real value on the client's first render would be a
// hydration mismatch). Falls back to the cookie, then OS preference, for the
// rare case this runs before the bootstrap script has.
function readInitialMode(): Mode {
  if (typeof document === 'undefined') return 'light'
  const attr = document.documentElement.getAttribute('data-mode')
  if (attr === 'light' || attr === 'dark') return attr
  const m = document.cookie.match(/(?:^|; )latexy-theme=(light|dark)/)
  if (m) return m[1] as Mode
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Lazy initializer runs synchronously on first client render, so it already
  // matches whatever the pre-paint script set — no post-hydration flip.
  const [mode, setModeState] = useState<Mode>(readInitialMode)
  const { data: session } = useSession()
  const userId = session?.user?.id

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
      if ((cached === 'light' || cached === 'dark') && cached !== mode) {
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
    // Only run when the account identity changes, not on every mode change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId])

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

  const toggle = useCallback(() => setMode(mode === 'dark' ? 'light' : 'dark'), [mode, setMode])

  return <Ctx.Provider value={{ mode, setMode, toggle }}>{children}</Ctx.Provider>
}

export function useTheme(): ThemeCtx {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
