import { describe, test, expect } from 'vitest'
import { lintLatex, autoFixAll } from '../lib/latex-linter'

// ─── lintLatex ────────────────────────────────────────────────────────────────

describe('lintLatex', () => {
  test('returns empty array for clean LaTeX', () => {
    const clean = [
      '\\documentclass{article}',
      '\\usepackage{amsmath}',
      '\\begin{document}',
      'Hello \\textbf{world}.',
      '\\end{document}',
    ].join('\n')
    expect(lintLatex(clean)).toEqual([])
  })

  test('detects deprecated \\bf', () => {
    const issues = lintLatex('Some {\\bf bold} text')
    expect(issues.some((i) => i.ruleId === 'deprecated-bf')).toBe(true)
  })

  test('detects deprecated \\it', () => {
    const issues = lintLatex('Some {\\it italic} text')
    expect(issues.some((i) => i.ruleId === 'deprecated-it')).toBe(true)
  })

  test('detects straight double quotes', () => {
    const issues = lintLatex('He said "hello".')
    expect(issues.some((i) => i.ruleId === 'wrong-quotes')).toBe(true)
  })

  test('does not flag LaTeX curly quotes', () => {
    const issues = lintLatex("He said ``hello''.")
    expect(issues.some((i) => i.ruleId === 'wrong-quotes')).toBe(false)
  })

  test('detects redundant space after e.g.', () => {
    const issues = lintLatex('For example e.g. some text')
    expect(issues.some((i) => i.ruleId === 'redundant-space')).toBe(true)
  })

  test('detects redundant space after i.e.', () => {
    const issues = lintLatex('That is i.e. the answer')
    expect(issues.some((i) => i.ruleId === 'redundant-space')).toBe(true)
  })

  test('ignores \\bf on a comment-only line', () => {
    const issues = lintLatex('% \\bf is deprecated')
    expect(issues.some((i) => i.ruleId === 'deprecated-bf')).toBe(false)
  })

  test('ignores \\it in inline comment portion', () => {
    const issues = lintLatex('Some text % \\it italic comment')
    expect(issues.some((i) => i.ruleId === 'deprecated-it')).toBe(false)
  })

  test('issue has correct 1-based line number', () => {
    const content = 'line one\nSome {\\bf bold}\nline three'
    const issues = lintLatex(content)
    const issue = issues.find((i) => i.ruleId === 'deprecated-bf')
    expect(issue?.line).toBe(2)
  })

  test('issue column points to the match start', () => {
    const line = 'Some {\\bf bold}'
    const issues = lintLatex(line)
    const issue = issues.find((i) => i.ruleId === 'deprecated-bf')
    // \bf starts at index 6 (0-based) → column 7 (1-based)
    expect(issue?.column).toBe(7)
  })

  test('detects double-dollar display math', () => {
    const issues = lintLatex('$$E = mc^2$$')
    expect(issues.some((i) => i.ruleId === 'double-dollar')).toBe(true)
  })

  test('does not flag \\[ display math', () => {
    const issues = lintLatex('\\[ E = mc^2 \\]')
    expect(issues.some((i) => i.ruleId === 'double-dollar')).toBe(false)
  })
})

// ─── hyperref-order ───────────────────────────────────────────────────────────

describe('lintLatex — hyperref-order', () => {
  test('no issue when hyperref is last package', () => {
    const content = [
      '\\documentclass{article}',
      '\\usepackage{geometry}',
      '\\usepackage{hyperref}',
      '\\begin{document}',
      '\\end{document}',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'hyperref-order')).toBe(false)
  })

  test('flags hyperref when loaded before other packages', () => {
    const content = [
      '\\documentclass{article}',
      '\\usepackage{hyperref}',
      '\\usepackage{geometry}',
      '\\begin{document}',
      '\\end{document}',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'hyperref-order')).toBe(true)
  })

  test('no issue when hyperref is not present', () => {
    const content = [
      '\\documentclass{article}',
      '\\usepackage{geometry}',
      '\\begin{document}',
      '\\end{document}',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'hyperref-order')).toBe(false)
  })
})

// ─── missing-label ────────────────────────────────────────────────────────────

