'use client'

import { Moon, Sun } from 'lucide-react'
import { useTheme } from './ThemeProvider'

/**
 * Light/dark toggle (redesign, PRD 2026-08-03). Token-styled so it looks correct
 * in all four theme variants. Placed in the header(s) and settings.
 */
export default function ModeToggle({ className = '' }: { className?: string }) {
  const { mode, toggle } = useTheme()
  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
      title={mode === 'dark' ? 'Light mode' : 'Dark mode'}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-[var(--radius-md)] border border-line text-fg-2 transition hover:text-accent hover:border-accent ${className}`}
    >
      {mode === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
    </button>
  )
}
