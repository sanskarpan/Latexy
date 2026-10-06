/**
 * MacroPlayer — Feature 83.
 *
 * Executes a recorded Macro against a Monaco editor instance,
 * replaying each MacroAction sequentially.
 */

import type * as Monaco from 'monaco-editor'
import { validateMacroActions, type Macro, type MacroAction } from './macro-types'

type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

export class MacroPlayer {
  /** Replay every action in the macro against the given editor. */
  async play(macro: Macro, editor: IStandaloneCodeEditor): Promise<void> {
    const actions = validateMacroActions(macro.actions)
    const capturedModel = editor.getModel()
    if (!capturedModel) return
    editor.pushUndoStop()
    try {
      for (const action of actions) {
        if (editor.getModel() !== capturedModel) throw new Error('The document changed while the macro was running; nothing further was applied.')
        await this._execute(action, editor, capturedModel)
        if (editor.getModel() !== capturedModel) throw new Error('The document changed while the macro was running; nothing further was applied.')
      }
    } finally {
      editor.pushUndoStop()
    }
  }

  private async _execute(action: MacroAction, editor: IStandaloneCodeEditor, model: Monaco.editor.ITextModel): Promise<void> {
    switch (action.type) {
      case 'insert': {
        const pos = editor.getPosition()
        if (!pos) break
        const range = {
          startLineNumber: pos.lineNumber,
          startColumn: pos.column,
          endLineNumber: pos.lineNumber,
          endColumn: pos.column,
        }
        const offset = model.getOffsetAt(pos)
        this._applyEdit(editor, { range, text: action.text })
        // Monaco columns reset after a newline; calculate the position from
        // the model offset rather than adding the string length to a column.
        editor.setPosition(model.getPositionAt(offset + action.text.length))
        break
      }

      case 'delete': {
        const pos = editor.getPosition()
        if (!pos) break
        if (action.direction === 'backward') {
          const offset = model.getOffsetAt(pos)
          const newOffset = Math.max(0, offset - action.count)
          const startPos = model.getPositionAt(newOffset)
          this._applyEdit(editor, {
            range: {
              startLineNumber: startPos.lineNumber,
              startColumn: startPos.column,
              endLineNumber: pos.lineNumber,
              endColumn: pos.column,
            },
            text: '',
          })
          editor.setPosition(startPos)
        } else {
          const offset = model.getOffsetAt(pos)
          const newOffset = Math.min(model.getValueLength(), offset + action.count)
          const endPos = model.getPositionAt(newOffset)
          this._applyEdit(editor, {
            range: {
              startLineNumber: pos.lineNumber,
              startColumn: pos.column,
              endLineNumber: endPos.lineNumber,
              endColumn: endPos.column,
            },
            text: '',
          })
        }
        break
      }

      case 'move': {
        const pos = editor.getPosition()
        if (!pos) break
        let { lineNumber, column } = pos
        const lineCount = model.getLineCount()
        switch (action.direction) {
          case 'up':
            lineNumber = Math.max(1, lineNumber - action.count)
            break
          case 'down':
            lineNumber = Math.min(lineCount, lineNumber + action.count)
            break
          case 'left':
            column = Math.max(1, column - action.count)
            break
          case 'right': {
            const maxCol = model.getLineMaxColumn(lineNumber)
            column = Math.min(maxCol, column + action.count)
            break
          }
        }
        editor.setPosition({ lineNumber, column })
        break
      }

      case 'select': {
        editor.setSelection({
          startLineNumber: action.startLine,
          startColumn: action.startCol,
          endLineNumber: action.endLine,
          endColumn: action.endCol,
        })
        break
      }

      case 'replace': {
        const fullText = model.getValue()
        if (action.all) {
          const replaced = fullText.split(action.search).join(action.replacement)
          if (replaced !== fullText) {
            const applied = editor.executeEdits('macro', [{ range: model.getFullModelRange(), text: replaced }])
            if (!applied) throw new Error('Macro replacement could not be applied.')
          }
        } else {
          const idx = fullText.indexOf(action.search)
          if (idx !== -1) {
            const start = model.getPositionAt(idx)
            const end = model.getPositionAt(idx + action.search.length)
            this._applyEdit(editor, {
              range: {
                startLineNumber: start.lineNumber,
                startColumn: start.column,
                endLineNumber: end.lineNumber,
                endColumn: end.column,
              },
              text: action.replacement,
            })
          }
        }
        break
      }

      case 'command': {
        const editorAction = editor.getAction(action.monacoCommand)
        if (editorAction) {
          await editorAction.run()
        }
        break
      }
    }
  }

  private _applyEdit(
    editor: IStandaloneCodeEditor,
    edit: { range: { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number }; text: string },
  ): void {
    if (!editor.executeEdits('macro', [edit])) throw new Error('Macro edit could not be applied.')
  }
}
