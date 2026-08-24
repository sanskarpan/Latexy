'use client'

import { Moon, Sun } from 'lucide-react'
import { useTheme } from './ThemeProvider'

/**
 * Light/dark toggle (redesign, PRD 2026-08-03). Token-styled so it looks correct
 * in all four theme variants. Placed in the header(s) and settings.
 *
 * First-paint correctness without a hydration mismatch: we render BOTH icons
 * every time (identical DOM on server and client, so no structural diff) and
 * let CSS show the right one based on the root `data-mode` attribute — which
 * the pre-paint inline script in the root layout sets before hydration. So the
 * correct glyph shows on the very first paint with no swap/flash, and there is
 * no element-type mismatch for React to warn about. The `.mode-icon-*` rules
 * live in globals.css.
 */
export default function ModeToggle({ className = '' }: { className?: string }) {
  const { toggle } = useTheme()
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label="Toggle light or dark mode"
      title="Toggle theme"
      className={`inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-line text-fg-2 transition hover:text-accent hover:border-accent ${className}`}
    >
      <Moon size={15} className="mode-icon-light" />
      <Sun size={15} className="mode-icon-dark" />
    </button>
  )
}
