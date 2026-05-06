/**
 * Keyboard Macro System — Type Definitions (Feature 83B)
 *
 * MacroAction is a discriminated union covering all editor operations that can
 * be recorded and replayed. Each variant carries the minimum data needed to
 * faithfully reproduce the action in Monaco editor.
 */

// ── Cursor / position helpers ─────────────────────────────────────────────────

export interface EditorPosition {
  lineNumber: number
  column: number
}

export interface EditorRange {
  startLineNumber: number
  startColumn: number
  endLineNumber: number
  endColumn: number
}

// ── Action variants ───────────────────────────────────────────────────────────

/** Insert text at the current cursor position. */
export interface InsertAction {
  type: 'insert'
  text: string
}

/** Move the cursor to an absolute position (no selection). */
export interface MoveAction {
  type: 'move'
  position: EditorPosition
}

/** Set the editor selection to a range. */
export interface SelectAction {
  type: 'select'
  range: EditorRange
}

/** Delete the content within a range. */
export interface DeleteAction {
  type: 'delete'
  range: EditorRange
}

/** Replace the content of a range with new text. */
export interface ReplaceAction {
  type: 'replace'
  range: EditorRange
  text: string
}

/** Trigger a Monaco editor command by its registered id. */
export interface CommandAction {
  type: 'command'
  commandId: string
}

/** Discriminated union of all supported macro actions. */
export type MacroAction =
  | InsertAction
  | MoveAction
  | SelectAction
  | DeleteAction
  | ReplaceAction
  | CommandAction

// ── Macro model ───────────────────────────────────────────────────────────────

/** Full macro with actions — returned by GET /macros/:id and POST /macros. */
export interface Macro {
  id: string
  userId: string
  name: string
  description: string | null
  /** Optional keyboard shortcut string, e.g. "Ctrl+Shift+1" */
  shortcut: string | null
  actions: MacroAction[]
  createdAt: string
  updatedAt: string
}

/** Lightweight macro entry for list views (no actions payload). */
export interface MacroSummary {
  id: string
  name: string
  description: string | null
  shortcut: string | null
  createdAt: string
  updatedAt: string
}

// ── Request/Response shapes for the API client ────────────────────────────────

export interface CreateMacroPayload {
  name: string
  description?: string | null
  shortcut?: string | null
  actions: MacroAction[]
}

export interface UpdateMacroPayload {
  name?: string
  description?: string | null
  shortcut?: string | null
  actions?: MacroAction[]
}
