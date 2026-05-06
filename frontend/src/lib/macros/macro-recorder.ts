/**
 * MacroRecorder — Feature 83.
 *
 * Hooks into Monaco editor events to capture a sequence of MacroActions.
 * Call startRecording(editor) → perform actions → stopRecording() → MacroAction[].
 */

import type * as Monaco from 'monaco-editor'
import type { MacroAction } from './macro-types'

type IDisposable = Monaco.IDisposable
type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

export class MacroRecorder {
  private _recording = false
  private _actions: MacroAction[] = []
  private _disposables: IDisposable[] = []
  private _lastContent = ''
  private _lastPosition: { lineNumber: number; column: number } | null = null

  get isRecording(): boolean {
    return this._recording
  }

  /** Begin capturing editor events. Clears any previous recording. */
  startRecording(editor: IStandaloneCodeEditor): void {
    if (this._recording) return
    this._recording = true
    this._actions = []
    this._lastContent = editor.getValue()
    const pos = editor.getPosition()
    this._lastPosition = pos ? { lineNumber: pos.lineNumber, column: pos.column } : null

    // Capture content changes (insertions / deletions)
    this._disposables.push(
      editor.onDidChangeModelContent((e) => {
        for (const change of e.changes) {
          const { text, rangeLength } = change
          if (text.length > 0 && rangeLength === 0) {
            this._actions.push({ type: 'insert', text })
          } else if (rangeLength > 0 && text.length === 0) {
            this._actions.push({ type: 'delete', direction: 'backward', count: rangeLength })
          } else if (text.length > 0 && rangeLength > 0) {
            // replacement: record as delete then insert
            this._actions.push({ type: 'delete', direction: 'backward', count: rangeLength })
            this._actions.push({ type: 'insert', text })
          }
        }
        this._lastContent = editor.getValue()
      }),
    )

    // Capture cursor position changes (moves)
    this._disposables.push(
      editor.onDidChangeCursorPosition((e) => {
        if (!this._lastPosition) {
          this._lastPosition = { lineNumber: e.position.lineNumber, column: e.position.column }
          return
        }
        const { lineNumber, column } = e.position
        const prev = this._lastPosition

        if (lineNumber !== prev.lineNumber || column !== prev.column) {
          const lineDelta = lineNumber - prev.lineNumber
          const colDelta = column - prev.column
          if (lineDelta !== 0) {
            this._actions.push({
              type: 'move',
              direction: lineDelta > 0 ? 'down' : 'up',
              count: Math.abs(lineDelta),
            })
          } else if (colDelta !== 0) {
            this._actions.push({
              type: 'move',
              direction: colDelta > 0 ? 'right' : 'left',
              count: Math.abs(colDelta),
            })
          }
        }
        this._lastPosition = { lineNumber, column }
      }),
    )

    // Capture selection changes
    this._disposables.push(
      editor.onDidChangeCursorSelection((e) => {
        const { startLineNumber, startColumn, endLineNumber, endColumn } = e.selection
        if (startLineNumber !== endLineNumber || startColumn !== endColumn) {
          this._actions.push({
            type: 'select',
            startLine: startLineNumber,
            startCol: startColumn,
            endLine: endLineNumber,
            endCol: endColumn,
          })
        }
      }),
    )
  }

  /** Stop recording and return the captured action sequence. */
  stopRecording(): MacroAction[] {
    this._recording = false
    this._disposables.forEach((d) => d.dispose())
    this._disposables = []
    return [...this._actions]
  }

  /** Cancel recording without returning actions. */
  cancelRecording(): void {
    this._recording = false
    this._disposables.forEach((d) => d.dispose())
    this._disposables = []
    this._actions = []
  }
}
