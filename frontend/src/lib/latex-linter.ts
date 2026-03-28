// ─── Types ────────────────────────────────────────────────────────────────────

export interface LintIssue {
  line: number       // 1-based
  column: number     // 1-based
  endColumn: number  // 1-based, exclusive
  severity: 'error' | 'warning' | 'info'
  ruleId: string
  message: string
  fixable: boolean
  fix?: (lineContent: string) => string
}

interface PerLineRule {
  id: string
  pattern: RegExp
  message: string
  severity: LintIssue['severity']
  fixable: boolean
  fix?: (lineContent: string) => string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Context-aware fix for deprecated font-declaration commands.
 * Handles four patterns:
 *   {\old text}   → \new{text}
 *   \old word     → \new{word}   (bare word following whitespace)
 *   \old{...}     → \new{...}    (already-braced argument)
 *   \old          → \new         (at command boundary or EOL)
 */
function fixDeclarationToCommand(line: string, from: string, to: string): string {
  // { \old ... } → \new{...}
  let result = line.replace(
    new RegExp(`\\{\\\\${from}\\s+([^}]+)\\}`, 'g'),
    `\\${to}{$1}`
  )
  // \old word → \new{word}  (word = next non-space token, not a brace)
  result = result.replace(
    new RegExp(`(?<!\\w)\\\\${from}\\s+(\\S[^\\s}]*)`, 'g'),
    `\\${to}{$1}`
  )
  // \old{...} → \new{...}
  result = result.replace(
    new RegExp(`(?<!\\w)\\\\${from}\\{`, 'g'),
    `\\${to}{`
  )
  // bare \old at command boundary or end of line
  result = result.replace(
    new RegExp(`(?<!\\w)\\\\${from}(?=\\\\|$)`, 'g'),
    `\\${to}`
  )
  return result
}

// ─── Per-line rules ───────────────────────────────────────────────────────────

const PER_LINE_RULES: PerLineRule[] = [
  {
    id: 'deprecated-bf',
    pattern: /(?<!\w)\\bf(?=\s|\{|\\|$)/g,
    message: 'Deprecated: use \\textbf{} instead of \\bf',
    severity: 'warning',
    fixable: true,
    fix: (line) => fixDeclarationToCommand(line, 'bf', 'textbf'),
  },
  {
    id: 'deprecated-it',
    pattern: /(?<!\w)\\it(?=\s|\{|\\|$)/g,
    message: 'Deprecated: use \\textit{} instead of \\it',
    severity: 'warning',
    fixable: true,
    fix: (line) => fixDeclarationToCommand(line, 'it', 'textit'),
  },
  {
    id: 'deprecated-rm',
    pattern: /(?<!\w)\\rm(?=\s|\{|\\|$)/g,
    message: 'Deprecated: use \\textrm{} instead of \\rm',
    severity: 'warning',
    fixable: false,
  },
  {
    id: 'deprecated-tt',
    pattern: /(?<!\w)\\tt(?=\s|\{|\\|$)/g,
    message: 'Deprecated: use \\texttt{} instead of \\tt',
    severity: 'warning',
    fixable: false,
  },
  {
    id: 'wrong-quotes',
    pattern: /"[^"]*"/g,
    message: "Use LaTeX curly quotes: ``text'' instead of \"text\"",
    severity: 'info',
    fixable: true,
    fix: (line) => line.replace(/"([^"]+)"/g, "``$1''"),
  },
  {
    id: 'redundant-space',
    pattern: /\b(e\.g\.|i\.e\.|etc\.)\s(?!\}|\\|$)/g,
    message: 'Use e.g.\\ or e.g.~ to prevent incorrect inter-sentence spacing',
    severity: 'info',
    fixable: true,
    fix: (line) =>
      line.replace(/\b(e\.g\.|i\.e\.|etc\.)\s(?!\}|\\|$)/g, '$1\\ '),
  },
  {
    id: 'double-dollar',
    pattern: /\$\$[^$]+\$\$/g,
    message: 'Prefer \\[...\\] over $$...$$ for display math in LaTeX2e',
    severity: 'info',
    fixable: false,
  },
  {
    id: 'over-command',
    pattern: /(?<!\w)\\over(?=\s|{|\\|$)/g,
    message: 'Deprecated: use \\frac{}{} instead of \\over',
    severity: 'warning',
    fixable: false,
  },
  {
    id: 'multicol-ats-risk',
    pattern: /\\usepackage(?:\[[^\]]*\])?\{multicols?\}|\\begin\{multicols\*?\}/g,
    message: 'Multi-column layouts are read left-to-right across both columns by most ATS parsers, mixing section content into gibberish. Use a single-column layout for ATS-safe output.',
    severity: 'warning',
    fixable: false,
  },
  {
    id: 'fontawesome-ats-risk',
    pattern: /\\usepackage(?:\[[^\]]*\])?\{fontawesome/g,
    message: 'FontAwesome icon characters render as unrecognised symbols in ATS plain-text extraction. Replace icon bullets with standard text or • characters.',
    severity: 'info',
    fixable: false,
  },
  {
    id: 'tabular-layout',
    pattern: /\\begin\{tabular(?:x|\*)?\}/g,
    message: '\\begin{tabular} used for layout can cause content to be mis-ordered or invisible in ATS parsing. Consider using standard LaTeX spacing commands instead.',
    severity: 'info',
    fixable: false,
  },
]

// ─── Cross-line checkers ──────────────────────────────────────────────────────

/**
 * Warn when \input{glyphtounicode} is absent from the preamble.
 * Without it, pdflatex encodes text as glyph IDs instead of Unicode — ATS
 * parsers and copy-paste produce garbled output.
 * Not needed for XeLaTeX/LuaLaTeX (fontspec handles Unicode natively).
 */
function checkGlyphToUnicode(lines: string[]): LintIssue[] {
  // XeLaTeX / LuaLaTeX don't need glyphtounicode — fontspec handles Unicode
  const isXeOrLua = lines.some(
    (l) => !l.trim().startsWith('%') && /\\usepackage(?:\[[^\]]*\])?\{fontspec\}/.test(l)
  )
  if (isXeOrLua) return []

