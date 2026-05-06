/**
 * Keyboard Macro System — Recorder Engine (Feature 83C)
 *
 * MacroRecorder hooks into Monaco editor events and translates them into a
 * sequence of MacroActions that can later be replayed by MacroPlayer.
 *
 * Usage:
 *   const recorder = new MacroRecorder(editor)
 *   recorder.start()
 *   // ...user types...
 *   const actions = recorder.stop()
 */

import type * as Monaco from 'monaco-editor'
import type { MacroAction } from './macro-types'

export class MacroRecorder {
  private editor: Monaco.editor.IStandaloneCodeEditor
  private actions: MacroAction[] = []
  private recording = false
  private disposables: Monaco.IDisposable[] = []

  constructor(editor: Monaco.editor.IStandaloneCodeEditor) {
    this.editor = editor
  }

  /** Returns true if a recording session is active. */
  get isRecording(): boolean {
    return this.recording
  }

  /**
   * Start recording editor events.
   * Calling start() while already recording is a no-op.
   */
  start(): void {
    if (this.recording) return
    this.actions = []
    this.recording = true
    this._attachListeners()
  }

  /**
   * Stop recording and return the collected actions.
   * The recorder is reset — start() can be called again.
   */
  stop(): MacroAction[] {
    if (!this.recording) return []
    this.recording = false
    this._detachListeners()
    return [...this.actions]
  }

  /** Discard current recording without returning actions. */
  cancel(): void {
    this.recording = false
    this._detachListeners()
    this.actions = []
  }

  // ── Private helpers ──────────────────────────────────────────────────────────

  private _attachListeners(): void {
    // Track the last cursor position so we can emit MoveAction only when
    // the user explicitly moves (not as a by-product of text changes).
    let lastChangeWasEdit = false

    // Content changes → Insert / Delete / Replace
    const contentDisposable = this.editor.onDidChangeModelContent((e) => {
      if (!this.recording) return
      lastChangeWasEdit = true

      for (const change of e.changes) {
        const { range, text } = change
        const isEmpty = text === ''
        const isCollapsed =
          range.startLineNumber === range.endLineNumber &&
          range.startColumn === range.endColumn

        if (isEmpty && !isCollapsed) {
          // Pure deletion
          this.actions.push({
            type: 'delete',
            range: {
              startLineNumber: range.startLineNumber,
              startColumn: range.startColumn,
              endLineNumber: range.endLineNumber,
              endColumn: range.endColumn,
            },
          })
        } else if (!isEmpty && !isCollapsed) {
          // Replace existing range with new text
          this.actions.push({
            type: 'replace',
            range: {
              startLineNumber: range.startLineNumber,
              startColumn: range.startColumn,
              endLineNumber: range.endLineNumber,
              endColumn: range.endColumn,
            },
            text,
          })
        } else if (!isEmpty) {
          // Plain insertion at collapsed cursor
          this.actions.push({ type: 'insert', text })
        }
      }
    })

    // Cursor position changes → MoveAction (only when not caused by typing)
    const positionDisposable = this.editor.onDidChangeCursorPosition((e) => {
      if (!this.recording) return
      if (lastChangeWasEdit) {
        lastChangeWasEdit = false
        return // position change is a side-effect of the edit, skip
      }
      this.actions.push({
        type: 'move',
        position: {
          lineNumber: e.position.lineNumber,
          column: e.position.column,
        },
      })
    })

    // Selection changes → SelectAction (non-collapsed selections only)
    const selectionDisposable = this.editor.onDidChangeCursorSelection((e) => {
      if (!this.recording) return
      const sel = e.selection
      const isCollapsed =
        sel.startLineNumber === sel.endLineNumber &&
        sel.startColumn === sel.endColumn
      if (isCollapsed) return

      this.actions.push({
        type: 'select',
        range: {
          startLineNumber: sel.startLineNumber,
          startColumn: sel.startColumn,
          endLineNumber: sel.endLineNumber,
          endColumn: sel.endColumn,
        },
      })
    })

    this.disposables = [contentDisposable, positionDisposable, selectionDisposable]
  }

  private _detachListeners(): void {
    for (const d of this.disposables) {
      d.dispose()
    }
    this.disposables = []
  }
}
