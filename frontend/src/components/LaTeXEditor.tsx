'use client'

import dynamic from 'next/dynamic'
import { useEffect, useImperativeHandle, useMemo, useRef, useState, forwardRef } from 'react'
import katex from 'katex'
import { toast } from 'sonner'
import '@/lib/monaco-loader'
import 'katex/dist/katex.min.css'

let _latexLanguageRegistered = false
import type { OnMount } from '@monaco-editor/react'
import type { LogLine } from '@/hooks/useJobStream'
import { BLANK_RESUME_TEMPLATE } from '@/lib/latex-templates'
import ATSScoreBadge from '@/components/ATSScoreBadge'
import { apiClient, getCollabWebSocketUrl } from '@/lib/api-client'
import type { PresenceUser, ProofreadIssue, SpellCheckIssue } from '@/lib/api-client'
import type { LintIssue } from '@/lib/latex-linter'
import { addWordToDict, getPersonalDict } from '@/hooks/useSpellCheck'
import LaTeXSearchPanel from '@/components/LaTeXSearchPanel'
import { LATEX_SEARCH_PRESETS, type LatexSearchPreset } from '@/data/latex-search-presets'
import { observeChanges, type TrackedChange, type TrackChangesHandle } from '@/lib/yjs-track-changes'
import { classifyCollabClose } from '@/lib/collab-close'
import { createYWebsocketChatTransport, type ChatTransport } from '@/lib/collab-chat'
import { keepLatestSuggestionDecisions, namespaceSuggestionPresence, sanitizeSuggestionDecision, sanitizeSuggestionPresence, type SuggestionDecision, type SuggestionPresence } from '@/lib/suggestions'
import {
  extractCitationKeys,
  extractLatexLabels,
  matchLatexArgumentCompletion,
} from '@/lib/latex-completions'
import { buildLatexFoldingRanges } from '@/lib/latex-folding'
import { countRenderedWords } from '@/lib/rendered-word-count'
import { buildLatexHoverPreview, markdownCodeSpan, type LatexHoverPreview } from '@/lib/latex-hover-previews'
import {
  activateEditorKeybindings,
  parseEditorKeybindingMode,
  type EditorKeybindingAdapter,
  type EditorKeybindingMode,
} from '@/lib/editor-keybindings'

const MonacoEditor = dynamic(() => import('@monaco-editor/react').then((module) => module.default), {
  ssr: false,
  loading: () => <div className="h-full w-full bg-bg" aria-hidden="true" />,
})

type MonacoEditorInstance = import('monaco-editor').editor.IStandaloneCodeEditor
type MonacoNamespace = typeof import('monaco-editor')
const completionBibliographyByModel = new WeakMap<
  import('monaco-editor').editor.ITextModel,
  () => string
>()
type LatexyMonacoTestWindow = Window & {
  __latexyMonacoEditor?: MonacoEditorInstance
  __latexyMonaco?: MonacoNamespace
  __latexyKeybindingMode?: EditorKeybindingMode
}

function isEditorTestRuntime() {
  return process.env.NODE_ENV !== 'production' || process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1'
}

function exposeMonacoTestHook(editor: MonacoEditorInstance, monaco: MonacoNamespace) {
  if (!isEditorTestRuntime() || typeof window === 'undefined') return
  const testWindow = window as LatexyMonacoTestWindow
  testWindow.__latexyMonacoEditor = editor
  testWindow.__latexyMonaco = monaco
}

function clearMonacoTestHook(editor?: MonacoEditorInstance | null) {
  if (!isEditorTestRuntime() || typeof window === 'undefined') return
  const testWindow = window as LatexyMonacoTestWindow
  if (editor && testWindow.__latexyMonacoEditor && testWindow.__latexyMonacoEditor !== editor) return
  delete testWindow.__latexyMonacoEditor
  delete testWindow.__latexyMonaco
}

