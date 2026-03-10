'use client'

import { useEffect, useImperativeHandle, useRef, forwardRef } from 'react'

let _latexLanguageRegistered = false
import Editor, { type OnMount } from '@monaco-editor/react'
import type { LogLine } from '@/hooks/useJobStream'
import { BLANK_RESUME_TEMPLATE } from '@/lib/latex-templates'

export interface LaTeXEditorRef {
  setValue: (value: string) => void
  getValue: () => string
  highlightLine: (line: number) => void
}

interface LaTeXEditorProps {
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
  logLines?: LogLine[]
  onSave?: () => void
  onCompile?: () => void
  onCursorChange?: (line: number) => void
  /** When set, scrolls editor to this line (from PDF SyncTeX click) */
  syncLine?: number | null
}

// ── LaTeX command corpus ───────────────────────────────────────────────────

const STRUCTURE_CMDS = [
  'part', 'chapter', 'section', 'subsection', 'subsubsection',
  'paragraph', 'subparagraph',
  'part*', 'chapter*', 'section*', 'subsection*', 'subsubsection*',
]
const DOC_CMDS = [
  'documentclass', 'usepackage', 'begin', 'end', 'item',
  'label', 'ref', 'eqref', 'pageref', 'cite', 'citep', 'citet',
  'bibitem', 'bibliography', 'bibliographystyle',
  'maketitle', 'title', 'author', 'date', 'today',
  'newcommand', 'renewcommand', 'providecommand',
  'newenvironment', 'renewenvironment',
  'newtheorem', 'setlength', 'setcounter',
  'tableofcontents', 'listoffigures', 'listoftables',
  'appendix', 'frontmatter', 'mainmatter', 'backmatter',
]
const FONT_CMDS = [
  'textbf', 'textit', 'texttt', 'emph', 'textsc', 'textrm', 'textsf',
  'textup', 'textmd', 'textsl', 'textbfit', 'underline', 'uline',
  'small', 'large', 'Large', 'LARGE', 'huge', 'Huge', 'normalsize',
  'footnotesize', 'scriptsize', 'tiny',
]
const LAYOUT_CMDS = [
  'includegraphics', 'caption', 'label', 'ref', 'footnote',
  'hline', 'cline', 'multicolumn', 'multirow',
  'vspace', 'hspace', 'vfill', 'hfill',
  'newpage', 'clearpage', 'pagebreak',
  'noindent', 'indent', 'par',
  'smallskip', 'medskip', 'bigskip',
  'centering', 'raggedright', 'raggedleft', 'linebreak',
  'textwidth', 'linewidth', 'columnwidth', 'paperwidth', 'paperheight',
  'arraystretch',
]
const MATH_CMDS = [
  'frac', 'dfrac', 'tfrac', 'sqrt', 'sum', 'int', 'prod', 'lim', 'infty',
  'left', 'right', 'big', 'Big', 'bigg', 'Bigg',
  'alpha', 'beta', 'gamma', 'delta', 'epsilon', 'zeta', 'eta', 'theta',
  'iota', 'kappa', 'lambda', 'mu', 'nu', 'xi', 'pi', 'rho', 'sigma',
  'tau', 'upsilon', 'phi', 'chi', 'psi', 'omega',
  'Gamma', 'Delta', 'Theta', 'Lambda', 'Xi', 'Pi', 'Sigma', 'Upsilon',
  'Phi', 'Psi', 'Omega',
  'partial', 'nabla', 'forall', 'exists', 'in', 'notin', 'subset',
  'supset', 'cup', 'cap', 'pm', 'mp', 'times', 'div', 'cdot', 'cdots',
  'ldots', 'vdots', 'ddots', 'leq', 'geq', 'neq', 'approx', 'equiv',
  'to', 'rightarrow', 'leftarrow', 'Rightarrow', 'Leftarrow',
  'Leftrightarrow', 'leftrightarrow', 'mapsto',
  'mathrm', 'mathbf', 'mathit', 'mathsf', 'mathtt', 'mathcal', 'mathbb',
  'mathfrak', 'boldsymbol', 'vec', 'hat', 'bar', 'tilde', 'dot', 'ddot',
  'overline', 'underline', 'overbrace', 'underbrace',
  'begin', 'end', 'text', 'mbox',
]
const ENVIRONMENTS = [
  'document', 'abstract', 'figure', 'figure*', 'table', 'table*',
  'tabular', 'tabular*', 'tabularx', 'array', 'longtable',
  'equation', 'equation*', 'align', 'align*', 'gather', 'gather*',
  'multline', 'multline*', 'split', 'cases', 'matrix', 'pmatrix',
  'bmatrix', 'vmatrix', 'Bmatrix', 'Vmatrix',
  'itemize', 'enumerate', 'description', 'list',
  'verbatim', 'verbatim*', 'lstlisting',
  'center', 'flushleft', 'flushright', 'quote', 'quotation', 'verse',
  'minipage', 'framed', 'boxedminipage',
  'thebibliography', 'filecontents',
  'tikzpicture', 'scope', 'pgfpicture',
  'theorem', 'lemma', 'proof', 'definition', 'example', 'remark',
  'corollary', 'proposition',
]

