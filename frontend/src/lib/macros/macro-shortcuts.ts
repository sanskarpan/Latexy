/** Keyboard shortcut normalization and matching for user macros. */

const MODIFIERS = new Set(['ctrl', 'alt', 'shift'])

// These combinations belong to the browser, operating system, or Monaco's
// primary editor commands. They must never be claimed by a user macro.
const RESERVED_SHORTCUTS = new Set([
  'ctrl+s', 'ctrl+shift+s', 'ctrl+c', 'ctrl+v', 'ctrl+x', 'ctrl+z', 'ctrl+shift+z',
  'ctrl+p', 'ctrl+f', 'ctrl+h', 'ctrl+r', 'ctrl+l', 'ctrl+w', 'ctrl+t',
  'ctrl+tab', 'ctrl+shift+tab', 'ctrl+pageup', 'ctrl+pagedown', 'ctrl+space',
  'ctrl+shift+p', 'ctrl+`', 'ctrl+alt+delete', 'alt+f4',
])

const NAMED_KEYS = new Set([
  'backspace', 'delete', 'down', 'end', 'enter', 'escape', 'home', 'insert',
  'left', 'pagedown', 'pageup', 'right', 'space', 'tab', 'up',
])

const SHIFTED_KEY_ALIASES: Record<string, string> = {
  '!': '1', '@': '2', '#': '3', '$': '4', '%': '5', '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
  '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
}

function isAllowedKey(key: string): boolean {
  return /^[a-z0-9]$/.test(key) || /^f(?:[1-9]|1[0-9]|2[0-4])$/.test(key) || NAMED_KEYS.has(key)
}

/** Return one canonical form, or null for malformed/reserved shortcuts. */
export function normalizeShortcut(shortcut: string): string | null {
  if (typeof shortcut !== 'string') return null
  const parts = shortcut.toLowerCase().split('+').map((part) => part.trim()).filter(Boolean)
  if (parts.length < 2 || parts.length > 4) return null
  const modifiers = parts.filter((part) => MODIFIERS.has(part))
  const keys = parts.filter((part) => !MODIFIERS.has(part))
  if (!modifiers.includes('ctrl') || keys.length !== 1 || new Set(modifiers).size !== modifiers.length) return null
  const key = keys[0]
  if (!key || !isAllowedKey(key)) return null
  const normalized = [...['ctrl', 'alt', 'shift'].filter((modifier) => modifiers.includes(modifier)), key].join('+')
  return RESERVED_SHORTCUTS.has(normalized) ? null : normalized
}

/** Whether a browser key event is eligible for macro dispatch. */
export function shouldHandleShortcutEvent(event: KeyboardEvent): boolean {
  if (event.isComposing || event.repeat) return false
  const target = event.target
  // The tag-name checks keep this utility safe in SSR/unit-test environments
  // where DOM constructors are not installed, while the instanceof checks
  // retain correct behavior for real browser elements.
  if (typeof HTMLInputElement !== 'undefined' && target instanceof HTMLInputElement) return false
  if (typeof HTMLTextAreaElement !== 'undefined' && target instanceof HTMLTextAreaElement && !target.classList.contains('inputarea')) return false
  const candidate = target as (EventTarget & { tagName?: string; isContentEditable?: boolean; classList?: { contains(name: string): boolean } }) | null
  if (candidate?.tagName?.toUpperCase() === 'INPUT') return false
  if (candidate?.tagName?.toUpperCase() === 'TEXTAREA' && !candidate.classList?.contains('inputarea')) return false
  if (candidate?.isContentEditable) return false
  return true
}

export function matchesShortcut(event: KeyboardEvent, shortcut: string): boolean {
  const normalized = normalizeShortcut(shortcut)
  if (!normalized || !shouldHandleShortcutEvent(event)) return false
  const parts = normalized.split('+')
  const key = parts[parts.length - 1]
  const eventKey = event.code.match(/^Key([A-Z])$/)?.[1].toLowerCase()
    ?? event.code.match(/^Digit([0-9])$/)?.[1]
    ?? event.code.match(/^(F(?:[1-9]|1[0-9]|2[0-4]))$/)?.[1].toLowerCase()
    ?? event.key.toLowerCase()
  const canonicalEventKey = SHIFTED_KEY_ALIASES[eventKey] ?? eventKey
  return (event.ctrlKey || event.metaKey) === parts.includes('ctrl')
    && event.altKey === parts.includes('alt')
    && event.shiftKey === parts.includes('shift')
    && canonicalEventKey === key
}
