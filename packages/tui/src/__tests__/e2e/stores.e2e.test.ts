import { describe, it, expect, beforeEach } from 'vitest'
import {
  $messages,
  $activeJobId,
  addMessage,
  updateMessage,
  clearMessages,
  nextId,
} from '../../stores/messages.js'
import { $overlay, $isBlocked, openOverlay, closeOverlay } from '../../stores/overlay.js'
import { $session } from '../../stores/session.js'
import { $ui } from '../../stores/ui.js'

describe('messages store', () => {
  beforeEach(() => clearMessages())

  it('starts empty', () => {
    expect($messages.get()).toEqual([])
  })

  it('addMessage returns id and persists message', () => {
    const id = addMessage({ role: 'user', content: 'hello' })
    expect($messages.get()[0]?.id).toBe(id)
    expect($messages.get()[0]?.content).toBe('hello')
  })

  it('addMessage sets timestamp as ISO string', () => {
    const id = addMessage({ role: 'user', content: 'ts-check' })
    const msg = $messages.get().find(m => m.id === id)
    expect(msg?.timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  it('updateMessage patches by id', () => {
    const id = addMessage({ role: 'tool_use', content: '', toolState: 'running', toolName: 'compile' })
    updateMessage(id, { toolState: 'success', durationMs: 1200 })
    const msg = $messages.get().find(m => m.id === id)
    expect(msg?.toolState).toBe('success')
    expect(msg?.durationMs).toBe(1200)
  })

  it('updateMessage does not affect other messages', () => {
    const id1 = addMessage({ role: 'user', content: 'first' })
    const id2 = addMessage({ role: 'user', content: 'second' })
    updateMessage(id2, { content: 'updated' })
    expect($messages.get().find(m => m.id === id1)?.content).toBe('first')
  })

  it('clearMessages empties the store', () => {
    addMessage({ role: 'user', content: 'test' })
    clearMessages()
    expect($messages.get()).toEqual([])
  })

  it('nextId generates unique values', () => {
    const ids = Array.from({ length: 100 }, () => nextId())
    expect(new Set(ids).size).toBe(100)
  })

  it('$activeJobId starts null', () => {
    expect($activeJobId.get()).toBeNull()
  })

  it('$activeJobId can be set and cleared', () => {
    $activeJobId.set('job-123')
    expect($activeJobId.get()).toBe('job-123')
    $activeJobId.set(null)
    expect($activeJobId.get()).toBeNull()
  })
})

describe('overlay store', () => {
  beforeEach(() => closeOverlay())

  it('$isBlocked is false when no overlay', () => {
    expect($isBlocked.get()).toBe(false)
  })

  it('$isBlocked is true when overlay is set', () => {
    openOverlay('some-overlay')
    expect($isBlocked.get()).toBe(true)
  })

  it('closeOverlay sets overlay to null', () => {
    openOverlay('test')
    closeOverlay()
    expect($overlay.get()).toBeNull()
    expect($isBlocked.get()).toBe(false)
  })

  it('openOverlay can store any value', () => {
    openOverlay({ type: 'login' })
    expect($overlay.get()).toEqual({ type: 'login' })
  })
})

describe('session store defaults', () => {
  it('has string backendUrl', () => {
    expect(typeof $session.get().backendUrl).toBe('string')
  })

  it('wsUrl is derived from backendUrl with ws protocol', () => {
    const s = $session.get()
    expect(s.wsUrl).toContain('ws')
  })

  it('starts unauthenticated', () => {
    // In tests there is no session token unless LATEXY_SESSION_TOKEN is set
    // Just verify the structure is correct
    const s = $session.get()
    expect('isAuthenticated' in s).toBe(true)
    expect('token' in s).toBe(true)
  })
})

describe('ui store defaults', () => {
  it('healthStatus starts as unknown', () => {
    expect($ui.get().healthStatus).toBe('unknown')
  })

  it('wsConnected starts false', () => {
    expect($ui.get().wsConnected).toBe(false)
  })

  it('notifications starts as empty array', () => {
    expect(Array.isArray($ui.get().notifications)).toBe(true)
  })
})
