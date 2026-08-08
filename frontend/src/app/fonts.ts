/**
 * Webfonts for the redesign (PRD 2026-08-03; typography reworked 2026-08-04).
 *
 * Loaded via next/font (self-hosted, subset, display:swap) and exposed as CSS
 * variables consumed by the design tokens:
 *   --font-bricolage → display (bold grotesque — distinctive, modern/technical)
 *   --font-geist-sans → body (clean grotesque)
 *   --font-jetbrains  → mono (UI labels, code, metadata) — both aesthetics
 *
 * The all-serif Fraunces treatment was dropped (monotonous + overused); the site
 * now pairs a characterful grotesque display with a neutral sans body.
 */
import { JetBrains_Mono, Bricolage_Grotesque } from 'next/font/google'
import { GeistSans } from 'geist/font/sans'

export const bricolage = Bricolage_Grotesque({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-bricolage',
  axes: ['opsz'], // optical sizing; wght is included for the variable font
  fallback: ['Hanken Grotesk', 'Helvetica Neue', 'system-ui', 'sans-serif'],
})

export const jetbrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-jetbrains',
  fallback: ['SF Mono', 'ui-monospace', 'Menlo', 'Monaco', 'monospace'],
})

// Geist ships as its own package (not on Google Fonts); `.variable` defines
// `--font-geist-sans`.
export const geist = GeistSans

/** Combined variable classes to apply on <html>. */
export const fontVariables = `${bricolage.variable} ${jetbrainsMono.variable} ${geist.variable}`
