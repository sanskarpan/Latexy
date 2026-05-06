'use client'

/**
 * Mobile Editor (Feature 79E).
 *
 * A lightweight CodeMirror-based editor designed for mobile browsers.
 * Replaces the Monaco editor on screens ≤ 768 px wide.
 *
 * Implements the full LaTeXEditorRef interface (with stubs for Monaco-
 * specific methods) so it is drop-in compatible with the existing
 * editorRef throughout the edit page.
 *
 * Features:
 *  - Virtual-keyboard-aware height (visualViewport API)
 *  - Minimal toolbar strip for common LaTeX commands
 *  - Full-screen by default (no split-pane)
 */

import {
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  forwardRef,
} from 'react'
import { EditorView, keymap, lineNumbers } from '@codemirror/view'
import { EditorState } from '@codemirror/state'
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands'
import { markdown } from '@codemirror/lang-markdown'
import { Play, Save, AlignLeft, Bold, Italic, List } from 'lucide-react'
import type { LaTeXEditorRef } from '@/components/LaTeXEditor'

interface MobileEditorProps {
  value: string
  onChange: (value: string) => void
  onSave?: () => void
  onCompile?: () => void
}

const darkTheme = EditorView.theme(
  {
    '&': {
      backgroundColor: '#09090b',
      color: '#e4e4e7',
      height: '100%',
      fontSize: '14px',
    },
    '.cm-content': {
      padding: '8px 0',
      fontFamily: "ui-monospace, 'Cascadia Code', monospace",
    },
    '.cm-gutters': {
      backgroundColor: '#09090b',
      borderRight: '1px solid rgba(255,255,255,0.06)',
      color: '#52525b',
    },
    '.cm-lineNumbers .cm-gutterElement': {
      minWidth: '2.5em',
      paddingRight: '0.5em',
    },
    '.cm-cursor': { borderLeftColor: '#a855f7' },
    '.cm-selectionBackground': {
      backgroundColor: 'rgba(168,85,247,0.15) !important',
    },
    '.cm-activeLine': { backgroundColor: 'rgba(255,255,255,0.03)' },
    '.cm-activeLineGutter': { backgroundColor: 'rgba(168,85,247,0.08)' },
    '.cm-line': { padding: '0 8px' },
    '&.cm-focused .cm-cursor': { borderLeftColor: '#a855f7' },
  },
  { dark: true },
)

const TOOLBAR_ITEMS = [
  { icon: Bold, label: 'Bold', insert: '\\textbf{}', cursorOffset: -1 },
  { icon: Italic, label: 'Italic', insert: '\\textit{}', cursorOffset: -1 },
  { icon: List, label: 'Bullet', insert: '\\item ', cursorOffset: 0 },
  { icon: AlignLeft, label: 'Section', insert: '\\section{}', cursorOffset: -1 },
]

const MobileEditor = forwardRef<LaTeXEditorRef, MobileEditorProps>(
  function MobileEditor({ value, onChange, onSave, onCompile }, ref) {
    const containerRef = useRef<HTMLDivElement>(null)
    const viewRef = useRef<EditorView | null>(null)
    const onChangeRef = useRef(onChange)
    onChangeRef.current = onChange

    // Implement the full LaTeXEditorRef interface so this is drop-in compatible
    useImperativeHandle(ref, () => ({
      getValue: () => viewRef.current?.state.doc.toString() ?? '',
      setValue: (val: string) => {
        if (!viewRef.current) return
        viewRef.current.dispatch({
          changes: { from: 0, to: viewRef.current.state.doc.length, insert: val },
        })
      },
      insertAtCursor: (text: string) => {
        if (!viewRef.current) return
        const { from } = viewRef.current.state.selection.main
        viewRef.current.dispatch({
          changes: { from, insert: text },
          selection: { anchor: from + text.length },
        })
      },
      // Stubs for Monaco-specific methods (no-ops on mobile)
      highlightLine: () => {},
      applyFix: () => {},
      applyRewrite: () => {},
      applyMultipleRewrites: () => {},
      getCaretPosition: () => null,
      acceptTrackedChange: () => {},
      rejectTrackedChange: () => {},
      acceptAllTrackedChanges: () => {},
      rejectAllTrackedChanges: () => {},
      // MobileEditor has no Monaco instance — return null
      getEditor: () => null,
    }))

    // Initialise the CodeMirror view once on mount
    useEffect(() => {
      if (!containerRef.current) return

      const updateListener = EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChangeRef.current(update.state.doc.toString())
        }
      })

      const state = EditorState.create({
        doc: value,
        extensions: [
          history(),
          lineNumbers(),
          markdown(),
          darkTheme,
          keymap.of([...defaultKeymap, ...historyKeymap]),
          updateListener,
          EditorView.lineWrapping,
        ],
      })

      const view = new EditorView({ state, parent: containerRef.current })
      viewRef.current = view

      return () => {
        view.destroy()
        viewRef.current = null
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []) // intentionally only once

    // Sync external value changes (e.g. AI optimisation result)
    useEffect(() => {
      const view = viewRef.current
      if (!view) return
      const current = view.state.doc.toString()
      if (current !== value) {
        view.dispatch({
          changes: { from: 0, to: current.length, insert: value },
        })
      }
    }, [value])

    // Virtual-keyboard-aware height via visualViewport API
    useEffect(() => {
      const vv = window.visualViewport
      if (!vv) return
      const adjust = () => {
        if (containerRef.current) {
          containerRef.current.style.height = `${vv.height - 44}px` // 44px toolbar
        }
      }
      vv.addEventListener('resize', adjust)
      adjust()
      return () => vv.removeEventListener('resize', adjust)
    }, [])

    const insertSnippet = useCallback(
      (insert: string, cursorOffset: number) => {
        const view = viewRef.current
        if (!view) return
        const { from } = view.state.selection.main
        view.dispatch({
          changes: { from, insert },
          selection: { anchor: from + insert.length + cursorOffset },
        })
        view.focus()
      },
      [],
    )

    return (
      <div className="flex h-full flex-col bg-[#09090b]">
        {/* Toolbar strip — sits above the virtual keyboard */}
        <div className="flex shrink-0 items-center gap-1 border-b border-white/[0.06] bg-zinc-950 px-2 py-1.5">
          {TOOLBAR_ITEMS.map(({ icon: Icon, label, insert, cursorOffset }) => (
            <button
              key={label}
              title={label}
              onClick={() => insertSnippet(insert, cursorOffset)}
              className="flex h-7 w-7 items-center justify-center rounded text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
            >
              <Icon size={14} />
            </button>
          ))}
          <div className="mx-1 h-4 w-px bg-white/[0.08]" />
          {onCompile && (
            <button
              title="Compile"
              onClick={onCompile}
              className="flex h-7 items-center gap-1 rounded px-2 text-[11px] font-medium text-violet-400 transition hover:bg-violet-500/10"
            >
              <Play size={12} />
              Compile
            </button>
          )}
          {onSave && (
            <button
              title="Save"
              onClick={onSave}
              className="flex h-7 items-center gap-1 rounded px-2 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200"
            >
              <Save size={12} />
              Save
            </button>
          )}
        </div>

        {/* Editor area */}
        <div
          ref={containerRef}
          className="min-h-0 flex-1 overflow-auto"
          style={{ fontFamily: "ui-monospace, 'Cascadia Code', monospace" }}
        />
      </div>
    )
  },
)

export default MobileEditor
