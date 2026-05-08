/**
 * Feature 89 — Print Preview Mode utilities.
 *
 * Pure functions for detecting LaTeX color-command usage so PDFPreview can
 * warn the user when elements may become invisible or lose meaning in B&W print.
 */

// More specific commands (longer prefix) must come before shorter ones so that
// e.g. \colorbox is matched before \color (which is its prefix).
export const COLOR_COMMANDS = [
  '\\textcolor',
  '\\colorbox',
  '\\definecolor',
  '\\pagecolor',
  '\\color',
] as const

export interface ColorWarning {
  /** 1-based line number in the LaTeX source */
  line: number
  /** The matched command, e.g. "\\textcolor" */
  command: string
  /** Trimmed source line (max 100 chars) for display */
  context: string
}

/**
 * Scan `latex` for color-related commands and return one warning per matching
 * line. Comment lines (trimmed start with `%`) are skipped.
 */
export function analyzeColorUsage(latex: string): ColorWarning[] {
  const warnings: ColorWarning[] = []
  const lines = latex.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i]
    const trimmed = raw.trimStart()
    if (trimmed.startsWith('%')) continue
    for (const cmd of COLOR_COMMANDS) {
      if (raw.includes(cmd)) {
        warnings.push({ line: i + 1, command: cmd, context: trimmed.slice(0, 100) })
        break
      }
    }
  }
  return warnings
}