describe('lintLatex — missing-label', () => {
  test('flags \\section without \\label', () => {
    const content = '\\section{Introduction}\nSome text here.\nMore text.'
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-label')).toBe(true)
  })

  test('no issue when \\label follows \\section within 3 lines', () => {
    const content = '\\section{Introduction}\n\\label{sec:intro}\nSome text.'
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-label')).toBe(false)
  })

  test('flags \\subsection without \\label', () => {
    const content = '\\subsection{Methods}\nSome text here.\nMore text.'
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-label')).toBe(true)
  })
})

// ─── autoFixAll ───────────────────────────────────────────────────────────────

describe('autoFixAll', () => {
  test('replaces straight quotes with curly quotes', () => {
    const fixed = autoFixAll('He said "hello".')
    expect(fixed).toBe("He said ``hello''.")
  })

  test('replaces \\bf with \\textbf in braced form', () => {
    const fixed = autoFixAll('{\\bf bold text}')
    expect(fixed).toContain('\\textbf')
  })

  test('replaces \\it with \\textit in braced form', () => {
    const fixed = autoFixAll('{\\it italic text}')
    expect(fixed).toContain('\\textit')
  })

  test('fixes e.g. spacing', () => {
    const fixed = autoFixAll('e.g. some text')
    expect(fixed).toContain('e.g.\\ ')
    expect(fixed).not.toMatch(/e\.g\. /)
  })

  test('leaves comment lines unchanged', () => {
    const line = '% \\bf deprecated'
    expect(autoFixAll(line)).toBe(line)
  })

  test('is idempotent — applying twice gives same result', () => {
    const content = '"quoted" and {\\bf text}'
    expect(autoFixAll(autoFixAll(content))).toBe(autoFixAll(content))
  })

  test('does not change clean LaTeX', () => {
    const clean = '\\textbf{bold} and \\textit{italic}'
    expect(autoFixAll(clean)).toBe(clean)
  })

  // ── Fix 2: autoFixAll preserves inline comments ──────────────────── //

  test('does not rewrite text inside an inline comment', () => {
    const line = 'Some code % use "quotes" and {\\bf old} here'
    const result = autoFixAll(line)
    // Code part is unchanged (no violations in code)
    // Comment part must be untouched
    expect(result).toContain('% use "quotes" and {\\bf old} here')
  })

  test('fixes code part but leaves comment part unchanged', () => {
    const line = '"hello" world % keep "this" as-is'
    const result = autoFixAll(line)
    // Code part: "hello" → ``hello''
    expect(result.startsWith("``hello''")).toBe(true)
    // Comment part: preserved exactly
    expect(result).toContain('% keep "this" as-is')
  })

  // ── Fix 4: deprecated-bf/it produce valid LaTeX ───────────────────── //

  test('\\bf word → \\textbf{word} (bare word wrapped in braces)', () => {
    const fixed = autoFixAll('\\bf bold')
    expect(fixed).toBe('\\textbf{bold}')
  })

  test('\\it word → \\textit{word} (bare word wrapped in braces)', () => {
    const fixed = autoFixAll('\\it italic')
    expect(fixed).toBe('\\textit{italic}')
  })

  test('\\bf{text} → \\textbf{text} (braced form unchanged)', () => {
    const fixed = autoFixAll('\\bf{text}')
    expect(fixed).toBe('\\textbf{text}')
  })

  test('{\\bf text} → \\textbf{text} (declaration group form)', () => {
    const fixed = autoFixAll('{\\bf bold text}')
    expect(fixed).toBe('\\textbf{bold text}')
  })
})

// ─── Fix 3: checkMissingLabels edge cases ─────────────────────────────────────

describe('lintLatex — missing-label edge cases', () => {
  test('no issue when \\label is on the same line as \\section', () => {
    const issues = lintLatex('\\section{Intro}\\label{sec:intro}')
    expect(issues.some((i) => i.ruleId === 'missing-label')).toBe(false)
  })

  test('issues when \\label is commented out (% \\label{...})', () => {
    const content = '\\section{Methods}\n% \\label{sec:methods}\nSome text.'
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-label')).toBe(true)
  })

  test('no issue when real \\label follows within 3 lines', () => {
    const content = '\\section{Results}\n\n\\label{sec:results}\nSome text.'
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-label')).toBe(false)
  })
})
