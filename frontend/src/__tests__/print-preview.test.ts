/**
 * Feature 89 — Print Preview Mode tests.
 *
 * Tests:
 * 1. analyzeColorUsage — empty source → no warnings
 * 2. analyzeColorUsage — \textcolor usage → 1 warning with correct line + command
 * 3. analyzeColorUsage — \definecolor + \color on different lines → 2 warnings
 * 4. analyzeColorUsage — comment line containing \textcolor is skipped
 * 5. analyzeColorUsage — multiple commands on same line → only 1 warning (first command wins)
 * 6. analyzeColorUsage — \pagecolor and \colorbox detected
 * 7. analyzeColorUsage — clean resume without color commands → no warnings
 * 8. analyzeColorUsage — context is trimmed and capped at 100 chars
 */

import { describe, test, expect } from 'vitest'
import { analyzeColorUsage } from '../lib/print-preview'

describe('analyzeColorUsage', () => {

  test('returns empty array for source with no color commands', () => {
    const latex = [
      '\\documentclass{article}',
      '\\usepackage{fontenc}',
      '\\begin{document}',
      'Hello \\textbf{World}',
      '\\end{document}',
    ].join('\n')
    expect(analyzeColorUsage(latex)).toEqual([])
  })

  test('detects \\textcolor with correct line number', () => {
    const latex = [
      '\\documentclass{article}',
      '\\usepackage{xcolor}',
      '\\begin{document}',
      '\\textcolor{red}{Important!}',
      '\\end{document}',
    ].join('\n')
    const warnings = analyzeColorUsage(latex)
    expect(warnings).toHaveLength(1)
    expect(warnings[0].line).toBe(4)
    expect(warnings[0].command).toBe('\\textcolor')
  })

  test('detects \\definecolor and \\color on separate lines', () => {
    const latex = [
      '\\documentclass{article}',
      '\\definecolor{myblue}{RGB}{0,0,255}',
      '\\begin{document}',
      '{\\color{myblue} Blue text}',
      '\\end{document}',
    ].join('\n')
    const warnings = analyzeColorUsage(latex)
    expect(warnings).toHaveLength(2)
    expect(warnings[0].command).toBe('\\definecolor')
    expect(warnings[0].line).toBe(2)
    expect(warnings[1].command).toBe('\\color')
    expect(warnings[1].line).toBe(4)
  })

  test('skips comment lines (lines starting with %)', () => {
    const latex = [
      '\\documentclass{article}',
      '% \\textcolor{red}{this is commented out}',
      '\\begin{document}',
      '\\end{document}',
    ].join('\n')
    const warnings = analyzeColorUsage(latex)
    expect(warnings).toHaveLength(0)
  })

  test('skips comment lines with leading whitespace', () => {
    const latex = [
      '\\documentclass{article}',
      '  % \\textcolor{blue}{also commented}',
      '\\begin{document}',
      '\\end{document}',
    ].join('\n')
    expect(analyzeColorUsage(latex)).toHaveLength(0)
  })

  test('emits only one warning per line when multiple commands present', () => {
    const latex = '\\textcolor{red}{x} \\colorbox{yellow}{y}'
    const warnings = analyzeColorUsage(latex)
    expect(warnings).toHaveLength(1)
    expect(warnings[0].line).toBe(1)
  })

  test('detects \\pagecolor and \\colorbox', () => {
    const latex = [
      '\\pagecolor{white}',
      '\\colorbox{yellow}{highlight}',
    ].join('\n')
    const warnings = analyzeColorUsage(latex)
    expect(warnings).toHaveLength(2)
    const commands = warnings.map((w) => w.command)
    expect(commands).toContain('\\pagecolor')
    expect(commands).toContain('\\colorbox')
  })

  test('context is trimmed of leading whitespace', () => {
    const latex = '    \\textcolor{red}{indented}'
    const warnings = analyzeColorUsage(latex)
    expect(warnings[0].context).not.toMatch(/^\s/)
    expect(warnings[0].context).toBe('\\textcolor{red}{indented}')
  })

  test('context is capped at 100 characters', () => {
    const longLine = '\\textcolor{red}{' + 'x'.repeat(200) + '}'
    const warnings = analyzeColorUsage(longLine)
    expect(warnings[0].context.length).toBeLessThanOrEqual(100)
  })

  test('clean resume template returns no warnings', () => {
    const latex = [
      '\\documentclass[11pt,a4paper]{moderncv}',
      '\\moderncvstyle{classic}',
      '\\moderncvcolor{blue}',   // moderncv color setting — does NOT use \\textcolor etc.
      '\\begin{document}',
      '\\cventry{2020--2024}{Engineer}{Acme}{SF}{}{Built systems}',
      '\\end{document}',
    ].join('\n')
    // \\moderncvcolor is not in our COLOR_COMMANDS list → no warning
    expect(analyzeColorUsage(latex)).toHaveLength(0)
  })

})
