/**
 * MacroPlayer — Feature 83.
 *
 * Executes a recorded Macro against a Monaco editor instance,
 * replaying each MacroAction sequentially.
 */

import type * as Monaco from 'monaco-editor'
import type { Macro, MacroAction } from './macro-types'

type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

export class MacroPlayer {
  /** Replay every action in the macro against the given editor. */
  async play(macro: Macro, editor: IStandaloneCodeEditor): Promise<void> {
    for (const action of macro.actions) {
      await this._execute(action, editor)
    }
  }

  private async _execute(action: MacroAction, editor: IStandaloneCodeEditor): Promise<void> {
    const model = editor.getModel()
    if (!model) return

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
        model.applyEdits([{ range, text: action.text }])
        // advance cursor past inserted text
        const newCol = pos.column + action.text.length
        editor.setPosition({ lineNumber: pos.lineNumber, column: newCol })
        break
      }

      case 'delete': {
        const pos = editor.getPosition()
        if (!pos) break
        if (action.direction === 'backward') {
          const offset = model.getOffsetAt(pos)
          const newOffset = Math.max(0, offset - action.count)
          const startPos = model.getPositionAt(newOffset)
          model.applyEdits([
            {
              range: {
                startLineNumber: startPos.lineNumber,
                startColumn: startPos.column,
                endLineNumber: pos.lineNumber,
                endColumn: pos.column,
              },
              text: '',
            },
          ])
          editor.setPosition(startPos)
        } else {
          const offset = model.getOffsetAt(pos)
          const newOffset = Math.min(model.getValueLength(), offset + action.count)
          const endPos = model.getPositionAt(newOffset)
          model.applyEdits([
            {
              range: {
                startLineNumber: pos.lineNumber,
                startColumn: pos.column,
                endLineNumber: endPos.lineNumber,
                endColumn: endPos.column,
              },
              text: '',
            },
          ])
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
            model.setValue(replaced)
          }
        } else {
          const idx = fullText.indexOf(action.search)
          if (idx !== -1) {
            const start = model.getPositionAt(idx)
            const end = model.getPositionAt(idx + action.search.length)
            model.applyEdits([
              {
                range: {
                  startLineNumber: start.lineNumber,
                  startColumn: start.column,
                  endLineNumber: end.lineNumber,
                  endColumn: end.column,
                },
                text: action.replacement,
              },
            ])
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
}
