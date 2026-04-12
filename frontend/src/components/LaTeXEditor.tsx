'use client'

import { useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from 'react'

let _latexLanguageRegistered = false
import Editor, { type OnMount } from '@monaco-editor/react'
import type { LogLine } from '@/hooks/useJobStream'
import { BLANK_RESUME_TEMPLATE } from '@/lib/latex-templates'
import ATSScoreBadge from '@/components/ATSScoreBadge'
import type { PresenceUser, ProofreadIssue, SpellCheckIssue } from '@/lib/api-client'
import type { LintIssue } from '@/lib/latex-linter'
import { addWordToDict, getPersonalDict } from '@/hooks/useSpellCheck'
import LaTeXSearchPanel from '@/components/LaTeXSearchPanel'
import { LATEX_SEARCH_PRESETS, type LatexSearchPreset } from '@/data/latex-search-presets'
import { observeChanges, type TrackedChange, type TrackChangesHandle } from '@/lib/yjs-track-changes'

export interface LaTeXEditorRef {
  setValue: (value: string) => void
  getValue: () => string
  highlightLine: (line: number) => void
  applyFix: (line: number, correctedCode: string) => void
  applyRewrite: (startLine: number, startColumn: number, endLine: number, endColumn: number, text: string) => void
  applyMultipleRewrites: (edits: Array<{ startLine: number; startColumn: number; endLine: number; endColumn: number; text: string }>) => void
  insertAtCursor: (text: string) => void
  /** Returns pixel position of the cursor relative to the editor container, or null if unavailable */
  getCaretPosition: () => { top: number; left: number } | null
  acceptTrackedChange: (id: string) => void
  rejectTrackedChange: (id: string) => void
  acceptAllTrackedChanges: () => void
  rejectAllTrackedChanges: () => void
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
  /** When provided (auto-compile enabled), fires 2s after last keystroke with current content */
  onAutoCompile?: (content: string) => void
  /** Hide the "Insert Sample Resume" empty-state button (e.g. on cover letter pages) */
  hideEmptyAction?: boolean
  /** Live ATS quick-score value (null = not scored yet) */
  atsScore?: number | null
  /** Whether ATS quick-score is loading */
  atsScoreLoading?: boolean
  /** Callback when user clicks the ATS badge */
  onATSBadgeClick?: () => void
  /** Called when user clicks "Explain this error" CodeLens */
  onExplainError?: (error: { line: number; message: string; surroundingLatex: string }) => void
  /** Actual page count from last compile result (null = not compiled yet) */
  pageCount?: number | null
  /** Called (debounced 200ms) when cursor moves to a different line — fires with raw line content */
  onCursorLineChange?: (lineContent: string, lineNumber: number) => void
  /** Called when cursor enters or leaves a summary/objective/profile section */
  onCursorInSummarySection?: (inSummary: boolean) => void
  /** Called when user right-clicks and selects AI Writing Assistant from context menu */
  onWritingAssistantAction?: (info: {
    selectedText: string
    context: string
    startLine: number
    startColumn: number
    endLine: number
    endColumn: number
  }) => void
  /** Proofreader issues to render as inline decorations */
  proofreadIssues?: ProofreadIssue[]
  /** Linter issues to show as Monaco markers (squiggles) */
  lintIssues?: LintIssue[]
  /** Spell/grammar check issues from LanguageTool */
  spellCheckIssues?: SpellCheckIssue[]
  /** Whether spell check is currently enabled (for status bar indicator) */
  spellCheckEnabled?: boolean
  /** Toggle spell check on/off */
  onSpellCheckToggle?: () => void
  /** Whether spell check is loading (for status bar pulse) */
  spellCheckLoading?: boolean
  // ── Collaboration (Feature 40) ─────────────────────────────────────
  /** Enable Y.js CRDT collaboration */
  collabEnabled?: boolean
  /** Resume ID used as the Y.js room name */
  collabResumeId?: string
  /** Current user info for cursor labelling */
  collabUser?: { name: string; color: string; token: string }
  /** Fires when the set of remote-presence users changes */
  onPresenceChange?: (users: PresenceUser[]) => void
  // ── Track Changes (Feature 41) ──────────────────────────────────────
  /** Current tracked changes to render as decorations */
  trackedChanges?: TrackedChange[]
  /** Called when tracked changes are updated */
  onTrackedChangesUpdate?: (changes: TrackedChange[]) => void
  // ── Quality Score (Feature 59) ──────────────────────────────────────
  /** Resume quality/confidence score (0-100, null = not scored yet) */
  confidenceScore?: number | null
  /** Whether quality score is loading */
  confidenceScoreLoading?: boolean
  /** Callback when user clicks the quality score badge */
  onConfidenceBadgeClick?: () => void
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

// ── Rich environment snippets (Feature 30) ────────────────────────────────
// Overrides the generic insertText for specific \begin{env} completions.
// The text starts AFTER \begin{ so it begins with the env name.
const RICH_ENV_SNIPPETS: Record<string, string> = {
  itemize:
    'itemize}\n\t\\item ${1:First item}\n\t\\item ${2:Second item}\n\\end{itemize}',
  enumerate:
    'enumerate}\n\t\\item ${1:First item}\n\t\\item ${2:Second item}\n\\end{enumerate}',
  tabular:
    'tabular}{${1:lll}}\n\t${2:Col1} & ${3:Col2} & ${4:Col3} \\\\\\\\\n\t\\hline\n\t${5:Row1} & ${6:Data} & ${7:Data} \\\\\\\\\n\\end{tabular}',
  equation:
    'equation}\n\t${1:formula}\n\t\\label{eq:${2:label}}\n\\end{equation}',
  align:
    'align}\n\t${1:f(x)} &= ${2:g(x)} \\\\\\\\\n\t      &= ${3:h(x)}\n\\end{align}',
  figure:
    'figure}[htbp]\n\t\\centering\n\t\\includegraphics[width=0.8\\textwidth]{${1:filename}}\n\t\\caption{${2:Caption}}\n\t\\label{fig:${3:label}}\n\\end{figure}',
}

// Standalone keyword snippets — triggered when user types the bare keyword
interface KeywordSnippet { label: string; insertText: string; documentation: string }
const KEYWORD_SNIPPETS: Record<string, KeywordSnippet> = {
  doc: {
    label: 'doc — document boilerplate',
    insertText:
      '\\documentclass[${1:11pt}]{${2:article}}\n\\usepackage[T1]{fontenc}\n\\usepackage[utf8]{inputenc}\n\\usepackage{geometry}\n\\geometry{margin=1in}\n\n\\begin{document}\n\n${3:Content here}\n\n\\end{document}',
    documentation: 'Full document boilerplate',
  },
  sec: {
    label: 'sec — section with label',
    insertText: '\\section{${1:Section Title}}\n\\label{sec:${2:label}}\n\n${3}',
    documentation: 'Section with label',
  },
  fig: {
    label: 'fig — figure environment',
    insertText:
      '\\begin{figure}[htbp]\n\t\\centering\n\t\\includegraphics[width=0.8\\textwidth]{${1:filename}}\n\t\\caption{${2:Caption}}\n\t\\label{fig:${3:label}}\n\\end{figure}',
    documentation: 'Figure with caption and label',
  },
  eq: {
    label: 'eq — numbered equation',
    insertText:
      '\\begin{equation}\n\t${1:formula}\n\t\\label{eq:${2:label}}\n\\end{equation}',
    documentation: 'Numbered equation environment',
  },
  tab: {
    label: 'tab — tabular environment',
    insertText:
      '\\begin{tabular}{${1:lll}}\n\t${2:Col1} & ${3:Col2} & ${4:Col3} \\\\\\\\\n\t\\hline\n\t${5:Row1} & ${6:Data} & ${7:Data} \\\\\\\\\n\\end{tabular}',
    documentation: 'Table with header row',
  },
}

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
    { value, onChange, readOnly = false, logLines = [], onSave, onCompile, onCursorChange, syncLine, onAutoCompile, hideEmptyAction = false, atsScore, atsScoreLoading, onATSBadgeClick, onExplainError, pageCount, onCursorLineChange, onCursorInSummarySection, onWritingAssistantAction, proofreadIssues, lintIssues, spellCheckIssues, spellCheckEnabled, onSpellCheckToggle, spellCheckLoading, collabEnabled, collabResumeId, collabUser, onPresenceChange, trackedChanges, onTrackedChangesUpdate, confidenceScore, confidenceScoreLoading, onConfidenceBadgeClick },
    ref
  ) {
    const editorRef = useRef<any>(null)
    const monacoRef = useRef<any>(null)
    const disposablesRef = useRef<any[]>([])
    const proofreaderDecsRef = useRef<any>(null)
    const autoCompileRef = useRef(onAutoCompile)
    autoCompileRef.current = onAutoCompile
    const onExplainErrorRef = useRef(onExplainError)
    onExplainErrorRef.current = onExplainError
    const onCursorLineChangeRef = useRef(onCursorLineChange)
    onCursorLineChangeRef.current = onCursorLineChange
    const onCursorInSummarySectionRef = useRef(onCursorInSummarySection)
    onCursorInSummarySectionRef.current = onCursorInSummarySection
    const onWritingAssistantActionRef = useRef(onWritingAssistantAction)
    onWritingAssistantActionRef.current = onWritingAssistantAction
    const spellCheckIssuesRef = useRef(spellCheckIssues)
    spellCheckIssuesRef.current = spellCheckIssues
    const onPresenceChangeRef = useRef(onPresenceChange)
    onPresenceChangeRef.current = onPresenceChange
    const onTrackedChangesUpdateRef = useRef(onTrackedChangesUpdate)
    onTrackedChangesUpdateRef.current = onTrackedChangesUpdate

    // Y.js collab refs — cleaned up on unmount
    const ydocRef = useRef<any>(null)
    const providerRef = useRef<any>(null)
    const bindingRef = useRef<any>(null)
    // Track changes refs (Feature 41)
    const trackChangesRef = useRef<TrackChangesHandle | null>(null)
    const trackedChangesDecsRef = useRef<any>(null)

    // Cleanup Y.js session on unmount
    useEffect(() => {
      return () => {
        trackChangesRef.current?.cleanup()
        trackChangesRef.current = null
        bindingRef.current?.destroy()
        providerRef.current?.destroy()
        ydocRef.current?.destroy()
        bindingRef.current = null
        providerRef.current = null
        ydocRef.current = null
      }
    }, [])

    const [searchPanelOpen, setSearchPanelOpen] = useState(false)

    function handlePresetSelect(preset: LatexSearchPreset) {
      const editor = editorRef.current
      if (!editor) return

      // Prefer the public actions.findWithArgs action (registered in Monaco 0.34+,
      // stable in 0.55). It accepts searchString + isRegex directly without
      // touching any internal findController methods.
      if (editor.getAction('actions.findWithArgs')) {
        editor.trigger('keyboard', 'actions.findWithArgs', {
          searchString: preset.pattern,
          isRegex: true,
          matchCase: false,
          matchWholeWord: false,
        })
      } else {
        // Last-resort fallback for older Monaco builds: internal findController API
        const fc = editor.getContribution('editor.contrib.findController') as any
        if (fc) {
          try {
            const state = fc.getState?.()
            if (state && !state.isRegex) fc.toggleRegex()
            fc.setSearchString(preset.pattern)
          } catch {}
        } else {
          editor.getAction('actions.find')?.run()
        }
      }
      editor.focus()
    }

    // Pre-compile page count estimate (~50 text lines per page)
    const estimatedPageCount = useMemo(() => {
      if (!value || value.length < 100 || pageCount !== null && pageCount !== undefined) return null
      const lines = value.split('\n').filter(l => !l.trim().startsWith('%'))
      const textLines = lines.filter(l => !l.trim().startsWith('\\') || l.includes('item'))
      return Math.max(1, Math.round(textLines.length / 50))
    }, [value, pageCount])

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
      applyFix(line: number, correctedCode: string) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return
        const model = editor.getModel()
        if (!model) return
        const lineNum = Math.min(line, model.getLineCount())
        const lineContent = model.getLineContent(lineNum)
        editor.executeEdits('error-fix', [{
          range: new monaco.Range(lineNum, 1, lineNum, lineContent.length + 1),
          text: correctedCode,
        }])
      },
      applyRewrite(startLine: number, startColumn: number, endLine: number, endColumn: number, text: string) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return
        editor.executeEdits('writing-assistant', [{
          range: new monaco.Range(startLine, startColumn, endLine, endColumn),
          text,
        }])
        editor.focus()
      },
      applyMultipleRewrites(edits) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return
        // Sort descending by line then column so earlier edits don't shift
        // the positions of later ones in the document.
        const sorted = [...edits].sort(
          (a, b) => b.startLine - a.startLine || b.startColumn - a.startColumn
        )
        editor.executeEdits('proofread-autofix', sorted.map(e => ({
          range: new monaco.Range(e.startLine, e.startColumn, e.endLine, e.endColumn),
          text: e.text,
        })))
        editor.focus()
      },
      insertAtCursor(text: string) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return
        const position = editor.getPosition()
        if (!position) return
        editor.executeEdits('insert-bibtex', [{
          range: new monaco.Range(
            position.lineNumber, position.column,
            position.lineNumber, position.column,
          ),
          text,
        }])
        editor.focus()
      },
      getCaretPosition() {
        const editor = editorRef.current
        if (!editor) return null
        const position = editor.getPosition()
        if (!position) return null
        const pixel = editor.getScrolledVisiblePosition(position)
        if (!pixel) return null
        return { top: pixel.top, left: pixel.left }
      },
      acceptTrackedChange: (id: string) => { trackChangesRef.current?.acceptChange(id) },
      rejectTrackedChange: (id: string) => { trackChangesRef.current?.rejectChange(id) },
      acceptAllTrackedChanges: () => { trackChangesRef.current?.acceptAll() },
      rejectAllTrackedChanges: () => { trackChangesRef.current?.rejectAll() },
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

      // Refresh CodeLens so "Explain this error" links appear for new markers
      editor.trigger('latexy', 'editor.action.refreshCodeLenses', null)
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

    // Apply proofreader decorations when issues change
    useEffect(() => {
      const editor = editorRef.current
      const monaco = monacoRef.current
      if (!editor || !monaco) return

      if (proofreaderDecsRef.current) {
        proofreaderDecsRef.current.clear()
        proofreaderDecsRef.current = null
      }

      if (!proofreadIssues || proofreadIssues.length === 0) return

      const decorations = proofreadIssues.map(issue => ({
        range: new monaco.Range(issue.line, issue.column_start, issue.line, issue.column_end),
        options: {
          inlineClassName:
            issue.category === 'passive_voice' ? 'proofreader-passive'
            : issue.category === 'buzzword' ? 'proofreader-buzzword'
            : issue.category === 'vague' ? 'proofreader-vague'
            : 'proofreader-weak',
          hoverMessage: {
            value: `**${issue.category.replace(/_/g, ' ')}**: ${issue.message}`,
          },
        },
      }))

      proofreaderDecsRef.current = editor.createDecorationsCollection(decorations)
    }, [proofreadIssues])

    // Apply lint markers when lintIssues change
    useEffect(() => {
      const monaco = monacoRef.current
      const editor = editorRef.current
      if (!monaco || !editor) return

      const model = editor.getModel()
      if (!model) return

      const markers = (lintIssues ?? []).map((issue) => ({
        startLineNumber: issue.line,
        endLineNumber: issue.line,
        startColumn: issue.column,
        endColumn: issue.endColumn,
        severity:
          issue.severity === 'error'
            ? monaco.MarkerSeverity.Error
            : issue.severity === 'warning'
              ? monaco.MarkerSeverity.Warning
              : monaco.MarkerSeverity.Info,
        message: issue.message,
        source: `latexy-lint(${issue.ruleId})`,
      }))

      monaco.editor.setModelMarkers(model, 'latex-lint', markers)
    }, [lintIssues])

    // Apply spell-check markers when spellCheckIssues change
    useEffect(() => {
      const monaco = monacoRef.current
      const editor = editorRef.current
      if (!monaco || !editor) return

      const model = editor.getModel()
      if (!model) return

      const dict = getPersonalDict()

      const markers = (spellCheckIssues ?? []).flatMap((issue) => {
        // Extract the flagged word from the model to check personal dictionary
        const word = model.getValueInRange({
          startLineNumber: issue.line,
          startColumn: issue.column_start,
          endLineNumber: issue.line,
          endColumn: issue.column_end,
        }).toLowerCase()
        if (dict.has(word)) return []

        return [{
          startLineNumber: issue.line,
          endLineNumber: issue.line,
          startColumn: issue.column_start,
          endColumn: issue.column_end,
          // spelling → Error (red), grammar → Info (blue), style → Warning (amber)
          severity:
            issue.severity === 'spelling'
              ? monaco.MarkerSeverity.Error
              : issue.severity === 'style'
                ? monaco.MarkerSeverity.Warning
                : monaco.MarkerSeverity.Info,
          message: issue.message,
          source: `spellcheck(${issue.rule_id})`,
        }]
      })

      monaco.editor.setModelMarkers(model, 'spellcheck', markers)
    }, [spellCheckIssues])

    // Tracked changes decorations (Feature 41)
    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return
      if (!trackedChangesDecsRef.current) {
        trackedChangesDecsRef.current = editor.createDecorationsCollection([])
      }
      if (!trackedChanges || trackedChanges.length === 0) {
        trackedChangesDecsRef.current.set([])
        return
      }
      const decorations = trackedChanges.map((c) => ({
        range: {
          startLineNumber: c.range.startLineNumber,
          startColumn: c.range.startColumn,
          endLineNumber: c.range.endLineNumber,
          endColumn: c.range.endColumn,
        },
        options: c.type === 'insertion'
          ? {
              className: 'tracked-insertion',
              hoverMessage: { value: `**${c.userName}** inserted — *Accept or Reject in Changes panel*` },
            }
          : {
              glyphMarginClassName: 'tracked-deletion-glyph',
              hoverMessage: { value: `**${c.userName}** deleted "${c.text.slice(0, 40)}" — *Accept or Reject in Changes panel*` },
            },
      }))
      trackedChangesDecsRef.current.set(decorations)
    }, [trackedChanges])

    // Auto-compile: debounce 2s after last keystroke
    useEffect(() => {
      const editor = editorRef.current
      if (!editor) return

      let timer: ReturnType<typeof setTimeout> | null = null
      const disposable = editor.onDidChangeModelContent(() => {
        if (!autoCompileRef.current) return
        if (timer) clearTimeout(timer)
        timer = setTimeout(() => {
          const model = editor.getModel()
          if (!model || model.getValueLength() < 100) return
          autoCompileRef.current?.(editor.getValue())
        }, 2000)
      })

      return () => {
        disposable.dispose()
        if (timer) clearTimeout(timer)
      }
    }, []) // stable — uses ref for callback

    // Cleanup on unmount
    useEffect(() => {
      return () => {
        for (const d of disposablesRef.current) d?.dispose?.()
        disposablesRef.current = []
      }
    }, [])

    const handleEditorDidMount: OnMount = async (editor, monaco) => {
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
                  insertText: RICH_ENV_SNIPPETS[env] ?? `${env}}\n\t$0\n\\end{${env}}`,
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

          // Standalone keyword snippets (doc, sec, fig, eq, tab)
          const word = model.getWordUntilPosition(position)
          if (word.word && word.word in KEYWORD_SNIPPETS) {
            const snippet = KEYWORD_SNIPPETS[word.word]
            const kwRange = {
              startLineNumber: position.lineNumber,
              startColumn: word.startColumn,
              endLineNumber: position.lineNumber,
              endColumn: position.column,
            }
            suggestions.push({
              label: snippet.label,
              kind: monaco.languages.CompletionItemKind.Snippet,
              insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet,
              insertText: snippet.insertText,
              range: kwRange,
              documentation: snippet.documentation,
              sortText: '00' + word.word,
            })
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

      // ── CodeLens provider (Explain this error) ──────────────────────
      // Register a unique command that CodeLens items can reference
      const explainCmdId = editor.addCommand(0, (_ctx: any, lineNumber: number, message: string) => {
        const model = editor.getModel()
        if (!model || !onExplainErrorRef.current) return
        const startLine = Math.max(1, lineNumber - 3)
        const endLine = Math.min(model.getLineCount(), lineNumber + 3)
        const lines: string[] = []
        for (let i = startLine; i <= endLine; i++) {
          lines.push(model.getLineContent(i))
        }
        onExplainErrorRef.current({
          line: lineNumber,
          message,
          surroundingLatex: lines.join('\n'),
        })
      })

      const codeLensDisposable = monaco.languages.registerCodeLensProvider('latex', {
        provideCodeLenses(model: import('monaco-editor').editor.ITextModel) {
          const markers = monaco.editor.getModelMarkers({ owner: 'latex-log' })
          const lenses: any[] = []
          const seenLines = new Set<number>()
          for (const marker of markers) {
            if (marker.severity !== monaco.MarkerSeverity.Error || seenLines.has(marker.startLineNumber)) continue
            seenLines.add(marker.startLineNumber)
            lenses.push({
              range: new monaco.Range(marker.startLineNumber, 1, marker.startLineNumber, 1),
              id: `explain-${marker.startLineNumber}`,
              command: {
                id: explainCmdId!,
                title: '$(lightbulb) Explain this error',
                arguments: [marker.startLineNumber, marker.message],
              },
            })
          }
          return { lenses, dispose() {} }
        },
        resolveCodeLens(_model: import('monaco-editor').editor.ITextModel, codeLens: any) {
          return codeLens
        },
      })
      disposablesRef.current.push(codeLensDisposable)

      // ── Keyboard shortcuts ─────────────────────────────────────────
      if (onSave) {
        const d = editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSave())
        if (d) disposablesRef.current.push(d)
      }
      if (onCompile) {
        const d = editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onCompile())
        if (d) disposablesRef.current.push(d)
      }
      // ⌘⇧H — open LaTeX Presets panel
      {
        const d = editor.addCommand(
          monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyH,
          () => setSearchPanelOpen(true),
        )
        if (d) disposablesRef.current.push(d)
      }

      // ── Cursor change listener ─────────────────────────────────────
      if (onCursorChange) {
        const cursorDisposable = editor.onDidChangeCursorPosition((e: any) => {
          onCursorChange(e.position.lineNumber)
        })
        disposablesRef.current.push(cursorDisposable)
      }

      // ── Cursor line-content change (debounced 200ms) ───────────────
      {
        let lineTimer: ReturnType<typeof setTimeout> | null = null
        const lineDisposable = editor.onDidChangeCursorPosition((e: any) => {
          if (!onCursorLineChangeRef.current) return
          if (lineTimer) clearTimeout(lineTimer)
          lineTimer = setTimeout(() => {
            const model = editor.getModel()
            if (!model) return
            const content = model.getLineContent(e.position.lineNumber) ?? ''
            onCursorLineChangeRef.current?.(content, e.position.lineNumber)
          }, 200)
        })
        disposablesRef.current.push(lineDisposable)
        disposablesRef.current.push({ dispose: () => { if (lineTimer) clearTimeout(lineTimer) } })
      }

      // ── Summary section detection (debounced 300ms) ────────────────
      {
        let summaryTimer: ReturnType<typeof setTimeout> | null = null
        const summaryDisposable = editor.onDidChangeCursorPosition((e: any) => {
          if (!onCursorInSummarySectionRef.current) return
          if (summaryTimer) clearTimeout(summaryTimer)
          summaryTimer = setTimeout(() => {
            const model = editor.getModel()
            if (!model) return
            const lineNumber = e.position.lineNumber
            const lines = model.getValue().split('\n')
            let inSummary = false
            for (let i = lineNumber - 1; i >= 0; i--) {
              if (/\\section\*?\{(summary|objective|profile|about)\}/i.test(lines[i])) {
                inSummary = true
                break
              }
              if (/\\section\*?\{/i.test(lines[i])) break
            }
            onCursorInSummarySectionRef.current?.(inSummary)
          }, 300)
        })
        disposablesRef.current.push(summaryDisposable)
        disposablesRef.current.push({ dispose: () => { if (summaryTimer) clearTimeout(summaryTimer) } })
      }

      // ── AI Writing Assistant context menu action ───────────────────
      const writingActionDisposable = editor.addAction({
        id: 'latexy.writingAssistant',
        label: '✨ AI Writing Assistant',
        contextMenuGroupId: 'navigation',
        contextMenuOrder: 1.5,
        precondition: 'editorHasSelection',
        run: (ed) => {
          const selection = ed.getSelection()
          if (!selection) return
          const model = ed.getModel()
          if (!model) return
          const selectedText = model.getValueInRange(selection)
          if (!selectedText.trim()) return
          // Collect 5 lines of surrounding context
          const ctxStart = Math.max(1, selection.startLineNumber - 5)
          const ctxEnd = Math.min(model.getLineCount(), selection.endLineNumber + 5)
          const ctxLines: string[] = []
          for (let i = ctxStart; i <= ctxEnd; i++) ctxLines.push(model.getLineContent(i))
          onWritingAssistantActionRef.current?.({
            selectedText,
            context: ctxLines.join('\n'),
            startLine: selection.startLineNumber,
            startColumn: selection.startColumn,
            endLine: selection.endLineNumber,
            endColumn: selection.endColumn,
          })
        },
      })
      if (writingActionDisposable) disposablesRef.current.push(writingActionDisposable)

      // ── Spell-check code actions (right-click replacements + Add to Dictionary) ──
      // Register a command for "Add to dictionary" so it can be referenced by code actions
      const addToDictCmdId = editor.addCommand(0, (_ctx: any, word: string) => {
        addWordToDict(word)
        // Force markers to refresh by clearing and re-setting with updated dictionary
        const m = editor.getModel()
        const mc = monacoRef.current
        if (!m || !mc) return
        const dict = getPersonalDict()
        const refreshed = (spellCheckIssuesRef.current ?? []).flatMap((issue) => {
          const w = m.getValueInRange({
            startLineNumber: issue.line,
            startColumn: issue.column_start,
            endLineNumber: issue.line,
            endColumn: issue.column_end,
          }).toLowerCase()
          if (dict.has(w)) return []
          return [{
            startLineNumber: issue.line,
            endLineNumber: issue.line,
            startColumn: issue.column_start,
            endColumn: issue.column_end,
            severity:
              issue.severity === 'spelling'
                ? mc.MarkerSeverity.Error
                : issue.severity === 'style'
                  ? mc.MarkerSeverity.Warning
                  : mc.MarkerSeverity.Info,
            message: issue.message,
            source: `spellcheck(${issue.rule_id})`,
          }]
        })
        mc.editor.setModelMarkers(m, 'spellcheck', refreshed)
      })

      // Only register if language is already registered (inside or outside the guard)
      const spellCodeActionDisposable = monaco.languages.registerCodeActionProvider('latex', {
        provideCodeActions(
          model: import('monaco-editor').editor.ITextModel,
          _range: import('monaco-editor').Range,
          context: import('monaco-editor').languages.CodeActionContext,
        ) {
          const spellMarkers = context.markers.filter((m) =>
            m.source?.startsWith('spellcheck(')
          )
          if (spellMarkers.length === 0) return { actions: [], dispose() {} }

          const marker = spellMarkers[0]
          const flaggedWord = model.getValueInRange({
            startLineNumber: marker.startLineNumber,
            startColumn: marker.startColumn,
            endLineNumber: marker.endLineNumber,
            endColumn: marker.endColumn,
          })

          const issue = spellCheckIssuesRef.current?.find(
            (iss) =>
              iss.line === marker.startLineNumber &&
              iss.column_start === marker.startColumn
          )

          const actions: import('monaco-editor').languages.CodeAction[] = []

          for (const rep of (issue?.replacements ?? []).slice(0, 5)) {
            actions.push({
              title: `Replace with "${rep}"`,
              kind: 'quickfix',
              edit: {
                edits: [{
                  resource: model.uri,
                  versionId: model.getVersionId(),
                  textEdit: {
                    range: {
                      startLineNumber: marker.startLineNumber,
                      startColumn: marker.startColumn,
                      endLineNumber: marker.endLineNumber,
                      endColumn: marker.endColumn,
                    },
                    text: rep,
                  },
                }],
              },
              isPreferred: (issue?.replacements ?? []).indexOf(rep) === 0,
            })
          }

          if (flaggedWord.trim()) {
            actions.push({
              title: `Add "${flaggedWord}" to dictionary`,
              kind: 'quickfix',
              command: {
                id: addToDictCmdId!,
                title: `Add "${flaggedWord}" to dictionary`,
                arguments: [flaggedWord],
              },
            })
          }

          return { actions, dispose() {} }
        },
      })
      disposablesRef.current.push(spellCodeActionDisposable)

      // ── Y.js real-time collaboration (Feature 40) ────────────────────
      if (collabEnabled && collabResumeId && collabUser) {
        try {
          const Y = await import('yjs')
          const { WebsocketProvider } = await import('y-websocket')
          const { MonacoBinding } = await import('y-monaco')

          const ydoc = new Y.Doc()
          const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030')
          const wsBase = apiUrl.replace(/^https?:\/\//, (m) => (m.startsWith('https') ? 'wss://' : 'ws://'))

          const provider = new WebsocketProvider(
            `${wsBase}/ws/collab`,
            collabResumeId,
            ydoc,
            {
              params: {
                token: collabUser.token,
                name: collabUser.name,
                color: collabUser.color,
              },
            },
          )

          const yText = ydoc.getText('content')
          const model = editor.getModel()
          if (model) {
            const binding = new MonacoBinding(yText, model, new Set([editor]), provider.awareness)
            bindingRef.current = binding
          }

          provider.awareness.setLocalStateField('user', {
            name: collabUser.name,
            color: collabUser.color,
          })

          // Broadcast presence changes to parent
          provider.awareness.on('change', () => {
            const states = provider.awareness.getStates()
            const others = Array.from(states.entries())
              .filter(([id]: [number, any]) => id !== provider.awareness.clientID)
              .map(([, s]: [number, any]) => s?.user)
              .filter(Boolean)
            onPresenceChangeRef.current?.(others)
          })

          // Seed the Y.Doc with the current value once synced (if remote doc is empty)
          const handleSync = (isSynced: boolean) => {
            if (!isSynced) return
            if (yText.length === 0 && value) {
              ydoc.transact(() => yText.insert(0, value))
            }
            provider.off('sync', handleSync)
          }
          provider.on('sync', handleSync)

          ydocRef.current = ydoc
          providerRef.current = provider

          // Track changes (Feature 41)
          trackChangesRef.current = observeChanges(yText, provider, (updatedChanges) => {
            onTrackedChangesUpdateRef.current?.(updatedChanges)
          })
        } catch (err) {
          console.warn('[LaTeXEditor] Y.js collab init failed:', err)
        }
      }

    }

    return (
      <div className="flex h-full flex-col">
        <style>{`
          .synctex-highlight {
            background-color: rgba(245,158,11,0.15) !important;
            border-left: 2px solid #f59e0b !important;
          }
          .proofreader-weak {
            text-decoration: underline wavy #f59e0b;
            text-underline-offset: 2px;
          }
          .proofreader-passive {
            text-decoration: underline wavy #60a5fa;
            text-underline-offset: 2px;
          }
          .proofreader-buzzword {
            text-decoration: underline wavy #a78bfa;
            text-underline-offset: 2px;
          }
          .proofreader-vague {
            text-decoration: underline wavy #f87171;
            text-underline-offset: 2px;
          }
          /* Y.js remote cursor labels */
          .yRemoteSelectionHead::after {
            content: attr(data-user-name);
            font-size: 10px;
            font-family: sans-serif;
            padding: 1px 4px;
            border-radius: 3px;
            position: absolute;
            top: -1.4em;
            left: 0;
            white-space: nowrap;
            background-color: var(--user-color, #7c3aed);
            color: #fff;
            pointer-events: none;
            z-index: 10;
          }
          .yRemoteSelectionHead {
            position: absolute;
            border-left: 2px solid var(--user-color, #7c3aed);
            height: 100%;
          }
          .yRemoteSelection {
            background-color: var(--user-color-light, rgba(124,58,237,0.12));
          }
          /* Tracked changes (Feature 41) */
          .tracked-insertion {
            background-color: rgba(74,222,128,0.15);
            border-bottom: 2px solid rgba(74,222,128,0.6);
          }
          .tracked-deletion-glyph {
            width: 8px !important;
            height: 8px !important;
            border-radius: 50%;
            background-color: rgba(248,113,113,0.8);
            margin-top: 6px;
          }
        `}</style>
        {!value ? (
          <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
            <p className="text-sm uppercase tracking-[0.14em] text-zinc-600">Empty document</p>
            <p className="mt-2 max-w-sm text-xs text-zinc-600">
              {hideEmptyAction ? 'Content will appear here once generated.' : 'Start writing or use a sample template.'}
            </p>
            {!hideEmptyAction && (
              <button
                onClick={() => onChange(BLANK_RESUME_TEMPLATE)}
                className="mt-4 rounded-lg border border-white/[0.08] bg-white/[0.04] px-4 py-2 text-xs font-medium text-zinc-300 transition hover:bg-white/[0.08]"
              >
                Insert Sample Resume
              </button>
            )}
          </div>
        ) : (
          <div className="relative min-h-0 flex-1">
            <LaTeXSearchPanel
              presets={LATEX_SEARCH_PRESETS}
              isOpen={searchPanelOpen}
              onToggle={() => setSearchPanelOpen((v) => !v)}
              onClose={() => setSearchPanelOpen(false)}
              onPresetSelect={handlePresetSelect}
            />
            <Editor
              height="100%"
              defaultLanguage="latex"
              {...(collabEnabled ? { defaultValue: '' } : { value })}
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
            {onAutoCompile && (
              <span className="flex items-center gap-1 text-[10px] text-orange-400/70">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-orange-400/70" />
                Auto
              </span>
            )}
            {/* Page count badge — actual (post-compile) or estimated (pre-compile) */}
            {(pageCount !== null && pageCount !== undefined) ? (
              <span
                title={`Resume is ${pageCount} page${pageCount === 1 ? '' : 's'}`}
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md ${
                  pageCount === 1
                    ? 'text-emerald-400 bg-emerald-500/10'
                    : pageCount === 2
                    ? 'text-amber-400 bg-amber-500/10'
                    : 'text-rose-400 bg-rose-500/10 animate-pulse'
                }`}
              >
                {pageCount} {pageCount === 1 ? 'page' : 'pages'}{pageCount > 1 ? ' ⚠' : ''}
              </span>
            ) : estimatedPageCount !== null ? (
              <span
                title="Estimated page count (compile for exact count)"
                className="text-[10px] text-zinc-600 px-1.5"
              >
                ~{estimatedPageCount} {estimatedPageCount === 1 ? 'page' : 'pages'}
              </span>
            ) : null}
            {onSpellCheckToggle && (
              <button
                onClick={onSpellCheckToggle}
                title={spellCheckEnabled ? 'Spell check on — click to disable' : 'Spell check off — click to enable'}
                className={`flex items-center gap-1 text-[10px] transition ${
                  spellCheckEnabled
                    ? 'text-blue-400 hover:text-blue-300'
                    : 'text-zinc-700 hover:text-zinc-400'
                }`}
              >
                ABC{spellCheckEnabled ? ' ✓' : ''}
                {spellCheckLoading && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
                )}
              </button>
            )}
            {(atsScore !== undefined || atsScoreLoading) && (
              <ATSScoreBadge
                score={atsScore ?? null}
                loading={atsScoreLoading ?? false}
                onClick={onATSBadgeClick}
              />
            )}
            {(confidenceScore !== undefined || confidenceScoreLoading) && (
              confidenceScoreLoading ? (
                <span className="flex items-center gap-1 text-[10px] text-zinc-500">
                  <span className="h-1.5 w-1.5 animate-spin rounded-full border border-zinc-500 border-t-transparent" />
                  Quality
                </span>
              ) : confidenceScore != null ? (
                <button
                  type="button"
                  onClick={onConfidenceBadgeClick}
                  title="Resume quality score — click to view details"
                  className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors cursor-pointer hover:brightness-110 ${
                    confidenceScore >= 80
                      ? 'text-emerald-400 bg-emerald-500/10'
                      : confidenceScore >= 60
                        ? 'text-amber-400 bg-amber-500/10'
                        : 'text-rose-400 bg-rose-500/10'
                  }`}
                >
                  Q {confidenceScore}
                </button>
              ) : null
            )}
            <span>{value.length.toLocaleString()} chars</span>
            <span className="text-zinc-800">
              {[onSave && '⌘S save', onCompile && '⌘↵ compile', '⌘⇧H presets'].filter(Boolean).join(' · ')}
            </span>
          </div>
        </div>
      </div>
    )
  }
)

export default LaTeXEditor
