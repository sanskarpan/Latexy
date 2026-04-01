export interface Shortcut {
  keys: string[]
  description: string
  category: 'file' | 'edit' | 'compile' | 'navigation' | 'ai' | 'view'
}

const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.userAgent)
const mod = isMac ? '⌘' : 'Ctrl'
const shift = isMac ? '⇧' : 'Shift'
const alt = isMac ? '⌥' : 'Alt'

export const SHORTCUTS: Shortcut[] = [
  // ── Compile ────────────────────────────────────────────────────
  { keys: [mod, '↵'],           description: 'Compile resume',                category: 'compile' },
  { keys: [mod, shift, '↵'],    description: 'Optimize & compile',            category: 'compile' },

  // ── File ───────────────────────────────────────────────────────
  { keys: [mod, 'S'],           description: 'Save',                           category: 'file' },
  { keys: [mod, shift, 'S'],    description: 'Save checkpoint',                category: 'file' },
  { keys: [mod, shift, 'E'],    description: 'Export PDF',                     category: 'file' },

  // ── Edit ───────────────────────────────────────────────────────
  { keys: [mod, 'Z'],           description: 'Undo',                           category: 'edit' },
  { keys: [mod, shift, 'Z'],    description: 'Redo',                           category: 'edit' },
  { keys: [mod, 'X'],           description: 'Cut line / selection',           category: 'edit' },
  { keys: [mod, 'C'],           description: 'Copy line / selection',          category: 'edit' },
  { keys: [mod, 'V'],           description: 'Paste',                          category: 'edit' },
  { keys: [mod, 'D'],           description: 'Select next occurrence',         category: 'edit' },
  { keys: [mod, '/'],           description: 'Toggle line comment',            category: 'edit' },
  { keys: [alt, '↑'],           description: 'Move line up',                   category: 'edit' },
  { keys: [alt, '↓'],           description: 'Move line down',                 category: 'edit' },
  { keys: [mod, shift, 'K'],    description: 'Delete line',                    category: 'edit' },
  { keys: [mod, ']'],           description: 'Indent line',                    category: 'edit' },
  { keys: [mod, '['],           description: 'Outdent line',                   category: 'edit' },

  // ── Navigation ─────────────────────────────────────────────────
  { keys: [mod, 'F'],           description: 'Find in editor',                 category: 'navigation' },
  { keys: [mod, 'H'],           description: 'Find and replace',               category: 'navigation' },
  { keys: [mod, 'G'],           description: 'Go to line',                     category: 'navigation' },
  { keys: [mod, 'P'],           description: 'Command palette',                category: 'navigation' },
  { keys: [mod, shift, 'H'],    description: 'Open LaTeX presets',             category: 'navigation' },

  // ── AI ─────────────────────────────────────────────────────────
  { keys: [mod, shift, 'A'],    description: 'AI writing assistant',           category: 'ai' },

  // ── View ───────────────────────────────────────────────────────
  { keys: [mod, '?'],           description: 'Show keyboard shortcuts',        category: 'view' },
  { keys: [mod, 'B'],           description: 'Toggle sidebar',                 category: 'view' },
  { keys: [mod, shift, 'M'],    description: 'Toggle minimap',                 category: 'view' },
]

export const CATEGORY_LABELS: Record<Shortcut['category'], string> = {
  compile: 'Compile',
  file: 'File',
  edit: 'Editing',
  navigation: 'Navigation',
  ai: 'AI',
  view: 'View',
}

export const CATEGORY_ORDER: Shortcut['category'][] = [
  'compile', 'file', 'edit', 'navigation', 'ai', 'view',
]
