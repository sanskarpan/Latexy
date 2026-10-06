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
  script?: string | null
  script_version?: number
  script_hash?: string | null
  /** True when pre-cap recorded actions were quarantined and cannot execute. */
  legacy_actions_available?: boolean
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

const SAFE_MONACO_COMMANDS = new Set([
  'editor.action.formatDocument',
  'editor.action.indentLines',
  'editor.action.outdentLines',
])

const MAX_ACTION_TEXT_BYTES = 100_000
const MAX_ACTIONS_JSON_BYTES = 65_536

function hasInvalidUnicode(value: string): boolean {
  return /[\uD800-\uDFFF]/.test(value)
}

function utf8ByteLength(value: string): number | null {
  if (hasInvalidUnicode(value)) return null
  try {
    return new TextEncoder().encode(value).byteLength
  } catch {
    return null
  }
}

/** Runtime validation for legacy JSONB rows before anything reaches Monaco. */
export function isSafeMacroAction(value: unknown): value is MacroAction {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const action = value as Record<string, unknown>
  const keys = Object.keys(action).sort().join(',')
  const text = (candidate: unknown) => {
    if (typeof candidate !== 'string' || candidate.length > MAX_ACTION_TEXT_BYTES) return false
    if (/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(candidate)) return false
    const bytes = utf8ByteLength(candidate)
    return bytes !== null && bytes <= MAX_ACTION_TEXT_BYTES
  }
  if (action.type === 'insert') return keys === 'text,type' && text(action.text)
  if (action.type === 'move') return keys === 'count,direction,type' && ['up', 'down', 'left', 'right'].includes(String(action.direction)) && Number.isInteger(action.count) && Number(action.count) >= 0 && Number(action.count) <= 500_000
  if (action.type === 'select') return keys === 'endCol,endLine,startCol,startLine,type' && ['startLine', 'startCol', 'endLine', 'endCol'].every((key) => Number.isInteger(action[key]) && Number(action[key]) >= 1 && Number(action[key]) <= 500_000)
  if (action.type === 'delete') return keys === 'count,direction,type' && ['forward', 'backward'].includes(String(action.direction)) && Number.isInteger(action.count) && Number(action.count) >= 0 && Number(action.count) <= 500_000
  if (action.type === 'replace') return keys === 'all,replacement,search,type' && text(action.search) && Boolean(action.search) && text(action.replacement) && typeof action.all === 'boolean'
  if (action.type === 'command') return keys === 'monacoCommand,type' && typeof action.monacoCommand === 'string' && SAFE_MONACO_COMMANDS.has(action.monacoCommand)
  return false
}

export function validateMacroActions(actions: unknown): MacroAction[] {
  if (!Array.isArray(actions) || actions.length > 128 || !actions.every(isSafeMacroAction)) {
    throw new Error('This macro contains unsafe or invalid recorded actions.')
  }
  let serialized: string
  try {
    serialized = JSON.stringify(actions)
  } catch {
    throw new Error('This macro contains unsafe or invalid recorded actions.')
  }
  const bytes = utf8ByteLength(serialized)
  if (bytes === null || bytes > MAX_ACTIONS_JSON_BYTES) {
    throw new Error('This macro exceeds the recorded action size limit.')
  }
  return actions
}
