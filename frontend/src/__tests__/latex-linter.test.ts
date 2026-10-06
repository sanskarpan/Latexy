import { describe, test, expect } from 'vitest'
import { lintLatex, autoFixAll } from '../lib/latex-linter'

// ─── lintLatex ────────────────────────────────────────────────────────────────

describe('lintLatex', () => {
  test('returns empty array for clean LaTeX', () => {
    const clean = [
      '\\documentclass{article}',
      '\\input{glyphtounicode}',
      '\\pdfgentounicode=1',
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

  test('no false positive for package names containing hyperref as substring', () => {
    // e.g. a hypothetical \usepackage{nohyperref} should NOT trigger
    const content = [
      '\\documentclass{article}',
      '\\usepackage{nohyperref}',
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

// ─── ATS pre-flight rules ─────────────────────────────────────────────────────

describe('lintLatex — missing-glyphtounicode', () => {
  const withDocclass = (body = '') =>
    `\\documentclass{article}\n\\begin{document}\n${body}\n\\end{document}`

  test('flags missing \\input{glyphtounicode} in a pdflatex document', () => {
    const issues = lintLatex(withDocclass())
    expect(issues.some((i) => i.ruleId === 'missing-glyphtounicode')).toBe(true)
  })

  test('no issue when \\input{glyphtounicode} is present', () => {
    const content = `\\documentclass{article}\n\\input{glyphtounicode}\n\\pdfgentounicode=1\n\\begin{document}\n\\end{document}`
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-glyphtounicode')).toBe(false)
  })

  test('no issue for XeLaTeX documents (fontspec present)', () => {
    const content = `\\documentclass{article}\n\\usepackage{fontspec}\n\\begin{document}\n\\end{document}`
    expect(lintLatex(content).some((i) => i.ruleId === 'missing-glyphtounicode')).toBe(false)
  })

  test('no issue for snippet without \\documentclass', () => {
    const issues = lintLatex('Some {\\bf bold} text')
    expect(issues.some((i) => i.ruleId === 'missing-glyphtounicode')).toBe(false)
  })

  test('issue is marked fixable', () => {
    const issues = lintLatex(withDocclass())
    const issue = issues.find((i) => i.ruleId === 'missing-glyphtounicode')
    expect(issue?.fixable).toBe(true)
  })

  test('fix inserts \\input{glyphtounicode} after \\documentclass line', () => {
    const issues = lintLatex(withDocclass())
    const issue = issues.find((i) => i.ruleId === 'missing-glyphtounicode')!
    const fixed = issue.fix!('\\documentclass{article}')
    expect(fixed).toContain('\\input{glyphtounicode}')
    expect(fixed).toContain('\\pdfgentounicode=1')
    expect(fixed.startsWith('\\documentclass{article}')).toBe(true)
  })

  test('points to the \\documentclass line', () => {
    const content = `\\documentclass{article}\n\\begin{document}\n\\end{document}`
    const issue = lintLatex(content).find((i) => i.ruleId === 'missing-glyphtounicode')
    expect(issue?.line).toBe(1)
  })
})

describe('lintLatex — multicol-ats-risk', () => {
  test('flags \\usepackage{multicol}', () => {
    expect(lintLatex('\\usepackage{multicol}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(true)
  })

  test('flags \\usepackage{multicols}', () => {
    expect(lintLatex('\\usepackage{multicols}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(true)
  })

  test('flags \\begin{multicols}', () => {
    expect(lintLatex('\\begin{multicols}{2}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(true)
  })

  test('flags \\begin{multicols*}', () => {
    expect(lintLatex('\\begin{multicols*}{2}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(true)
  })

  test('no issue for single-column document', () => {
    expect(lintLatex('\\usepackage{geometry}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(false)
  })

  test('not flagged when in comment', () => {
    expect(lintLatex('% \\usepackage{multicol}').some((i) => i.ruleId === 'multicol-ats-risk')).toBe(false)
  })
})

describe('lintLatex — fontawesome-ats-risk', () => {
  test('flags \\usepackage{fontawesome}', () => {
    expect(lintLatex('\\usepackage{fontawesome}').some((i) => i.ruleId === 'fontawesome-ats-risk')).toBe(true)
  })

  test('flags \\usepackage{fontawesome5}', () => {
    expect(lintLatex('\\usepackage{fontawesome5}').some((i) => i.ruleId === 'fontawesome-ats-risk')).toBe(true)
  })

  test('flags \\usepackage[fixed]{fontawesome5}', () => {
    expect(lintLatex('\\usepackage[fixed]{fontawesome5}').some((i) => i.ruleId === 'fontawesome-ats-risk')).toBe(true)
  })

  test('no issue without fontawesome', () => {
    expect(lintLatex('\\usepackage{geometry}').some((i) => i.ruleId === 'fontawesome-ats-risk')).toBe(false)
  })
})

describe('lintLatex — tabular-layout', () => {
  test('flags \\begin{tabular}', () => {
    expect(lintLatex('\\begin{tabular}{lr}').some((i) => i.ruleId === 'tabular-layout')).toBe(true)
  })

  test('flags \\begin{tabularx}', () => {
    expect(lintLatex('\\begin{tabularx}{\\textwidth}{lX}').some((i) => i.ruleId === 'tabular-layout')).toBe(true)
  })

  test('flags \\begin{tabular*}', () => {
    expect(lintLatex('\\begin{tabular*}{\\textwidth}{lr}').some((i) => i.ruleId === 'tabular-layout')).toBe(true)
  })

  test('no issue without tabular', () => {
    expect(lintLatex('\\begin{itemize}').some((i) => i.ruleId === 'tabular-layout')).toBe(false)
  })
})

// ─── autoFixAll — glyphtounicode ──────────────────────────────────────────────

describe('autoFixAll — glyphtounicode insertion', () => {
  test('inserts \\input{glyphtounicode} after \\documentclass when missing', () => {
    const input = '\\documentclass{article}\n\\begin{document}\n\\end{document}'
    const result = autoFixAll(input)
    const lines = result.split('\n')
    expect(lines[0]).toBe('\\documentclass{article}')
    expect(lines[1]).toBe('\\input{glyphtounicode}')
    expect(lines[2]).toBe('\\pdfgentounicode=1')
  })

  test('does not insert if already present', () => {
    const input = '\\documentclass{article}\n\\input{glyphtounicode}\n\\pdfgentounicode=1\n\\begin{document}\n\\end{document}'
    const result = autoFixAll(input)
    const occurrences = result.split('\\input{glyphtounicode}').length - 1
    expect(occurrences).toBe(1)
  })

  test('does not insert for XeLaTeX documents', () => {
    const input = '\\documentclass{article}\n\\usepackage{fontspec}\n\\begin{document}\n\\end{document}'
    const result = autoFixAll(input)
    expect(result).not.toContain('\\input{glyphtounicode}')
  })

  test('is idempotent', () => {
    const input = '\\documentclass{article}\n\\begin{document}\n\\end{document}'
    expect(autoFixAll(autoFixAll(input))).toBe(autoFixAll(input))
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

// ─── duplicate-label ────────────────────────────────────────────────────────

describe('lintLatex — duplicate-label', () => {
  test('flags the second literal label definition with precise location', () => {
    const content = '\\section{Intro}\\label{sec:intro}\ntext\n  \\label { sec:intro }'
    const issue = lintLatex(content).find((i) => i.ruleId === 'duplicate-label')
    expect(issue).toMatchObject({
      line: 3,
      column: 3,
      endColumn: 23,
      severity: 'warning',
      fixable: false,
    })
    expect(issue?.message).toContain('Duplicate \\label{sec:intro} definition')
  })

  test('does not flag repeated references or commented labels', () => {
    const content = [
      '\\label{sec:intro}',
      '\\ref{sec:intro} and \\pageref{sec:intro}',
      '% \\label{sec:intro}',
      'text % \\label{sec:intro}',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'duplicate-label')).toBe(false)
  })

  test('does not treat a TeX line-break followed by text as a label command', () => {
    const content = ['\\label{sec:intro}', '\\\\label{sec:intro}'].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'duplicate-label')).toBe(false)
  })

  test('ignores labels inside literal environments and inline verbatim text', () => {
    const content = [
      '\\label{sec:intro}',
      '\\begin{verbatim}',
      '\\label{sec:intro}',
      '\\end{verbatim}',
      '\\begin{minted}{latex}',
      '\\label{sec:intro}',
      '\\end{minted}',
      '\\verb|\\label{sec:intro}|',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'duplicate-label')).toBe(false)
  })

  test('ignores labels in inline listings and non-executing control-sequence text', () => {
    const content = [
      '\\label{sec:intro}',
      '\\lstinline[language=tex]|\\label{sec:intro}|',
      '\\mintinline[bgcolor=gray]{tex}|\\label{sec:intro}|',
      '\\string\\label{sec:intro}',
      '\\meaning\\label',
      '\\show\\label',
      '\\detokenize{\\label{sec:intro}}',
    ].join('\n')
    expect(lintLatex(content).some((i) => i.ruleId === 'duplicate-label')).toBe(false)
  })

  test('respects escaped-percent parity while scanning comments', () => {
    const content = [
      '\\label{sec:intro}',
      '\\% \\label{sec:intro}', // escaped percent: the label is active
      '\\\\% \\label{sec:intro}', // even slash run: percent starts a comment
    ].join('\n')
    const issues = lintLatex(content).filter((i) => i.ruleId === 'duplicate-label')
    expect(issues).toHaveLength(1)
    expect(issues[0]).toMatchObject({ line: 2, column: 4 })
  })

  test('requires a real command boundary and stays responsive on long slash runs', () => {
    const content = [
      '\\label{sec:intro}',
      '\\labelled{sec:intro}',
      `${'\\'.repeat(2)}label{sec:intro}`,
      `${'\\'.repeat(3)}label{sec:intro}`,
      '\\\\'.repeat(50_000),
    ].join('\n')
    const issues = lintLatex(content).filter((i) => i.ruleId === 'duplicate-label')
    expect(issues).toHaveLength(1)
    expect(issues[0].line).toBe(4)
  })

  test('rejects control characters in keys and bounds reported diagnostics', () => {
    const controlCharacter = [
      '\\label{sec:intro}',
      `\\label{sec:intro${String.fromCharCode(7)}}`,
    ].join('\n')
    expect(lintLatex(controlCharacter).some((i) => i.ruleId === 'duplicate-label')).toBe(false)

    const repeated = Array.from({ length: 10_050 }, () => '\\label{same}').join('\n')
    expect(lintLatex(repeated).filter((i) => i.ruleId === 'duplicate-label')).toHaveLength(10_000)
  })

  test('reports every repeated definition without regex backtracking risk', () => {
    const content = Array.from({ length: 3 }, () => '\\label{same}').join('\n')
    const issues = lintLatex(content).filter((i) => i.ruleId === 'duplicate-label')
    expect(issues).toHaveLength(2)
    expect(issues.map((issue) => issue.line)).toEqual([2, 3])
  })
})