function LatexRichHoverCard({ preview, left, top }: {
  preview: LatexHoverPreview
  left: number
  top: number
}) {
  return (
    <div
      role="tooltip"
      data-testid="latex-rich-hover"
      className="pointer-events-none absolute z-[70] max-w-sm rounded-[var(--radius-md)] border border-line bg-surface p-3 text-xs text-fg shadow-[var(--shadow-2)]"
      style={{ left, top }}
    >
      {preview.kind === 'math' && (
        <>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Rendered math</p>
          <div
            className="overflow-x-auto py-1 text-center"
            dangerouslySetInnerHTML={{
              __html: katex.renderToString(preview.latex, {
                displayMode: preview.displayMode,
                throwOnError: false,
                strict: 'warn',
                trust: false,
                output: 'htmlAndMathml',
              }),
            }}
          />
        </>
      )}
      {preview.kind === 'graphic' && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Graphic include</p>
          <p className="mt-2 break-all font-mono text-accent-strong">{preview.filename}</p>
          {preview.options && <p className="mt-1 break-words text-fg-3">{preview.options}</p>}
          <p className="mt-2 text-[10px] leading-relaxed text-fg-3">Previewed from source metadata; the compiled PDF is authoritative.</p>
        </>
      )}
      {preview.kind === 'citation' && (
        <>
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Citation preview</p>
          <div className="space-y-2">
            {preview.citations.slice(0, 5).map((citation) => (
              <div key={citation.key}>
                <p className="font-mono text-[10px] text-accent-strong">{citation.key}{citation.type ? ` · ${citation.type}` : ''}</p>
                <p className="mt-0.5 font-medium">{citation.title ?? 'No saved bibliography metadata'}</p>
                {(citation.author || citation.year) && <p className="mt-0.5 text-[10px] text-fg-3">{[citation.author, citation.year].filter(Boolean).join(' · ')}</p>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

// ── Collaboration permissions (Feature 40) ────────────────────────────────
// Mirrors EDIT_ROLES in backend/app/services/collab_manager.py.
const COLLAB_EDIT_ROLES = new Set(['owner', 'editor'])
// Latexy protocol extension emitted by the relay when a frame is refused.
const MSG_PERMISSION_DENIED = 63

/**
 * Read a lib0 varbuffer straight off a y-websocket decoder.
 * (lib0 is a transitive dependency only, so it is not importable here.)
 */
function readVarBuffer(decoder: { arr: Uint8Array; pos: number }): Uint8Array {
  let length = 0
  let shift = 0
  for (;;) {
    const byte = decoder.arr[decoder.pos++]
    length |= (byte & 0x7f) << shift
    if ((byte & 0x80) === 0) break
    shift += 7
  }
  const payload = decoder.arr.subarray(decoder.pos, decoder.pos + length)
  decoder.pos += length
  return payload
}

export interface LaTeXEditorRef {
  /** Replace the buffer. By default the view scrolls to the end; pass
   *  `{ reveal: false }` for streaming updates so the viewport doesn't jerk
   *  to the bottom on every token. */
  setValue: (value: string, opts?: { reveal?: boolean }) => void
  getValue: () => string
  highlightLine: (line: number) => void
  applyFix: (line: number, correctedCode: string) => void
  applyRewrite: (startLine: number, startColumn: number, endLine: number, endColumn: number, text: string) => void
  /** Apply the exact server-authoritative source once, if the local source is unchanged. */
  applySuggestionResult: (expectedContent: string, resultContent: string) => boolean
  applyMultipleRewrites: (edits: Array<{ startLine: number; startColumn: number; endLine: number; endColumn: number; text: string }>) => void
  /** Insert text at the current caret. Returns false until Monaco is ready. */
  insertAtCursor: (text: string) => boolean
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
  /** Expose the live Monaco instance to integrations such as macro playback. */
  onEditorReady?: (editor: MonacoEditorInstance | null) => void
  /** Saved references.bib content used by citation autocomplete. */
  bibliographyBibTeX?: string
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
  /** Whether multi-page output should be styled as a resume overflow warning. */
  warnOnMultiplePages?: boolean
  /** pdftotext output from the last compile; used for an honest rendered-word count. */
  renderedText?: string | null
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
  /** Called when user right-clicks a LaTeX command and selects Show Documentation */
  onShowDocs?: (command: string) => void
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
  collabUser?: { name: string; color: string }
  /** Known collaborator role; anything other than owner/editor forces read-only */
  collabRole?: string | null
  /** Fires when the set of remote-presence users changes */
  onPresenceChange?: (users: PresenceUser[]) => void
  /** Exposes a bounded adapter over this editor's authenticated Y websocket. */
  onChatTransport?: (transport: ChatTransport | null) => void
  /** Ephemeral suggestion payload published through the existing Y.js awareness channel. */
  suggestionPresence?: SuggestionPresence
  /** Receives validated suggestion payloads from live peers. */
  onSuggestionPresenceChange?: (peers: SuggestionPresence[]) => void
  /** Server-confirmed decisions mirrored through Y.Map as a live notification. */
  suggestionDecisions?: SuggestionDecision[]
  onSuggestionDecisionsChange?: (decisions: SuggestionDecision[]) => void
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
  // ── Collaboration Comments (Feature 74) ─────────────────────────────
  /** Line numbers that have at least one comment — renders a glyph icon */
  commentedLines?: number[]
  /** Called when the user clicks a comment glyph in the editor margin */
  onCommentIconClick?: (lineNumber: number) => void
}

// ── LaTeX command corpus ───────────────────────────────────────────────────

const STRUCTURE_CMDS = [
  'part', 'chapter', 'section', 'subsection', 'subsubsection',
  'paragraph', 'subparagraph',
  'part*', 'chapter*', 'section*', 'subsection*', 'subsubsection*',
]
const DOC_CMDS = [
  'documentclass', 'usepackage', 'begin', 'end', 'item',
  'label', 'ref', 'eqref', 'pageref', 'autoref', 'cref', 'Cref', 'vref', 'Vref', 'nameref',
  'cite', 'citep', 'citet', 'citealp', 'citealt', 'citeauthor', 'citeyear',
  'citeyearpar', 'nocite', 'parencite', 'textcite', 'autocite', 'footcite', 'smartcite',
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

// ── Editor themes ───────────────────────────────────────────────────────
// Defined unconditionally on every editor mount (defineTheme is idempotent) so
// the light theme ALWAYS exists — it must not sit behind the run-once language
// guard, or a hot-reload / prior mount leaves it undefined and setTheme falls
// back to dark on a light page.
function defineLatexyThemes(monaco: MonacoNamespace) {
  monaco.editor.defineTheme('latexy-dark', {
    base: 'vs-dark',
    inherit: true,
    rules: [
      { token: 'comment',           foreground: '6b7280', fontStyle: 'italic' },
      { token: 'keyword.structure', foreground: 'fb923c', fontStyle: 'bold' },
      { token: 'keyword.doc',       foreground: '818cf8' },
      { token: 'keyword.font',      foreground: '67e8f9' },
      { token: 'keyword.math',      foreground: 'f472b6' },
      { token: 'keyword.special',   foreground: 'fbbf24' },
      { token: 'keyword',           foreground: 'fcd34d' },
      { token: 'math.delim',        foreground: 'ec4899', fontStyle: 'bold' },
      { token: 'math.content',      foreground: 'f9a8d4' },
      { token: 'math.command',      foreground: 'f472b6' },
      { token: 'math.bracket',      foreground: 'a78bfa' },
      { token: 'delimiter.bracket', foreground: 'a78bfa' },
      { token: 'delimiter.square',  foreground: 'c4b5fd' },
      { token: 'number',            foreground: '86efac' },
    ],
    colors: {
      'editor.background':            '#0d1117',
      'editor.foreground':            '#e2e8f0',
      'editor.lineHighlightBackground': '#161b22',
      'editor.selectionBackground':   '#1e3a5f',
      'editor.inactiveSelectionBackground': '#162a44',
      'editorLineNumber.foreground':  '#4b5563',
      'editorLineNumber.activeForeground': '#9ca3af',
      'editorCursor.foreground':      '#f59e0b',
      'editorWhitespace.foreground':  '#1e293b',
      'editorIndentGuide.background': '#1e293b',
      'editorIndentGuide.activeBackground': '#334155',
      'editorOverviewRuler.background': '#0d1117',
      'scrollbar.shadow':             '#00000000',
      'scrollbarSlider.background':   '#334155aa',
      'scrollbarSlider.hoverBackground': '#475569bb',
      'editorGutter.background':      '#0d1117',
    },
  })
  // Light counterpart — warm paper-white surface, muted higher-contrast ink.
  monaco.editor.defineTheme('latexy-light', {
    base: 'vs',
    inherit: true,
    rules: [
      { token: 'comment',           foreground: '8a8f98', fontStyle: 'italic' },
      { token: 'keyword.structure', foreground: 'c2410c', fontStyle: 'bold' },
      { token: 'keyword.doc',       foreground: '4f46e5' },
      { token: 'keyword.font',      foreground: '0e7490' },
      { token: 'keyword.math',      foreground: 'be185d' },
      { token: 'keyword.special',   foreground: 'b45309' },
      { token: 'keyword',           foreground: 'a16207' },
      { token: 'math.delim',        foreground: 'be185d', fontStyle: 'bold' },
      { token: 'math.content',      foreground: 'a21caf' },
      { token: 'math.command',      foreground: 'be185d' },
      { token: 'math.bracket',      foreground: '7c3aed' },
      { token: 'delimiter.bracket', foreground: '7c3aed' },
      { token: 'delimiter.square',  foreground: '9333ea' },
      { token: 'number',            foreground: '15803d' },
    ],
    colors: {
      'editor.background':            '#fbfbf9',
      'editor.foreground':            '#26282d',
      'editor.lineHighlightBackground': '#f1f1ec',
      'editor.selectionBackground':   '#d6e4f5',
      'editor.inactiveSelectionBackground': '#e8eef6',
      'editorLineNumber.foreground':  '#b8b8b0',
      'editorLineNumber.activeForeground': '#4b5563',
      'editorCursor.foreground':      '#d97706',
      'editorWhitespace.foreground':  '#e6e6df',
      'editorIndentGuide.background': '#ecece5',
      'editorIndentGuide.activeBackground': '#d6d6cd',
      'editorOverviewRuler.background': '#fbfbf9',
      'scrollbar.shadow':             '#00000000',
      'scrollbarSlider.background':   '#c8c8be88',
      'scrollbarSlider.hoverBackground': '#b0b0a6aa',
      'editorGutter.background':      '#fbfbf9',
    },
  })
}

// ── Component ─────────────────────────────────────────────────────────────

const LaTeXEditor = forwardRef<LaTeXEditorRef, LaTeXEditorProps>(
  function LaTeXEditor(
    { value, onChange, onEditorReady, bibliographyBibTeX = '', readOnly = false, logLines = [], onSave, onCompile, onCursorChange, syncLine, onAutoCompile, hideEmptyAction = false, atsScore, atsScoreLoading, onATSBadgeClick, onShowDocs, onExplainError, pageCount, warnOnMultiplePages = true, renderedText, onCursorLineChange, onCursorInSummarySection, onWritingAssistantAction, proofreadIssues, lintIssues, spellCheckIssues, spellCheckEnabled, onSpellCheckToggle, spellCheckLoading, collabEnabled, collabResumeId, collabUser, collabRole, onPresenceChange, onChatTransport, suggestionPresence, onSuggestionPresenceChange, suggestionDecisions, onSuggestionDecisionsChange, trackedChanges, onTrackedChangesUpdate, confidenceScore, confidenceScoreLoading, onConfidenceBadgeClick, commentedLines, onCommentIconClick },
    ref
  ) {
    const editorRef = useRef<any>(null)
    const onEditorReadyRef = useRef(onEditorReady)
    onEditorReadyRef.current = onEditorReady
    const keybindingStatusRef = useRef<HTMLSpanElement>(null)
    const keybindingAdapterRef = useRef<EditorKeybindingAdapter | null>(null)
    const keybindingActivationRef = useRef(0)
    const [keybindingMode, setKeybindingMode] = useState<EditorKeybindingMode>(() => {
      if (typeof window === 'undefined') return 'standard'
      return parseEditorKeybindingMode(localStorage.getItem('latexy_editor_keybindings'))
    })
    const [richHover, setRichHover] = useState<{
      preview: LatexHoverPreview
      left: number
      top: number
    } | null>(null)
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
    const onShowDocsRef = useRef(onShowDocs)
    onShowDocsRef.current = onShowDocs
    const spellCheckIssuesRef = useRef(spellCheckIssues)
    spellCheckIssuesRef.current = spellCheckIssues
    const onPresenceChangeRef = useRef(onPresenceChange)
    onPresenceChangeRef.current = onPresenceChange
    const onChatTransportRef = useRef(onChatTransport)
    onChatTransportRef.current = onChatTransport
    const onSuggestionPresenceChangeRef = useRef(onSuggestionPresenceChange)
    onSuggestionPresenceChangeRef.current = onSuggestionPresenceChange
    const onSuggestionDecisionsChangeRef = useRef(onSuggestionDecisionsChange)
    onSuggestionDecisionsChangeRef.current = onSuggestionDecisionsChange
    const suggestionDecisionsRef = useRef<SuggestionDecision[]>(suggestionDecisions ?? [])
    suggestionDecisionsRef.current = suggestionDecisions ?? []
    const suggestionPresenceRef = useRef<SuggestionPresence>(suggestionPresence ?? { items: [], decisions: [] })
    suggestionPresenceRef.current = suggestionPresence ?? { items: [], decisions: [] }
    const onTrackedChangesUpdateRef = useRef(onTrackedChangesUpdate)
    onTrackedChangesUpdateRef.current = onTrackedChangesUpdate
    const bibliographyBibTeXRef = useRef(bibliographyBibTeX)
    bibliographyBibTeXRef.current = bibliographyBibTeX

    // Collaboration permissions: locked either by a known non-editing role or
    // by a permission-denied / revocation frame from the relay.
    const [collabLocked, setCollabLocked] = useState(false)
    const collabRoleReadOnly = !!collabRole && !COLLAB_EDIT_ROLES.has(collabRole)
    const collabReadOnly = collabLocked || collabRoleReadOnly
    const collabReadOnlyRef = useRef(collabReadOnly)
    collabReadOnlyRef.current = collabReadOnly

    // Y.js collab refs — cleaned up on unmount
    const ydocRef = useRef<any>(null)
    const suggestionYTextRef = useRef<any>(null)
    const providerRef = useRef<any>(null)
    const suggestionDecisionsMapRef = useRef<any>(null)
    const bindingRef = useRef<any>(null)
    // Track changes refs (Feature 41)
    const trackChangesRef = useRef<TrackChangesHandle | null>(null)
    const trackedChangesDecsRef = useRef<any>(null)
    // Comment gutter refs (Feature 74)
    const commentDecsRef = useRef<any>(null)
    const onCommentIconClickRef = useRef(onCommentIconClick)
    onCommentIconClickRef.current = onCommentIconClick

    // Cleanup Y.js session on unmount
    useEffect(() => {
      return () => {
        keybindingActivationRef.current += 1
        keybindingAdapterRef.current?.dispose()
        keybindingAdapterRef.current = null
        trackChangesRef.current?.cleanup()
        trackChangesRef.current = null
        bindingRef.current?.destroy()
        providerRef.current?.destroy()
        ydocRef.current?.destroy()
        bindingRef.current = null
        providerRef.current = null
        ydocRef.current = null
        suggestionYTextRef.current = null
        onChatTransportRef.current?.(null)
      }
    }, [])

    // Suggestions use awareness only; they are ephemeral metadata and never
    // enter the Y.Text document. The existing authenticated provider remains
    // the sole collaboration socket.
    useEffect(() => {
      providerRef.current?.awareness?.setLocalStateField('suggestions', suggestionPresenceRef.current)
    }, [suggestionPresence])

    useEffect(() => {
      const map = suggestionDecisionsMapRef.current
      // The relay only permits document writes from owner/editor roles. This
      // map is a notification mirror; the server endpoint remains authoritative.
      if (!map || (collabRole !== 'owner' && collabRole !== 'editor')) return
      const prefix = providerRef.current?.awareness?.clientID == null ? '' : `${providerRef.current.awareness.clientID}:`
      for (const decision of suggestionDecisionsRef.current.slice(-50)) {
        const id = /^[a-zA-Z0-9_-]{1,32}:/.test(decision.id) ? decision.id : `${prefix}${decision.id}`
        if (id) map.set(id, { ...decision, id })
      }
      const retained = new Set(keepLatestSuggestionDecisions(Array.from(map.values())).map((decision) => decision.id))
      for (const [key, value] of Array.from(map.entries()) as Array<[string, unknown]>) {
        const decision = sanitizeSuggestionDecision(value)
        if (!decision || !retained.has(decision.id)) map.delete(key)
      }
    }, [collabRole, suggestionDecisions])

    async function applyKeybindingMode(editor: MonacoEditorInstance, mode: EditorKeybindingMode) {
      const activation = ++keybindingActivationRef.current
      keybindingAdapterRef.current?.dispose()
      keybindingAdapterRef.current = null
      try {
        const adapter = await activateEditorKeybindings(mode, editor, keybindingStatusRef.current)
        if (activation !== keybindingActivationRef.current || editorRef.current !== editor) {
          adapter.dispose()
          return
        }
        keybindingAdapterRef.current = adapter
        if (isEditorTestRuntime() && typeof window !== 'undefined') {
          ;(window as LatexyMonacoTestWindow).__latexyKeybindingMode = mode
        }
      } catch (error) {
        console.error(`[LaTeXEditor] Failed to activate ${mode} keybindings`, error)
        if (keybindingStatusRef.current) keybindingStatusRef.current.textContent = 'KEYBINDINGS ERROR'
        toast.error(`${mode === 'vim' ? 'Vim' : 'Emacs'} keybindings could not be loaded`)
      }
    }

    useEffect(() => {
      localStorage.setItem('latexy_editor_keybindings', keybindingMode)
      const editor = editorRef.current as MonacoEditorInstance | null
      if (editor) void applyKeybindingMode(editor, keybindingMode)
    // The active editor is intentionally read from its ref; mode is the user-controlled trigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [keybindingMode])

    const [searchPanelOpen, setSearchPanelOpen] = useState(false)

    // Follow the app's light/dark mode so the editor matches the page instead
    // of being permanently dark. Reads the `data-mode` attribute the
    // ThemeProvider stamps on <html> and reacts to toggles.
    // Matches the token CSS: dark ONLY when data-mode="dark"; anything else
    // (light, or the attribute missing) resolves to the light editor theme.
    const [editorTheme, setEditorTheme] = useState<'latexy-dark' | 'latexy-light'>('latexy-light')
    useEffect(() => {
      const read = () =>
        setEditorTheme(document.documentElement.getAttribute('data-mode') === 'dark' ? 'latexy-dark' : 'latexy-light')
      read()
      const obs = new MutationObserver(read)
      obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] })
      return () => obs.disconnect()
    }, [])

    function handlePresetSelect(preset: LatexSearchPreset) {
      const editor = editorRef.current
      if (!editor) return

      // Prefer the public actions.findWithArgs action (registered in Monaco 0.34+,
      // stable in 0.55). It accepts searchString + isRegex directly without
      // touching any internal findController methods.
      if (editor.getAction('editor.actions.findWithArgs')) {
        editor.trigger('keyboard', 'editor.actions.findWithArgs', {
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
    const renderedWordCount = useMemo(
      () => renderedText === null || renderedText === undefined
        ? null
        : countRenderedWords(renderedText),
      [renderedText],
    )

    useImperativeHandle(ref, () => ({
      setValue(content: string, opts?: { reveal?: boolean }) {
        const model = editorRef.current?.getModel()
        if (!model) return
        model.setValue(content)
        // Streaming updates pass reveal:false so the viewport stays put instead
        // of yanking to the last line on every token.
        if (opts?.reveal !== false) {
          editorRef.current?.revealLine(model.getLineCount())
        }
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
        onChange(editor.getValue())
      },
      applyRewrite(startLine: number, startColumn: number, endLine: number, endColumn: number, text: string) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return
        editor.executeEdits('writing-assistant', [{
          range: new monaco.Range(startLine, startColumn, endLine, endColumn),
          text,
        }])
        onChange(editor.getValue())
        editor.focus()
      },
      applySuggestionResult(expectedContent: string, resultContent: string) {
        const editor = editorRef.current
        if (!editor) return false
        const yText = suggestionYTextRef.current
        const ydoc = ydocRef.current
        const current = yText ? yText.toString() : editor.getValue()
        // The server's CAS was against expectedContent. Do not overwrite a
        // newer local/collaborative edit while reconciling its committed result.
        if (current !== expectedContent) return false
        if (yText && ydoc) {
          ydoc.transact(() => {
            if (yText.toString() !== expectedContent) return
            yText.delete(0, yText.length)
            if (resultContent) yText.insert(0, resultContent)
          }, 'suggestion-authoritative')
        } else {
          const model = editor.getModel()
          if (!model || model.getValue() !== expectedContent) return false
          model.setValue(resultContent)
        }
        onChange(editor.getValue())
        editor.focus()
        return true
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
        onChange(editor.getValue())
        editor.focus()
      },
      insertAtCursor(text: string) {
        const editor = editorRef.current
        const monaco = monacoRef.current
        if (!editor || !monaco) return false
        const position = editor.getPosition()
        if (!position) return false
        editor.executeEdits('insert-bibtex', [{
          range: new monaco.Range(
            position.lineNumber, position.column,
            position.lineNumber, position.column,
          ),
          text,
        }])
        // @monaco-editor/react does not consistently forward programmatic
        // executeEdits through its onChange prop. Synchronize the controlled
        // parent explicitly or its next render restores the pre-insert value.
        onChange(editor.getValue())
        editor.focus()
        return true
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
      rejectTrackedChange: (id: string) => {
        if (trackChangesRef.current?.rejectChange(id) === false) {
          toast.error('This change overlaps newer edits and could not be rejected safely')
        }
      },
      acceptAllTrackedChanges: () => { trackChangesRef.current?.acceptAll() },
      rejectAllTrackedChanges: () => {
        if (trackChangesRef.current?.rejectAll() === false) {
          toast.error('Some changes overlap newer edits and were left pending')
        }
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

      // Monaco builds without the CodeLens refresh command should not emit a runtime error.
      const supportsCodeLensRefresh = editor
        .getSupportedActions()
        .some((action: { id: string }) => action.id === 'editor.action.refreshCodeLenses')
      if (supportsCodeLensRefresh) {
        editor.trigger('latexy', 'editor.action.refreshCodeLenses', null)
      }
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

    // Comment gutter decorations (Feature 74)
    useEffect(() => {
      const editor = editorRef.current
      const monaco = monacoRef.current
      if (!editor || !monaco) return

      if (!commentDecsRef.current) {
        commentDecsRef.current = editor.createDecorationsCollection([])
      }
      if (!commentedLines || commentedLines.length === 0) {
        commentDecsRef.current.set([])
        return
      }
      const decorations = commentedLines.map((line) => ({
        range: new monaco.Range(line, 1, line, 1),
        options: {
          glyphMarginClassName: 'comment-gutter-icon',
          glyphMarginHoverMessage: { value: 'Click to view comments on this line' },
        },
      }))
      commentDecsRef.current.set(decorations)
    }, [commentedLines])

    // Comment glyph click handler (Feature 74) — registered once on mount
    useEffect(() => {
      const editor = editorRef.current
      const monaco = monacoRef.current
      if (!editor || !monaco) return
      const disposable = editor.onMouseDown((e: any) => {
        if (
          e.target.type === monaco.editor.MouseTargetType.GUTTER_GLYPH_MARGIN &&
          onCommentIconClickRef.current
        ) {
          onCommentIconClickRef.current(e.target.position?.lineNumber ?? 0)
        }
      })
      return () => disposable.dispose()
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [editorRef.current, monacoRef.current])

    // Keep the Monaco model in sync with fetched resume content until the
    // collaborative Y.js document has completed its initial sync and binding.
    useEffect(() => {
      if (!collabEnabled || bindingRef.current) return
      const editor = editorRef.current
      const model = editor?.getModel()
      if (!model) return
      if (model.getValue() === value) return
      model.setValue(value)
    }, [collabEnabled, value])

    // Cleanup on unmount
    useEffect(() => {
      return () => {
        onEditorReadyRef.current?.(null)
        clearMonacoTestHook(editorRef.current)
        for (const d of disposablesRef.current) d?.dispose?.()
        disposablesRef.current = []
        editorRef.current = null
        monacoRef.current = null
      }
    }, [])

    const handleEditorDidMount: OnMount = async (editor, monaco) => {
      editorRef.current = editor
      monacoRef.current = monaco
      onEditorReadyRef.current?.(editor)
      exposeMonacoTestHook(editor, monaco)
      void applyKeybindingMode(editor, keybindingMode)
      disposablesRef.current.push({ dispose: () => clearMonacoTestHook(editor) })
      const mountedModel = editor.getModel()
      if (mountedModel) {
        completionBibliographyByModel.set(mountedModel, () => bibliographyBibTeXRef.current)
        disposablesRef.current.push({
          dispose: () => completionBibliographyByModel.delete(mountedModel),
        })
      }

      let richHoverTimer: ReturnType<typeof setTimeout> | null = null
      const clearRichHover = () => {
        if (richHoverTimer) clearTimeout(richHoverTimer)
        richHoverTimer = null
        setRichHover(null)
      }
      const hoverMoveDisposable = editor.onMouseMove((event) => {
        if (richHoverTimer) clearTimeout(richHoverTimer)
        const model = editor.getModel()
        const position = event.target.position
        if (!model || !position) {
          setRichHover(null)
          return
        }
        richHoverTimer = setTimeout(() => {
          if (editor.getModel() !== model) return
          const preview = buildLatexHoverPreview(
            model.getValue(),
            completionBibliographyByModel.get(model)?.() ?? '',
            model.getOffsetAt(position),
          )
          if (!preview) {
            setRichHover(null)
            return
          }
          const visible = editor.getScrolledVisiblePosition(position)
          if (!visible) return
          const layout = editor.getLayoutInfo()
          setRichHover({
            preview,
            left: Math.max(8, Math.min(visible.left + 28, layout.width - 370)),
            top: visible.top + visible.height + 8,
          })
        }, 250)
      })
      const hoverLeaveDisposable = editor.onMouseLeave(clearRichHover)
      const hoverScrollDisposable = editor.onDidScrollChange(clearRichHover)
      disposablesRef.current.push(hoverMoveDisposable, hoverLeaveDisposable, hoverScrollDisposable, {
        dispose: clearRichHover,
      })

      // Register against the real Monaco instance. A mount-only React effect can
      // run before the dynamically imported editor exists and silently skip this
      // listener for the component's entire lifetime.
      let autoCompileTimer: ReturnType<typeof setTimeout> | null = null
      const autoCompileDisposable = editor.onDidChangeModelContent(() => {
        if (!autoCompileRef.current) return
        if (autoCompileTimer) clearTimeout(autoCompileTimer)
        autoCompileTimer = setTimeout(() => {
          const model = editor.getModel()
          if (!model) return
          const content = editor.getValue()
          if (!content.trim()) return
          autoCompileRef.current?.(content)
        }, 2000)
      })
      disposablesRef.current.push(autoCompileDisposable)
      disposablesRef.current.push({
        dispose: () => {
          if (autoCompileTimer) clearTimeout(autoCompileTimer)
        },
      })

      // Always (re)define themes before applying one — never behind the language guard.
      defineLatexyThemes(monaco)

      if (collabEnabled && value && !editor.getValue()) {
        editor.setValue(value)
      }

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

          // Citation/reference arguments — source-local plus the saved references.bib.
          const argument = matchLatexArgumentCompletion(text)
          if (argument) {
            const allText = model.getValue()
            const candidates = argument.kind === 'citation'
              ? extractCitationKeys(allText, completionBibliographyByModel.get(model)?.() ?? '')
              : extractLatexLabels(allText)
            for (const candidate of candidates) {
              if (
                candidate.startsWith(argument.partial)
                && !argument.alreadyUsed.has(candidate)
              ) {
                suggestions.push({
                  label: candidate,
                  kind: argument.kind === 'citation'
                    ? monaco.languages.CompletionItemKind.Reference
                    : monaco.languages.CompletionItemKind.Variable,
                  insertText: candidate,
                  range: {
                    startLineNumber: position.lineNumber,
                    startColumn: position.column - argument.partial.length,
                    endLineNumber: position.lineNumber,
                    endColumn: position.column,
                  },
                  detail: argument.kind === 'citation' ? 'Bibliography key' : 'Document label',
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
      // Language providers are Monaco-global and guarded by
      // _latexLanguageRegistered. Disposing them with the first editor instance
      // would permanently remove autocomplete from later editor mounts.
      void completionDisposable

      // ── Folding range provider ─────────────────────────────────────
      const foldingDisposable = monaco.languages.registerFoldingRangeProvider('latex', {
        provideFoldingRanges(model: import('monaco-editor').editor.ITextModel) {
          return buildLatexFoldingRanges(model.getValue()).map((range) => ({
            ...range,
            kind: monaco.languages.FoldingRangeKind.Region,
          }))
        },
      })
      void foldingDisposable

      // ── Hover provider (show command description) ──────────────────
      const hoverDisposable = monaco.languages.registerHoverProvider('latex', {
        provideHover(model: import('monaco-editor').editor.ITextModel, position: import('monaco-editor').Position) {
          const preview = buildLatexHoverPreview(
            model.getValue(),
            completionBibliographyByModel.get(model)?.() ?? '',
            model.getOffsetAt(position),
          )
          if (preview) {
            const start = model.getPositionAt(preview.start)
            const end = model.getPositionAt(preview.end)
            const range = new monaco.Range(start.lineNumber, start.column, end.lineNumber, end.column)
            if (preview.kind === 'math') {
              return {
                range,
                contents: [
                  { value: '**Rendered math**' },
                  { value: `Preview: ${markdownCodeSpan(preview.latex)}` },
                  { value: '_Point at the formula for the visual KaTeX preview._' },
                ],
              }
            }
            if (preview.kind === 'graphic') {
              return {
                range,
                contents: [
                  { value: '**Graphic include**' },
                  { value: `File: ${markdownCodeSpan(preview.filename)}` },
                  ...(preview.options ? [{ value: `Options: ${markdownCodeSpan(preview.options)}` }] : []),
                  { value: '_The current single-source workspace has no uploaded asset to thumbnail; the compiled PDF remains authoritative._' },
                ],
              }
            }
            const contents: Array<{ value: string }> = [{ value: '**Citation preview**' }]
            for (const citation of preview.citations.slice(0, 5)) {
              const key = citation.key
              const title = citation.title?.replace(/[\\`*_{}[\]()#+.!|>-]/g, '\\$&')
              const author = citation.author?.replace(/[\\`*_{}[\]()#+.!|>-]/g, '\\$&')
              const year = citation.year?.replace(/[\\`*_{}[\]()#+.!|>-]/g, '\\$&')
              contents.push({
                value: [
                  `${markdownCodeSpan(key)}${citation.type ? ` · ${citation.type}` : ''}`,
                  title ? `**${title}**` : '_No saved bibliography metadata_',
                  [author, year].filter(Boolean).join(' · '),
                ].filter(Boolean).join('  \n'),
              })
            }
            return { range, contents }
          }

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
      void hoverDisposable

        _latexLanguageRegistered = true
      } // end !_latexLanguageRegistered
      monaco.editor.setTheme(
        document.documentElement.getAttribute('data-mode') === 'dark' ? 'latexy-dark' : 'latexy-light'
      )

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

      // ── Show Documentation context menu action ────────────────────
      const docsActionDisposable = editor.addAction({
        id: 'latexy.showDocs',
        label: '📖 Show Documentation',
        contextMenuGroupId: 'navigation',
        contextMenuOrder: 2.0,
        run: (ed) => {
          const position = ed.getPosition()
          if (!position) return
          const model = ed.getModel()
          if (!model) return
          const lineContent = model.getLineContent(position.lineNumber)
          const col0 = position.column - 1  // 0-based column

          // Case 1: cursor is on an env name inside \begin{...} or \end{...}
          // More precise: check if cursor is inside braces of \begin{} or \end{}
          const envPattern = /\\(?:begin|end)\{(\w+\*?)\}/g
          let envMatch: RegExpExecArray | null
          let resolvedEnvCmd: string | null = null
          while ((envMatch = envPattern.exec(lineContent)) !== null) {
            const start = envMatch.index + envMatch[0].indexOf('{') + 1
            const end = start + envMatch[1].length
            if (col0 >= start && col0 <= end) {
              resolvedEnvCmd = `\\begin{${envMatch[1]}}`
              break
            }
          }

          if (resolvedEnvCmd) {
            onShowDocsRef.current?.(resolvedEnvCmd)
            return
          }

          // Case 2: cursor is on a regular \command
          const wordRange = model.getWordAtPosition(position)
          if (!wordRange) return
          const charBefore = lineContent[wordRange.startColumn - 2]
          if (charBefore !== '\\') return
          const cmd = '\\' + wordRange.word
          onShowDocsRef.current?.(cmd)
        },
      })
      if (docsActionDisposable) disposablesRef.current.push(docsActionDisposable)

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
          const initialTicket = await apiClient.createWebSocketTicket('collab', collabResumeId)

          const provider = new WebsocketProvider(
            getCollabWebSocketUrl(),
            collabResumeId,
            ydoc,
            {
              params: {
                ticket: initialTicket.ticket,
                name: collabUser.name,
                color: collabUser.color,
              },
            },
          )

          // The relay refuses document frames from viewers / commenters, so
          // lock the editor rather than letting edits apply locally and then
          // silently disappear on reload.
          const lockCollabEditing = (message: string) => {
            if (collabReadOnlyRef.current) return
            collabReadOnlyRef.current = true
            setCollabLocked(true)
            toast.error(message)
          }

          provider.messageHandlers[MSG_PERMISSION_DENIED] = (
            _encoder: unknown,
            decoder: { arr: Uint8Array; pos: number },
          ) => {
            let code = 'read_only'
            let message = 'You do not have permission to edit this document'
            try {
              const parsed = JSON.parse(new TextDecoder().decode(readVarBuffer(decoder)))
              if (parsed?.code) code = String(parsed.code)
              if (parsed?.message) message = String(parsed.message)
            } catch {
              /* keep defaults */
            }
            // Chat uses this protocol extension for its own rate-limit and
            // live-revocation notices. The chat transport observes the same
            // frame; do not turn a chat-only denial into an editor lock.
            if (code === 'chat_rate_limited' || code === 'chat_forbidden') return
            // A role change is not a permission loss: the relay drops the socket
            // so the client re-handshakes with the new role. Locking here would
            // undo a promotion — the user would come back with less access than
            // they started with — so leave the buffer editable and let the
            // reconnect re-authorise.
            if (code === 'role_changed') {
              toast.info(message || 'Your access level changed — reconnecting')
              return
            }
            lockCollabEditing(
              code === 'access_revoked'
                ? `Collaboration access revoked — ${message}`
                : `Read-only — ${message}`,
            )
          }

          // Handshake rejections: stop y-websocket's reconnect loop instead of hammering
          // the auth + permission queries forever. Losing the relay is NOT the same as
          // losing edit rights — only 4003 (access revoked) makes the buffer read-only;
          // everything else leaves Monaco editable and falls back to REST autosave.
          let transientCollabRejections = 0
          let collabGiveUpNotified = false
          let ticketRefreshInFlight = false
          provider.on('connection-close', (event: CloseEvent | null) => {
            // Awareness is ephemeral; never retain peer suggestions after a
            // disconnected session until a fresh awareness snapshot arrives.
            onSuggestionPresenceChangeRef.current?.([])
            const code = event?.code
            const action = classifyCollabClose(code, transientCollabRejections)
            // provider.disconnect() clears shouldConnect before it emits close;
            // that is intentional teardown and must not resurrect the socket.
            if (action === 'ignore' && !provider.shouldConnect) return
            // The handshake consumes its ticket. Stop y-websocket's built-in
            // reconnect before it can replay that spent credential; a retry
            // resumes only after authenticated HTTP mints a fresh one.
            provider.shouldConnect = false
            if (action === 'retry' || action === 'ignore') {
              if (action === 'retry') transientCollabRejections += 1
              if (ticketRefreshInFlight) return
              ticketRefreshInFlight = true
              void apiClient.createWebSocketTicket('collab', collabResumeId)
                .then(({ ticket }) => {
                  provider.params.ticket = ticket
                  provider.shouldConnect = true
                  provider.connect()
                })
                .catch(() => {
                  if (!collabGiveUpNotified) {
                    collabGiveUpNotified = true
                    toast.warning('Live collaboration could not reconnect — your edits are still saved')
                  }
                })
                .finally(() => {
                  ticketRefreshInFlight = false
                })
              return
            }
            // Deferred: y-websocket has not finished tearing this socket down yet.
            setTimeout(() => {
              try {
                provider.disconnect()
              } catch {
                /* already gone */
              }
            }, 0)
            if (action === 'lock') {
              lockCollabEditing('Collaboration access revoked — this document is now read-only')
              return
            }
            if (collabGiveUpNotified) return
            collabGiveUpNotified = true
            toast.warning(
              code === 4001
                ? 'Live collaboration disconnected — your edits are still saved, reload to reconnect'
                : 'Live collaboration is unavailable for this document — your edits are still saved',
            )
          })

          const yText = ydoc.getText('content')
          suggestionYTextRef.current = yText
          const suggestionDecisionsMap = ydoc.getMap('suggestion-decisions')
          suggestionDecisionsMapRef.current = suggestionDecisionsMap
          const emitSuggestionDecisions = () => {
            const allValues = Array.from(suggestionDecisionsMap.values())
            const ownPrefix = `${provider.awareness.clientID}:`
            const decisions = keepLatestSuggestionDecisions(allValues).map((decision) =>
              decision.id.startsWith(ownPrefix) ? { ...decision, id: decision.id.slice(ownPrefix.length) } : decision,
            )
            onSuggestionDecisionsChangeRef.current?.(decisions)
          }
          suggestionDecisionsMap.observe(emitSuggestionDecisions)
          emitSuggestionDecisions()
          const model = editor.getModel()
          if (!model) return

          const bindCollabDocument = () => {
            if (bindingRef.current) return

            const localContent = model.getValue()
            // Seeding is a document write: read-only peers must not attempt it.
            if (!collabReadOnlyRef.current && yText.length === 0 && localContent) {
              ydoc.transact(() => {
                yText.insert(0, localContent)
              })
            }

            const binding = new MonacoBinding(yText, model, new Set([editor]), provider.awareness)
            bindingRef.current = binding

            // Track changes (Feature 41)
            trackChangesRef.current?.cleanup()
            trackChangesRef.current = observeChanges(yText, provider, (updatedChanges) => {
              onTrackedChangesUpdateRef.current?.(updatedChanges)
            }, Y)
          }

          provider.awareness.setLocalStateField('user', {
            name: collabUser.name,
            color: collabUser.color,
          })
          provider.awareness.setLocalStateField('suggestions', suggestionPresenceRef.current)

          // Broadcast presence changes to parent
          provider.awareness.on('change', () => {
            const states = provider.awareness.getStates()
            const others = Array.from(states.entries())
              .filter(([id]: [number, any]) => id !== provider.awareness.clientID)
              .map(([, s]: [number, any]) => s?.user)
              .filter(Boolean)
            onPresenceChangeRef.current?.(others)
            const peerSuggestions = Array.from(states.entries())
              .filter(([id]: [number, any]) => id !== provider.awareness.clientID)
              .map(([id, state]: [number, any]) => namespaceSuggestionPresence(sanitizeSuggestionPresence(state?.suggestions), id))
              .filter((payload) => payload.items.length > 0 || payload.decisions.length > 0)
            onSuggestionPresenceChangeRef.current?.(peerSuggestions)
          })

          // Seed the Y.Doc with the current value once synced (if remote doc is empty)
          const handleSync = (isSynced: boolean) => {
            if (!isSynced) return
            bindCollabDocument()
            provider.off('sync', handleSync)
          }
          provider.on('sync', handleSync)
          if (provider.synced) bindCollabDocument()

          ydocRef.current = ydoc
          providerRef.current = provider
          onChatTransportRef.current?.(createYWebsocketChatTransport(provider))
        } catch (err) {
          console.warn('[LaTeXEditor] Y.js collab init failed:', err)
        }
      }

    }

    return (
      <div className="flex h-full flex-col">
        <div className="relative min-h-0 flex-1">
          <LaTeXSearchPanel
            presets={LATEX_SEARCH_PRESETS}
            isOpen={searchPanelOpen}
            onToggle={() => setSearchPanelOpen((v) => !v)}
            onClose={() => setSearchPanelOpen(false)}
            onPresetSelect={handlePresetSelect}
          />
          <MonacoEditor
              height="100%"
              defaultLanguage="latex"
              theme={editorTheme}
              // A collaborative editor is uncontrolled once Y.js binds it, but
              // it must still start with the fetched REST content. Mounting
              // Monaco with an empty model can emit onChange('') before the
              // async collaboration imports finish, erasing the parent buffer.
              {...(collabEnabled ? { defaultValue: value } : { value })}
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
                // Keep Monaco's native multi-cursor contract explicit so future
                // option presets cannot silently replace Option/Alt-click.
                multiCursorModifier: 'alt',
                multiCursorPaste: 'spread',
                renderLineHighlight: 'line',
                cursorBlinking: 'smooth',
                cursorSmoothCaretAnimation: 'on',
                smoothScrolling: true,
                contextmenu: true,
                readOnly: readOnly || collabReadOnly,
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
          {richHover && <LatexRichHoverCard {...richHover} />}
          {!value && (
            <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center px-6 text-center">
              <p className="text-sm uppercase tracking-[0.14em] text-fg-3">Empty document</p>
              <p className="mt-2 max-w-sm text-xs text-fg-3">
                {hideEmptyAction ? 'Content will appear here once generated.' : 'Start writing or use a sample template.'}
              </p>
              {!hideEmptyAction && (
                <button
                  onClick={() => onChange(BLANK_RESUME_TEMPLATE)}
                  className="pointer-events-auto mt-4 rounded-[var(--radius-md)] border border-line bg-surface px-4 py-2 text-xs font-medium text-fg-2 transition hover:bg-surface-2"
                >
                  Insert Sample Resume
                </button>
              )}
            </div>
          )}
        </div>

        {/* Status bar */}
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t border-line bg-bg px-3 py-1 text-[12px] uppercase tracking-[0.12em]">
          <span className="text-fg-3">
            {readOnly
              ? 'Read-only — job running'
              : collabReadOnly
                ? 'Read-only — no edit access'
                : 'LaTeX editor'}
          </span>
          <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 text-fg-3">
            <label className="flex items-center gap-1 normal-case tracking-normal" title="Editor keybinding mode">
              <span className="sr-only">Editor keybindings</span>
              <select
                aria-label="Editor keybindings"
                value={keybindingMode}
                onChange={(event) => setKeybindingMode(parseEditorKeybindingMode(event.target.value))}
                className="rounded border border-line bg-surface px-1 py-0.5 text-[10px] uppercase text-fg-2 outline-none focus:border-accent"
              >
                <option value="standard">Standard</option>
                <option value="vim">Vim</option>
                <option value="emacs">Emacs</option>
              </select>
              <span ref={keybindingStatusRef} aria-live="polite" className="min-w-0 max-w-32 truncate text-[9px] text-fg-3" />
            </label>
            {onAutoCompile && (
              <span className="flex items-center gap-1 text-[12px] text-accent-strong">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                Auto
              </span>
            )}
            {/* Page count badge — actual (post-compile) or estimated (pre-compile) */}
            {(pageCount !== null && pageCount !== undefined) ? (
              <span
                title={`${warnOnMultiplePages ? 'Resume' : 'Document'} is ${pageCount} page${pageCount === 1 ? '' : 's'}`}
                className={`text-[12px] font-medium px-1.5 py-0.5 rounded-[var(--radius-md)] ${
                  pageCount === 1
                    ? 'text-ok bg-ok/10'
                    : !warnOnMultiplePages
                    ? 'text-fg-2 bg-surface-2'
                    : pageCount === 2
                    ? 'text-warn bg-warn/10'
                    : 'text-err bg-err/10 animate-pulse'
                }`}
              >
                {pageCount} {pageCount === 1 ? 'page' : 'pages'}{pageCount > 1 && warnOnMultiplePages ? ' ⚠' : ''}
              </span>
            ) : estimatedPageCount !== null ? (
              <span
                title="Estimated page count (compile for exact count)"
                className="text-[12px] text-fg-3 px-1.5"
              >
                ~{estimatedPageCount} {estimatedPageCount === 1 ? 'page' : 'pages'}
              </span>
            ) : null}
            {renderedWordCount !== null && (
              <span
                className="text-[12px] tabular-nums text-fg-3"
                title="Word count from the last compiled PDF text (not LaTeX source tokens)"
              >
                {renderedWordCount.toLocaleString()} rendered {renderedWordCount === 1 ? 'word' : 'words'}
              </span>
            )}
            {onSpellCheckToggle && (
              <button
                onClick={onSpellCheckToggle}
                title={spellCheckEnabled ? 'Spell check on — click to disable' : 'Spell check off — click to enable'}
                className={`flex items-center gap-1 text-[12px] transition ${
                  spellCheckEnabled
                    ? 'text-accent-strong hover:text-accent'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                ABC{spellCheckEnabled ? ' ✓' : ''}
                {spellCheckLoading && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
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
                <span className="flex items-center gap-1 text-[12px] text-fg-3">
                  <span className="h-1.5 w-1.5 animate-spin rounded-full border border-line-2 border-t-transparent" />
                  Quality
                </span>
              ) : confidenceScore != null ? (
                onConfidenceBadgeClick ? (
                  <button
                    type="button"
                    onClick={onConfidenceBadgeClick}
                    title="Resume quality score — click to view details"
                    className={`rounded-[var(--radius-md)] px-1.5 py-0.5 text-[12px] font-medium transition-colors cursor-pointer hover:brightness-110 ${
                      confidenceScore >= 80
                        ? 'text-ok bg-ok/10'
                        : confidenceScore >= 60
                          ? 'text-warn bg-warn/10'
                          : 'text-err bg-err/10'
                    }`}
                  >
                    Q {confidenceScore}
                  </button>
                ) : (
                  <span
                    title="Resume quality score"
                    className={`rounded-[var(--radius-md)] px-1.5 py-0.5 text-[12px] font-medium ${
                      confidenceScore >= 80
                        ? 'text-ok bg-ok/10'
                        : confidenceScore >= 60
                          ? 'text-warn bg-warn/10'
                          : 'text-err bg-err/10'
                    }`}
                  >
                    Q {confidenceScore}
                  </span>
                )
              ) : null
            )}
            <span>{value.length.toLocaleString()} chars</span>
            <span className="hidden text-fg-3 sm:inline">
              {[onSave && '⌘S save', onCompile && '⌘↵ compile', '⌘⇧H presets'].filter(Boolean).join(' · ')}
            </span>
          </div>
        </div>
      </div>
    )
  }
)

export default LaTeXEditor
