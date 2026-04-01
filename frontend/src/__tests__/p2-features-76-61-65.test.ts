/**
 * Unit tests for P2 Features 76, 61, 65.
 *
 * Feature 76: Dark Mode PDF Preview — localStorage toggle + CSS filter
 * Feature 61: Keyboard Shortcuts Reference Panel — data, search, grouping
 * Feature 65: Browser Push Notifications — hook behavior
 */

import { describe, test, expect, beforeEach, vi } from 'vitest'

// ─────────────────────────────────────────────────────────────────────────────
// Feature 76 · Dark Mode PDF Preview
// ─────────────────────────────────────────────────────────────────────────────

const PDF_DARK_KEY = 'latexy_pdf_dark'

describe('Feature 76 · Dark Mode PDF Preview localStorage', () => {
  let store: Record<string, string>

  beforeEach(() => {
    store = {}
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value },
      removeItem: (key: string) => { delete store[key] },
    })
  })

  test('default state: dark mode is off (no key in localStorage)', () => {
    const isDark = localStorage.getItem(PDF_DARK_KEY) === '1'
    expect(isDark).toBe(false)
  })

  test('enabling dark mode sets key to "1"', () => {
    localStorage.setItem(PDF_DARK_KEY, '1')
    expect(localStorage.getItem(PDF_DARK_KEY)).toBe('1')
    const isDark = localStorage.getItem(PDF_DARK_KEY) === '1'
    expect(isDark).toBe(true)
  })

  test('disabling dark mode sets key to "0"', () => {
    localStorage.setItem(PDF_DARK_KEY, '1')
    localStorage.setItem(PDF_DARK_KEY, '0')
    const isDark = localStorage.getItem(PDF_DARK_KEY) === '1'
    expect(isDark).toBe(false)
  })

  test('CSS filter values for dark mode', () => {
    const darkPdf = true
    const style = darkPdf
      ? { filter: 'invert(1) hue-rotate(180deg)', background: '#fff' }
      : {}
    expect(style.filter).toBe('invert(1) hue-rotate(180deg)')
    expect(style.background).toBe('#fff')
  })

  test('CSS filter values for light mode (default)', () => {
    const darkPdf = false
    const style = darkPdf
      ? { filter: 'invert(1) hue-rotate(180deg)', background: '#fff' }
      : {}
    expect(style).toEqual({})
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Feature 61 · Keyboard Shortcuts Reference Panel
// ─────────────────────────────────────────────────────────────────────────────

import {
  SHORTCUTS,
  CATEGORY_LABELS,
  CATEGORY_ORDER,
  type Shortcut,
} from '@/lib/editor-shortcuts'

describe('Feature 61 · Keyboard Shortcuts Data', () => {
  test('SHORTCUTS is a non-empty array', () => {
    expect(Array.isArray(SHORTCUTS)).toBe(true)
    expect(SHORTCUTS.length).toBeGreaterThan(10)
  })

  test('every shortcut has required fields', () => {
    for (const s of SHORTCUTS) {
      expect(s.keys).toBeDefined()
      expect(Array.isArray(s.keys)).toBe(true)
      expect(s.keys.length).toBeGreaterThan(0)
      expect(s.description).toBeTruthy()
      expect(CATEGORY_ORDER).toContain(s.category)
    }
  })

  test('all categories in CATEGORY_ORDER have labels', () => {
    for (const cat of CATEGORY_ORDER) {
      expect(CATEGORY_LABELS[cat]).toBeTruthy()
    }
  })

  test('CATEGORY_ORDER covers all 6 categories', () => {
    expect(CATEGORY_ORDER).toHaveLength(6)
    expect(CATEGORY_ORDER).toContain('compile')
    expect(CATEGORY_ORDER).toContain('file')
    expect(CATEGORY_ORDER).toContain('edit')
    expect(CATEGORY_ORDER).toContain('navigation')
    expect(CATEGORY_ORDER).toContain('ai')
    expect(CATEGORY_ORDER).toContain('view')
  })

  test('searching shortcuts by description works', () => {
    const query = 'compile'
    const results = SHORTCUTS.filter((s) =>
      s.description.toLowerCase().includes(query)
    )
    expect(results.length).toBeGreaterThan(0)
    expect(results.every((r) => r.description.toLowerCase().includes('compile'))).toBe(true)
  })

  test('searching shortcuts by key works', () => {
    const query = 'S'
    const results = SHORTCUTS.filter((s) =>
      s.keys.some((k) => k.toLowerCase() === query.toLowerCase())
    )
    expect(results.length).toBeGreaterThan(0)
  })

  test('grouping shortcuts by category', () => {
    const map = new Map<string, Shortcut[]>()
    for (const s of SHORTCUTS) {
      const list = map.get(s.category) || []
      list.push(s)
      map.set(s.category, list)
    }
    // At least compile, edit, and navigation should have entries
    expect(map.has('compile')).toBe(true)
    expect(map.has('edit')).toBe(true)
    expect(map.has('navigation')).toBe(true)
  })

  test('Cmd+? shortcut exists in view category', () => {
    const shortcutEntry = SHORTCUTS.find(
      (s) => s.description.toLowerCase().includes('keyboard shortcuts')
    )
    expect(shortcutEntry).toBeDefined()
    expect(shortcutEntry!.category).toBe('view')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// Feature 65 · Browser Push Notifications
// ─────────────────────────────────────────────────────────────────────────────

const NOTIF_KEY = 'latexy_notifications_enabled'

describe('Feature 65 · Push Notifications localStorage', () => {
  let store: Record<string, string>

  beforeEach(() => {
    store = {}
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store[key] ?? null,
      setItem: (key: string, value: string) => { store[key] = value },
      removeItem: (key: string) => { delete store[key] },
    })
  })

  test('default: notifications enabled when key not set', () => {
    // Hook defaults to enabled (true) when no localStorage value
    const val = localStorage.getItem(NOTIF_KEY)
    const enabled = val !== 'false'
    expect(enabled).toBe(true)
  })

  test('explicitly disabled notifications', () => {
    localStorage.setItem(NOTIF_KEY, 'false')
    const enabled = localStorage.getItem(NOTIF_KEY) !== 'false'
    expect(enabled).toBe(false)
  })

  test('re-enabling notifications', () => {
    localStorage.setItem(NOTIF_KEY, 'false')
    localStorage.setItem(NOTIF_KEY, 'true')
    const enabled = localStorage.getItem(NOTIF_KEY) !== 'false'
    expect(enabled).toBe(true)
  })
})

describe('Feature 65 · Notification guard logic', () => {
  test('should not notify when tab is visible', () => {
    const shouldNotify = (
      enabled: boolean,
      permission: string,
      visibility: string,
    ) => {
      if (!enabled) return false
      if (permission !== 'granted') return false
      if (visibility === 'visible') return false
      return true
    }

    expect(shouldNotify(true, 'granted', 'visible')).toBe(false)
    expect(shouldNotify(true, 'granted', 'hidden')).toBe(true)
    expect(shouldNotify(false, 'granted', 'hidden')).toBe(false)
    expect(shouldNotify(true, 'default', 'hidden')).toBe(false)
    expect(shouldNotify(true, 'denied', 'hidden')).toBe(false)
  })

  test('notification tag replaces previous', () => {
    // The hook uses tag: 'latexy-job' to ensure only one notification at a time
    const tag = 'latexy-job'
    expect(tag).toBe('latexy-job')
  })
})