  let docclassLine = -1
  let hasGlyphToUnicode = false

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.trim().startsWith('%')) continue
    if (/\\begin\{document\}/.test(line)) break
    if (/\\documentclass/.test(line) && docclassLine === -1) docclassLine = i
    if (/\\input\{glyphtounicode\}/.test(line)) hasGlyphToUnicode = true
  }

  // Only flag documents that have a \documentclass (i.e. full LaTeX files)
  if (docclassLine < 0 || hasGlyphToUnicode) return []

  return [
    {
      line: docclassLine + 1,
      column: 1,
      endColumn: lines[docclassLine].length + 1,
      severity: 'warning',
      ruleId: 'missing-glyphtounicode',
      message:
        'Missing \\input{glyphtounicode} — pdflatex encodes text as glyph IDs instead of Unicode, causing ATS parsers and copy-paste to produce garbled output. Add \\input{glyphtounicode} and \\pdfgentounicode=1 to your preamble.',
      fixable: true,
      // Append the two lines directly after \documentclass
      fix: (lineContent) =>
        `${lineContent}\n\\input{glyphtounicode}\n\\pdfgentounicode=1`,
    },
  ]
}

/** hyperref should be loaded last (after geometry, color, etc.) */
function checkHyperrefOrder(lines: string[]): LintIssue[] {
  let hyperrefLine = -1
  let lastPackageLine = -1

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.trim().startsWith('%')) continue
    // Stop scanning at \begin{document}
    if (/\\begin\{document\}/.test(line)) break

    if (/\\usepackage(?:\[[^\]]*\])?\{hyperref\}/.test(line)) {
      hyperrefLine = i
    }
    if (/\\usepackage/.test(line)) {
      lastPackageLine = i
    }
  }

  if (hyperrefLine < 0 || hyperrefLine === lastPackageLine) return []

  return [
    {
      line: hyperrefLine + 1,
      column: 1,
      endColumn: lines[hyperrefLine].length + 1,
      severity: 'warning',
      ruleId: 'hyperref-order',
      message:
        'hyperref should be loaded as the last package in the preamble',
      fixable: false,
    },
  ]
}

/** \section / \subsection not followed by \label within 3 lines.
 *  Includes the section line itself (for same-line labels) and strips
 *  inline comments before checking so `% \label{...}` doesn't suppress. */