// ── Log parser → Monaco markers ───────────────────────────────────────────

interface LogError {
  line: number
  message: string
  severity: 'error' | 'warning'
}

function parseLogErrors(logLines: LogLine[]): LogError[] {
  const errors: LogError[] = []
  let pending: string | null = null

  for (const entry of logLines) {
    const text = entry.line

    // Hard error
    if (text.startsWith('! ')) {
      pending = text.slice(2).trim()
      continue
    }

    // Line reference for the pending hard error
    if (pending !== null) {
      const lineMatch = text.match(/^l\.(\d+)/)
      if (lineMatch) {
        errors.push({ line: parseInt(lineMatch[1], 10), message: pending, severity: 'error' })
        pending = null
        continue
      }
      // If we see a blank line, abandon the pending error (no line found)
      if (!text.trim()) pending = null
    }

    // LaTeX/Package warning with "line N"
    const warnLineMatch = text.match(/(?:LaTeX|Package\s+\S+)\s+Warning.*?line\s+(\d+)/i)
    if (warnLineMatch) {
      errors.push({ line: parseInt(warnLineMatch[1], 10), message: text.trim(), severity: 'warning' })
      continue
    }

    // Overfull/Underfull hbox "at lines N--M"
    const hboxMatch = text.match(/(?:Overfull|Underfull)\s+\\hbox.*?at lines\s+(\d+)/i)
    if (hboxMatch) {
      errors.push({ line: parseInt(hboxMatch[1], 10), message: text.trim(), severity: 'warning' })
      continue
    }
  }

  return errors
}

// ── Component ─────────────────────────────────────────────────────────────

