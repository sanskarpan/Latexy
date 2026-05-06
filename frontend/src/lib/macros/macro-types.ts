/**
 * Macro action types and Macro interface — Feature 83.
 *
 * MacroAction is a discriminated union of every editor operation that can be
 * recorded and replayed. Actions are stored as JSONB in the backend.
 */

export type MacroAction =
  | { type: 'insert'; text: string }
  | { type: 'move'; direction: 'up' | 'down' | 'left' | 'right'; count: number }
  | {
      type: 'select'
      startLine: number
      startCol: number
      endLine: number
      endCol: number
    }
  | { type: 'delete'; direction: 'forward' | 'backward'; count: number }
  | { type: 'replace'; search: string; replacement: string; all: boolean }
  | { type: 'command'; monacoCommand: string }

export interface Macro {
  id: string
  name: string
  description?: string
  shortcut?: string
  actions: MacroAction[]
  created_at?: string
  updated_at?: string
}

/** Payload for creating a macro via the API. */
export interface MacroCreate {
  name: string
  description?: string
  shortcut?: string
  actions: MacroAction[]
}

/** Payload for updating a macro via the API (all fields optional). */
export interface MacroUpdate {
  name?: string
  description?: string
  shortcut?: string
  actions?: MacroAction[]
}
