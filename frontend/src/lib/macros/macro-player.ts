/**
 * Keyboard Macro System — Player Engine (Feature 83D)
 *
 * MacroPlayer replays a sequence of MacroActions on a Monaco editor instance.
 * Each action type maps to the appropriate Monaco API call.
 *
 * Usage:
 *   const player = new MacroPlayer()
 *   await player.play(macro, editor)
 */

import type * as Monaco from 'monaco-editor'
import type {
  CommandAction,
  DeleteAction,
  InsertAction,
  Macro,
  MacroAction,
  MoveAction,
  ReplaceAction,
  SelectAction,
} from './macro-types'

/** Delay between actions in milliseconds (keeps replay visible to the user). */
const ACTION_DELAY_MS = 0

export class MacroPlayer {
  private playing = false

  /** Returns true if a playback is in progress. */
  get isPlaying(): boolean {
    return this.playing
  }

  /**
   * Play all actions in the macro on the given editor.
   * Resolves when playback is complete. Rejects if already playing.
   */
  async play(
    macro: Macro | MacroAction[],
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): Promise<void> {
    if (this.playing) throw new Error('MacroPlayer: already playing')
    this.playing = true

    const actions = Array.isArray(macro) ? macro : macro.actions

    try {
      for (const action of actions) {
        this._executeAction(action, editor)
        if (ACTION_DELAY_MS > 0) {
          await _sleep(ACTION_DELAY_MS)
        }
      }
    } finally {
      this.playing = false
    }
  }

  // ── Private dispatch ─────────────────────────────────────────────────────────

  private _executeAction(
    action: MacroAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    switch (action.type) {
      case 'insert':
        this._executeInsert(action, editor)
        break
      case 'move':
        this._executeMove(action, editor)
        break
      case 'select':
        this._executeSelect(action, editor)
        break
      case 'delete':
        this._executeDelete(action, editor)
        break
      case 'replace':
        this._executeReplace(action, editor)
        break
      case 'command':
        this._executeCommand(action, editor)
        break
      default:
        // exhaustive check — TypeScript narrows to never
        break
    }
  }

  private _executeInsert(
    action: InsertAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    const position = editor.getPosition()
    if (!position) return
    editor.executeEdits('macro-player', [
      {
        range: {
          startLineNumber: position.lineNumber,
          startColumn: position.column,
          endLineNumber: position.lineNumber,
          endColumn: position.column,
        },
        text: action.text,
        forceMoveMarkers: true,
      },
    ])
  }

  private _executeMove(
    action: MoveAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    editor.setPosition(action.position)
    editor.revealPositionInCenterIfOutsideViewport(action.position)
  }

  private _executeSelect(
    action: SelectAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    editor.setSelection(action.range)
    editor.revealRangeInCenterIfOutsideViewport(action.range)
  }

  private _executeDelete(
    action: DeleteAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    editor.executeEdits('macro-player', [
      {
        range: action.range,
        text: '',
        forceMoveMarkers: true,
      },
    ])
  }

  private _executeReplace(
    action: ReplaceAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    editor.executeEdits('macro-player', [
      {
        range: action.range,
        text: action.text,
        forceMoveMarkers: true,
      },
    ])
  }

  private _executeCommand(
    action: CommandAction,
    editor: Monaco.editor.IStandaloneCodeEditor,
  ): void {
    const cmd = editor.getAction(action.commandId)
    if (cmd) {
      cmd.run()
    } else {
      console.warn(`MacroPlayer: unknown command "${action.commandId}"`)
    }
  }
}

function _sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
