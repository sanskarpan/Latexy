'use client'

import { Moon, Sun } from 'lucide-react'
import { useTheme } from './ThemeProvider'

/**
 * Light/dark toggle (redesign, PRD 2026-08-03). Token-styled so it looks correct
 * in all four theme variants. Placed in the header(s) and settings.
 *
 * `ThemeProvider` lazily initializes its mode from the already-applied
 * `data-mode` attribute (set pre-paint, before React hydrates), so this glyph
 * matches the real mode on the very first client render — no post-mount icon
 * flip. That first client render can still legitimately differ from the
 * server-rendered markup (SSR has no access to the theme cookie), which is
 * the same class of intentional mismatch `suppressHydrationWarning` already
 * covers on `<html>` in the root layout; it's applied here too so React
 * doesn't warn about a difference that's correct by design.
 */
export default function ModeToggle({ className = '' }: { className?: string }) {
  const { mode, toggle } = useTheme()
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      title={mode === 'dark' ? 'Light mode' : 'Dark mode'}
      suppressHydrationWarning
      className={`inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-line text-fg-2 transition hover:text-accent hover:border-accent ${className}`}
    >
      {mode === 'dark' ? <Sun size={15} suppressHydrationWarning /> : <Moon size={15} suppressHydrationWarning />}
    </button>
  )
}