const LaTeXEditor = forwardRef<LaTeXEditorRef, LaTeXEditorProps>(
  function LaTeXEditor(
    { value, onChange, readOnly = false, logLines = [], onSave, onCompile, onCursorChange, syncLine },
    ref
  ) {
    const editorRef = useRef<any>(null)
    const monacoRef = useRef<any>(null)
    const disposablesRef = useRef<any[]>([])

    useImperativeHandle(ref, () => ({
      setValue(content: string) {
        const model = editorRef.current?.getModel()
        if (!model) return
        model.setValue(content)
        editorRef.current?.revealLine(model.getLineCount())
      },
      getValue() {
        return editorRef.current?.getValue() ?? ''
      },
      highlightLine(line: number) {
        if (!editorRef.current) return
        editorRef.current.revealLineInCenter(line)
        editorRef.current.setPosition({ lineNumber: line, column: 1 })
        editorRef.current.focus()
      },
    }))

    // Apply log markers whenever logLines change
    useEffect(() => {
      const monaco = monacoRef.current
      const editor = editorRef.current
      if (!monaco || !editor) return

      const model = editor.getModel()
      if (!model) return

      if (!logLines.length) {
        monaco.editor.setModelMarkers(model, 'latex-log', [])
        return
      }

      const errors = parseLogErrors(logLines)
      const markers = errors.map((err) => {
        const lineNum = Math.min(err.line, model.getLineCount())
        const lineContent = model.getLineContent(lineNum)
        return {
          severity:
            err.severity === 'error'
              ? monaco.MarkerSeverity.Error
              : monaco.MarkerSeverity.Warning,
          message: err.message,
          startLineNumber: lineNum,
          startColumn: 1,
          endLineNumber: lineNum,
          endColumn: lineContent.length + 1,
        }
      })

      monaco.editor.setModelMarkers(model, 'latex-log', markers)
    }, [logLines])

    // Sync editor position from PDF click
    useEffect(() => {
      if (!syncLine || !editorRef.current) return
      editorRef.current.revealLineInCenter(syncLine)
      editorRef.current.setPosition({ lineNumber: syncLine, column: 1 })

      // Flash highlight decoration
      const monaco = monacoRef.current
      if (!monaco) return
      const decs = editorRef.current.deltaDecorations(
        [],
        [{
          range: new monaco.Range(syncLine, 1, syncLine, 1),
          options: {
            isWholeLine: true,
            className: 'synctex-highlight',
            overviewRuler: {
              color: '#f59e0b',
              position: monaco.editor.OverviewRulerLane.Full,
            },
          },
        }]
      )
      // Remove highlight after 2s
      setTimeout(() => {
        editorRef.current?.deltaDecorations(decs, [])
      }, 2000)
    }, [syncLine])

    // Cleanup on unmount
    useEffect(() => {
      return () => {
        for (const d of disposablesRef.current) d?.dispose?.()
        disposablesRef.current = []
      }
    }, [])

    const handleEditorDidMount: OnMount = (editor, monaco) => {
      editorRef.current = editor
      monacoRef.current = monaco

      // ── Language registration ──────────────────────────────────────
      if (!_latexLanguageRegistered) {
        monaco.languages.register({ id: 'latex' })

      // ── Monarch tokenizer ──────────────────────────────────────────
      monaco.languages.setMonarchTokensProvider('latex', {
        structure: STRUCTURE_CMDS,
        docCmds: DOC_CMDS,
        fontCmds: FONT_CMDS,
        mathCmds: MATH_CMDS,

        tokenizer: {
          root: [
            // Display math: $$ ... $$
            [/\$\$/, { token: 'math.delim', next: '@displaymath' }],
            // Inline math: $ ... $
            [/\$/, { token: 'math.delim', next: '@inlinemath' }],
            // Comments
            [/%.*$/, 'comment'],
            // Commands
            [/\\[a-zA-Z@*]+/, {
              cases: {
                '@structure': 'keyword.structure',
                '@docCmds': 'keyword.doc',
                '@fontCmds': 'keyword.font',
                '@mathCmds': 'keyword.math',
                '@default': 'keyword',
              },
            }],
            // Special escaped chars
            [/\\[^a-zA-Z@]/, 'keyword.special'],
            // Curly braces
            [/[{}]/, 'delimiter.bracket'],
            // Square brackets
            [/[\[\]]/, 'delimiter.square'],
            // Numbers
            [/\d+(\.\d+)?/, 'number'],
          ],
          inlinemath: [
            [/\$/, { token: 'math.delim', next: '@pop' }],
            [/[^$\\{}\[\]]+/, 'math.content'],
            [/\\[a-zA-Z@*]+/, 'math.command'],
            [/[{}]/, 'math.bracket'],
          ],
          displaymath: [
            [/\$\$/, { token: 'math.delim', next: '@pop' }],
            [/[^$\\{}\[\]]+/, 'math.content'],
            [/\\[a-zA-Z@*]+/, 'math.command'],
            [/[{}]/, 'math.bracket'],
          ],
        },
      })

      // ── Theme ──────────────────────────────────────────────────────
      monaco.editor.defineTheme('latexy-dark', {
        base: 'vs-dark',
        inherit: true,
        rules: [
          { token: 'comment',         foreground: '6b7280', fontStyle: 'italic' },
          { token: 'keyword.structure', foreground: 'fb923c', fontStyle: 'bold' }, // orange - sections
          { token: 'keyword.doc',     foreground: '818cf8' },                       // indigo - doc cmds
          { token: 'keyword.font',    foreground: '67e8f9' },                       // cyan - font cmds
          { token: 'keyword.math',    foreground: 'f472b6' },                       // pink - math cmds
          { token: 'keyword.special', foreground: 'fbbf24' },                       // amber
          { token: 'keyword',         foreground: 'fcd34d' },                       // yellow - generic
          { token: 'math.delim',      foreground: 'ec4899', fontStyle: 'bold' },   // hot pink
          { token: 'math.content',    foreground: 'f9a8d4' },                       // light pink
          { token: 'math.command',    foreground: 'f472b6' },
          { token: 'math.bracket',    foreground: 'a78bfa' },
          { token: 'delimiter.bracket', foreground: 'a78bfa' },                    // purple
          { token: 'delimiter.square',  foreground: 'c4b5fd' },
          { token: 'number',          foreground: '86efac' },                       // green
        ],
        colors: {
          'editor.background':            '#0d1117',
          'editor.foreground':            '#e2e8f0',
          'editor.lineHighlightBackground': '#0f1420',
          'editor.selectionBackground':   '#1e3a5f',
          'editor.inactiveSelectionBackground': '#162a44',
          'editorLineNumber.foreground':  '#334155',
          'editorLineNumber.activeForeground': '#64748b',
          'editorCursor.foreground':      '#f59e0b',
          'editorWhitespace.foreground':  '#1e293b',
          'editorIndentGuide.background': '#1e293b',
          'editorIndentGuide.activeBackground': '#334155',
          'editorOverviewRuler.background': '#07090f',
          'scrollbar.shadow':             '#00000000',
          'scrollbarSlider.background':   '#334155aa',
          'scrollbarSlider.hoverBackground': '#475569bb',
          'editorGutter.background':      '#07090f',
        },
      })
      // ── Completion provider ────────────────────────────────────────
      const completionDisposable = monaco.languages.registerCompletionItemProvider('latex', {
        triggerCharacters: ['\\', '{'],
        provideCompletionItems(model: import('monaco-editor').editor.ITextModel, position: import('monaco-editor').Position) {
          const text = model.getValueInRange({
            startLineNumber: position.lineNumber,
            startColumn: 1,
            endLineNumber: position.lineNumber,
            endColumn: position.column,
          })

          const suggestions: any[] = []

          // \command completions
          const cmdMatch = text.match(/\\([a-zA-Z@*]*)$/)
          if (cmdMatch) {
            const partial = cmdMatch[1]
            const range = {
              startLineNumber: position.lineNumber,
              startColumn: position.column - partial.length - 1,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            }
            const allCmds = [...STRUCTURE_CMDS, ...DOC_CMDS, ...FONT_CMDS, ...LAYOUT_CMDS, ...MATH_CMDS]
            for (const cmd of [...new Set(allCmds)]) {
              if (cmd.startsWith(partial)) {
                suggestions.push({
                  label: `\\${cmd}`,
                  kind: monaco.languages.CompletionItemKind.Function,
                  insertText: cmd,
                  range,
                  sortText: STRUCTURE_CMDS.includes(cmd) ? `0${cmd}` : `1${cmd}`,
                })
              }
            }
          }

          // \begin{ environment completions
          const beginMatch = text.match(/\\begin\{([a-zA-Z*]*)$/)
          if (beginMatch) {
            const partial = beginMatch[1]
            const range = {
              startLineNumber: position.lineNumber,
              startColumn: position.column - partial.length,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            }
            for (const env of ENVIRONMENTS) {
              if (env.startsWith(partial)) {
                suggestions.push({
                  label: env,
                  kind: monaco.languages.CompletionItemKind.Module,
                  insertText: `${env}}\n\t$0\n\\end{${env}}`,
                  insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
                  range,
                  detail: 'LaTeX environment',
                  documentation: `\\begin{${env}} ... \\end{${env}}`,
                })
              }
            }
          }

          // \end{ environment completions
          const endMatch = text.match(/\\end\{([a-zA-Z*]*)$/)
          if (endMatch) {
            const partial = endMatch[1]
            const range = {
              startLineNumber: position.lineNumber,
              startColumn: position.column - partial.length,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            }
            for (const env of ENVIRONMENTS) {
              if (env.startsWith(partial)) {
                suggestions.push({
                  label: env,
                  kind: monaco.languages.CompletionItemKind.Module,
                  insertText: env + '}',
                  range,
                })
              }
            }
          }

          // \cite{ — scan document for \bibitem keys
          const citeMatch = text.match(/\\(?:cite[tp]?|nocite)\{([^}]*)$/)
          if (citeMatch) {
            const partial = citeMatch[1]
            const allText = model.getValue()
            const bibRe = /\\bibitem(?:\[[^\]]*\])?\{([^}]+)\}/g
            let m: RegExpExecArray | null
            const seen = new Set<string>()
            while ((m = bibRe.exec(allText)) !== null) {
              if (!seen.has(m[1]) && m[1].startsWith(partial)) {
                seen.add(m[1])
                suggestions.push({
                  label: m[1],
                  kind: monaco.languages.CompletionItemKind.Reference,
                  insertText: m[1],
                  range: {
                    startLineNumber: position.lineNumber,
                    startColumn: position.column - partial.length,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                  },
                  detail: 'Bibliography key',
                })
              }
            }
          }

          // \ref{ / \eqref{ / \pageref{ — scan document for \label keys
          const refMatch = text.match(/\\(?:eq)?(?:ref|pageref)\{([^}]*)$/)
          if (refMatch) {
            const partial = refMatch[1]
            const allText = model.getValue()
            const labelRe = /\\label\{([^}]+)\}/g
            let m: RegExpExecArray | null
            const seen = new Set<string>()
            while ((m = labelRe.exec(allText)) !== null) {
              if (!seen.has(m[1]) && m[1].startsWith(partial)) {
                seen.add(m[1])
                suggestions.push({
                  label: m[1],
                  kind: monaco.languages.CompletionItemKind.Variable,
                  insertText: m[1],
                  range: {
                    startLineNumber: position.lineNumber,
                    startColumn: position.column - partial.length,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                  },
                  detail: 'Label',
                })
              }
            }
          }

          return { suggestions }
        },
      })
      disposablesRef.current.push(completionDisposable)

      // ── Folding range provider ─────────────────────────────────────
      const foldingDisposable = monaco.languages.registerFoldingRangeProvider('latex', {
        provideFoldingRanges(model: import('monaco-editor').editor.ITextModel) {
          const ranges: any[] = []
          const lines = model.getLinesContent()

          // \begin / \end pairs
          const stack: { line: number; env: string }[] = []
          for (let i = 0; i < lines.length; i++) {
            const stripped = lines[i].replace(/(?<!\\)%.*$/, '')
            const beginM = stripped.match(/\\begin\{([^}]+)\}/)
            if (beginM) {
              stack.push({ line: i + 1, env: beginM[1] })
              continue
            }
            const endM = stripped.match(/\\end\{([^}]+)\}/)
            if (endM) {
              for (let j = stack.length - 1; j >= 0; j--) {
                if (stack[j].env === endM[1]) {
                  if (i + 1 > stack[j].line) {
                    ranges.push({
                      start: stack[j].line,
                      end: i + 1,
                      kind: monaco.languages.FoldingRangeKind.Region,
                    })
                  }
                  stack.splice(j, 1)
                  break
                }
              }
            }
          }

          // Section hierarchy
          const sectionCmds = [
            { re: /\\part\*?\s*\{/, level: 0 },
            { re: /\\chapter\*?\s*\{/, level: 1 },
            { re: /\\section\*?\s*\{/, level: 2 },
            { re: /\\subsection\*?\s*\{/, level: 3 },
            { re: /\\subsubsection\*?\s*\{/, level: 4 },
            { re: /\\paragraph\*?\s*\{/, level: 5 },
          ]
          const sections: { line: number; level: number }[] = []
          for (let i = 0; i < lines.length; i++) {
            const stripped = lines[i].replace(/(?<!\\)%.*$/, '')
            for (const { re, level } of sectionCmds) {
              if (re.test(stripped)) {
                sections.push({ line: i + 1, level })
                break
              }
            }
          }
          for (let i = 0; i < sections.length; i++) {
            const cur = sections[i]
            let end = lines.length
            for (let j = i + 1; j < sections.length; j++) {
              if (sections[j].level <= cur.level) {
                end = sections[j].line - 1
                break
              }
            }
            if (end > cur.line) {
              ranges.push({
                start: cur.line,
                end,
                kind: monaco.languages.FoldingRangeKind.Region,
              })
            }
          }

          return ranges
        },
      })
      disposablesRef.current.push(foldingDisposable)

      // ── Hover provider (show command description) ──────────────────
      const hoverDisposable = monaco.languages.registerHoverProvider('latex', {
        provideHover(model: import('monaco-editor').editor.ITextModel, position: import('monaco-editor').Position) {
          const word = model.getWordAtPosition(position)
          if (!word) return null

          // Check if we're hovering over a LaTeX command (preceded by \)
          const lineText = model.getLineContent(position.lineNumber)
          const charBefore = lineText[word.startColumn - 2]
          if (charBefore !== '\\') return null

          const cmd = word.word
          const descriptions: Record<string, string> = {
            section: 'Start a new section', subsection: 'Start a subsection',
            subsubsection: 'Start a sub-subsection', chapter: 'Start a chapter',
            textbf: 'Bold text: `{\\textbf{text}}`', textit: 'Italic text',
            texttt: 'Monospace (typewriter) text', emph: 'Emphasized text',
            begin: 'Begin an environment', end: 'End an environment',
            item: 'List item', label: 'Create a label for cross-referencing',
            ref: 'Reference a label', cite: 'Cite a bibliography entry',
            frac: 'Fraction: `\\frac{numerator}{denominator}`',
            sqrt: 'Square root: `\\sqrt{expr}` or `\\sqrt[n]{expr}`',
            includegraphics: 'Include an image file',
            usepackage: 'Load a LaTeX package',
            documentclass: 'Set the document class',
            newcommand: 'Define a new command',
          }

          const desc = descriptions[cmd]
          if (!desc) return null

          return {
            range: new monaco.Range(
              position.lineNumber, word.startColumn - 1,
              position.lineNumber, word.endColumn
            ),
            contents: [
              { value: `**\\${cmd}**` },
              { value: desc },
            ],
          }
        },
      })
      disposablesRef.current.push(hoverDisposable)

        _latexLanguageRegistered = true
      } // end !_latexLanguageRegistered
      monaco.editor.setTheme('latexy-dark')

      // ── Keyboard shortcuts ─────────────────────────────────────────
      if (onSave) {
        const d = editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSave())
        if (d) disposablesRef.current.push(d)
      }
      if (onCompile) {
        const d = editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onCompile())
        if (d) disposablesRef.current.push(d)
      }

      // ── Cursor change listener ─────────────────────────────────────
      if (onCursorChange) {
        const cursorDisposable = editor.onDidChangeCursorPosition((e: any) => {
          onCursorChange(e.position.lineNumber)
        })
        disposablesRef.current.push(cursorDisposable)
      }

    }

    return (
      <div className="flex h-full flex-col">
        <style>{`
          .synctex-highlight {
            background-color: rgba(245,158,11,0.15) !important;
            border-left: 2px solid #f59e0b !important;
          }
        `}</style>
        {!value ? (
          <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
            <p className="text-sm uppercase tracking-[0.14em] text-zinc-600">Empty document</p>
            <p className="mt-2 max-w-sm text-xs text-zinc-600">
              Start writing or use a sample template.
            </p>
            <button
              onClick={() => onChange(BLANK_RESUME_TEMPLATE)}
              className="mt-4 rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.08]"
            >
              Insert Sample Resume
            </button>
          </div>
        ) : (
          <div className="min-h-0 flex-1">
            <Editor
              height="100%"
              defaultLanguage="latex"
              value={value}
              onChange={(v) => onChange(v || '')}
              onMount={handleEditorDidMount}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                fontFamily: '"JetBrains Mono", "Fira Code", "Cascadia Code", Menlo, monospace',
                fontLigatures: true,
                lineNumbers: 'on',
                wordWrap: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 2,
                insertSpaces: true,
                renderLineHighlight: 'line',
                cursorBlinking: 'smooth',
                cursorSmoothCaretAnimation: 'on',
                smoothScrolling: true,
                contextmenu: true,
                readOnly,
                suggestOnTriggerCharacters: true,
                quickSuggestions: {
                  other: true,
                  comments: false,
                  strings: false,
                },
                folding: true,
                foldingHighlight: true,
                showFoldingControls: 'mouseover',
                bracketPairColorization: { enabled: false },
                renderWhitespace: 'selection',
                padding: { top: 8, bottom: 8 },
                scrollbar: {
                  vertical: 'visible',
                  horizontal: 'auto',
                  verticalScrollbarSize: 6,
                  horizontalScrollbarSize: 6,
                },
                overviewRulerLanes: 3,
                // Disable distracting features
                renderValidationDecorations: 'on',
                glyphMargin: true,
              }}
            />
          </div>
        )}

        {/* Status bar */}
        <div className="flex items-center justify-between border-t border-white/[0.05] bg-[#07090f] px-3 py-1 text-[10px] uppercase tracking-[0.12em]">
          <span className="text-zinc-700">
            {readOnly ? 'Read-only — job running' : 'LaTeX editor'}
          </span>
          <div className="flex items-center gap-3 text-zinc-700">
            <span>{value.length.toLocaleString()} chars</span>
            {onSave && <span className="text-zinc-800">⌘S save · ⌘↵ compile</span>}
          </div>
        </div>
      </div>
    )
  }
)

export default LaTeXEditor