function checkMissingLabels(lines: string[]): LintIssue[] {
  const issues: LintIssue[] = []
  const sectionRe = /\\(section|subsection|subsubsection)\*?\{[^}]+\}/
  const stripComment = (l: string) => l.replace(/(?<!\\)%.*$/, '')

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    if (line.trim().startsWith('%')) continue
    if (!sectionRe.test(line)) continue

    // Search window: current line + next 3 lines, all with inline comments stripped
    const window = [line, ...lines.slice(i + 1, i + 4)]
      .map(stripComment)
      .join('\n')

    if (!/\\label\{/.test(window)) {
      const match = sectionRe.exec(line)!
      issues.push({
        line: i + 1,
        column: match.index + 1,
        endColumn: match.index + match[0].length + 1,
        severity: 'info',
        ruleId: 'missing-label',
        message: `\\${match[1]} without a \\label — add \\label{sec:name} for cross-references`,
        fixable: false,
      })
    }
  }

  return issues
}

// ─── Main lintLatex function ──────────────────────────────────────────────────

export function lintLatex(content: string): LintIssue[] {
  const lines = content.split('\n')
  const issues: LintIssue[] = []

  // Per-line rules
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]
    // Skip pure comment lines
    if (line.trim().startsWith('%')) continue

    // Strip inline comment portion for matching (keep original for column math)
    const uncommented = line.replace(/(?<!\\)%.*$/, '')

    for (const rule of PER_LINE_RULES) {
      // Reset lastIndex since patterns use /g flag
      rule.pattern.lastIndex = 0

      let match: RegExpExecArray | null
      while ((match = rule.pattern.exec(uncommented)) !== null) {
        issues.push({
          line: i + 1,
          column: match.index + 1,
          endColumn: match.index + match[0].length + 1,
          severity: rule.severity,
          ruleId: rule.id,
          message: rule.message,
          fixable: rule.fixable,
          fix: rule.fix,
        })
      }
    }
  }

  // Cross-line rules
  issues.push(...checkGlyphToUnicode(lines))
  issues.push(...checkHyperrefOrder(lines))
  issues.push(...checkMissingLabels(lines))

  // Sort by line then column
  issues.sort((a, b) => a.line - b.line || a.column - b.column)

  return issues
}

// ─── autoFixAll ───────────────────────────────────────────────────────────────

/** Apply all fixable per-line rules to every line. Returns the fixed content.
 *  Inline comments (% ...) are split off before fixing so fix functions never
 *  accidentally rewrite comment text. */
export function autoFixAll(content: string): string {
  const lines = content.split('\n')

  const fixed = lines.map((line) => {
    // Skip pure comment lines entirely
    if (line.trim().startsWith('%')) return line

    // Split at the first unescaped % to isolate comment
    const commentIdx = line.search(/(?<!\\)%/)
    const codePart = commentIdx >= 0 ? line.slice(0, commentIdx) : line
    const commentPart = commentIdx >= 0 ? line.slice(commentIdx) : ''

    let result = codePart
    for (const rule of PER_LINE_RULES) {
      if (rule.fixable && rule.fix) {
        result = rule.fix(result)
      }
    }
    return result + commentPart
  })

  // Cross-line fix: insert \input{glyphtounicode} after \documentclass if missing
  return _insertGlyphToUnicode(fixed.join('\n'))
}

/**
 * Insert `\input{glyphtounicode}` + `\pdfgentounicode=1` on the line
 * immediately after `\documentclass` if they are absent.
 * No-ops for XeLaTeX/LuaLaTeX documents (fontspec present).
 */
function _insertGlyphToUnicode(content: string): string {
  const lines = content.split('\n')
  // Skip if already present or XeLaTeX/LuaLaTeX
  if (
    lines.some((l) => /\\input\{glyphtounicode\}/.test(l)) ||
    lines.some((l) => !l.trim().startsWith('%') && /\\usepackage(?:\[[^\]]*\])?\{fontspec\}/.test(l))
  ) {
    return content
  }
  const idx = lines.findIndex(
    (l) => !l.trim().startsWith('%') && /\\documentclass/.test(l)
  )
  if (idx < 0) return content
  lines.splice(idx + 1, 0, '\\input{glyphtounicode}', '\\pdfgentounicode=1')
  return lines.join('\n')
}
