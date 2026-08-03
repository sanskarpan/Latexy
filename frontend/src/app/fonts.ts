/**
 * Webfonts for the redesign (PRD 2026-08-03, Phase 0).
 *
 * These are loaded via next/font (self-hosted, subset, display:swap) and exposed
 * as CSS variables consumed by the design tokens in globals.css:
 *   --font-fraunces  → Typeset display + body (serif, variable, optical sizing)
 *   --font-jetbrains → shared mono (UI labels, code, metadata) — both aesthetics
 *   --font-geist     → Compiler body (grotesque)
 *
 * Fixes the audited bug where `Inter` was referenced in tailwind.config but never
 * actually delivered, so the site rendered in the OS default font.
 */
import { Fraunces, JetBrains_Mono } from 'next/font/google'
import { GeistSans } from 'geist/font/sans'

export const fraunces = Fraunces({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-fraunces',
  axes: ['opsz'], // optical sizing: large opsz for display, text opsz for body
  fallback: ['Hoefler Text', 'Iowan Old Style', 'Charter', 'Palatino', 'Georgia', 'serif'],
})

export const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains',
  fallback: ['SF Mono', 'ui-monospace', 'Menlo', 'Monaco', 'monospace'],
})

// Geist is not on Google Fonts; it ships as its own package. Its `.variable`
// class defines `--font-geist-sans`, which the design tokens reference.
export const geist = GeistSans

/** Combined variable classes to apply on <html>. */
export const fontVariables = `${fraunces.variable} ${jetbrainsMono.variable} ${geist.variable}`
