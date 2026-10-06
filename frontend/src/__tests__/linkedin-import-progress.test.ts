import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  clearLinkedInArchiveRequest,
  readLinkedInArchiveRequest,
  rememberLinkedInArchiveRequest,
} from '../lib/linkedin-import-progress'

const store = new Map<string, string>()

beforeEach(() => {
  store.clear()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => store.set(key, value),
      removeItem: (key: string) => store.delete(key),
    },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('LinkedIn archive request progress', () => {
  it('persists a valid request timestamp and clears it after ZIP import', () => {
    const now = new Date('2026-09-08T12:00:00.000Z')
    expect(rememberLinkedInArchiveRequest(now)).toBe(now.toISOString())
    expect(readLinkedInArchiveRequest()).toBe(now.toISOString())

    clearLinkedInArchiveRequest()
    expect(readLinkedInArchiveRequest()).toBeNull()
  })

  it('ignores malformed browser state', () => {
    store.set('latexy-linkedin-archive-requested-at', 'not-a-date')
    expect(readLinkedInArchiveRequest()).toBeNull()
  })
})
