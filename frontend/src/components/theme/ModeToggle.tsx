'use client'

import { useEffect, useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { useTheme } from './ThemeProvider'

/**
 * Light/dark toggle (redesign, PRD 2026-08-03). Token-styled so it looks correct
 * in all four theme variants. Placed in the header(s) and settings.
 *
 * `ThemeProvider` lazily initializes its `mode` state by reading the
 * already-applied `data-mode` attribute (set pre-paint, before React
 * hydrates). That's fine for the actual dark-mode *styling*, because
 * `[data-mode]` drives CSS outside of React's tree and never participates in
 * hydration diffing. But `mode` is also plain React state, and on the server
 * it can only ever resolve to the 'light' default (no `document` to read).
 * If this component swaps between the `Sun`/`Moon` icons based on `mode`
 * from the very first render, the client's first (hydrating) render can
 * legitimately compute 'dark' — a different child element type than the
 * server rendered. That's a *structural* mismatch (a different component in
 * that slot, not just different text/attributes), which
 * `suppressHydrationWarning` does NOT cover — it only silences text/attribute
 * differences one level deep, never a swapped element type — so it produces
 * React hydration errors #418/#423 on every page this header renders on.
 *
 * Fix: render the SSR-default icon (`Moon`, matching `mode === 'light'`)
 * until mounted, then switch to the real icon in an effect. The switch is a
 * normal post-hydration DOM update, not part of hydration diffing, so it
 * can't mismatch.
 */
export default function ModeToggle({ className = '' }: { className?: string }) {
  const { mode, toggle } = useTheme()
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])
  const resolvedMode = mounted ? mode : 'light'
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={resolvedMode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      title={resolvedMode === 'dark' ? 'Light mode' : 'Dark mode'}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-line text-fg-2 transition hover:text-accent hover:border-accent ${className}`}
    >
      {resolvedMode === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  )
}
