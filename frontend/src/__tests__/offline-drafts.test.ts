import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const records = new Map<string, any>()
const store = {
  get: async (key: string) => records.get(key),
  getAll: async () => [...records.values()],
  getAllFromIndex: async (_index: string, ownerId: string) => [...records.values()].filter((item) => item.ownerId === ownerId),
  put: async (value: any) => { records.set(value.key, value) },
  delete: async (key: string) => { records.delete(key) },
  clear: async () => { records.clear() },
}
const db = {
  transaction: () => ({ objectStore: () => store, done: Promise.resolve() }),
  get: (_storeName: string, key: string) => store.get(key),
  getAll: (_storeName: string) => store.getAll(),
  getAllFromIndex: (_storeName: string, index: string, ownerId: string) => store.getAllFromIndex(index, ownerId),
  put: (_storeName: string, value: any) => store.put(value),
  delete: (_storeName: string, key: string) => store.delete(key),
  clear: (_storeName: string) => store.clear(),
}

vi.mock('idb', () => ({ openDB: vi.fn(async () => db) }))

import {
  clearAllDrafts,
  clearAllDraftsExcept,
  deleteDraft,
  getDraft,
  getPendingDrafts,
  markSynced,
  pendingDraftCount,
  saveDraft,
} from '@/lib/offline-drafts'

const draft = (ownerId: string, resumeId: string, syncStatus: 'pending' | 'synced' = 'pending') => ({
  ownerId,
  resumeId,
  title: `${ownerId} resume`,
  latexContent: '\\documentclass{article}',
  savedAt: new Date(),
  syncStatus,
})

describe('owner-scoped offline drafts', () => {
  beforeEach(async () => {
    records.clear()
    await clearAllDrafts()
  })

  it('uses owner+resume identity for every read, pending query, sync, and delete', async () => {
    await saveDraft(draft('account-a', 'resume-1'))
    await saveDraft(draft('account-b', 'resume-1'))

    expect(await getDraft('account-b', 'resume-1')).toMatchObject({ ownerId: 'account-b' })
    expect(await getDraft('account-a', 'resume-1')).toMatchObject({ ownerId: 'account-a' })
    expect(await getPendingDrafts('account-a')).toHaveLength(1)
    expect(await pendingDraftCount('account-b')).toBe(1)

    await markSynced('account-a', 'resume-1')
    expect(await pendingDraftCount('account-a')).toBe(0)
    await deleteDraft('account-b', 'resume-1')
    expect(await getDraft('account-a', 'resume-1')).not.toBeNull()
    expect(await getDraft('account-b', 'resume-1')).toBeNull()
  })

  it('purges other owners on confirmed login and keeps current drafts', async () => {
    await saveDraft(draft('account-a', 'resume-1'))
    await saveDraft(draft('account-b', 'resume-2'))
    await clearAllDraftsExcept('account-b')

    expect(await getDraft('account-a', 'resume-1')).toBeNull()
    expect(await getDraft('account-b', 'resume-2')).not.toBeNull()

    const header = readFileSync(new URL('../components/GlobalHeader.tsx', import.meta.url), 'utf8')
    expect(header).toContain('clearAllDraftsExcept(effectiveUserId)')
    expect(header).toContain('clearAllDrafts()')
  })

  it('reconnect selection cannot flush another account as the current user', async () => {
    await saveDraft(draft('account-a', 'resume-a'))
    await saveDraft(draft('account-b', 'resume-b'))
    const updates: string[] = []
    for (const pending of await getPendingDrafts('account-b')) updates.push(pending.resumeId)

    expect(updates).toEqual(['resume-b'])
    expect(await getPendingDrafts('account-a')).toHaveLength(1)
  })

  it('documents the v2 migration data-loss boundary instead of guessing ownership', () => {
    const source = readFileSync(new URL('../lib/offline-drafts.ts', import.meta.url), 'utf8')
    expect(source).toContain('OFFLINE_DB_VERSION = 3')
    expect(source).toContain('v2 rows were keyed only by resumeId')
    expect(source).toContain('deletes them rather than guessing')
    expect(source).toContain('cold offline recovery inside the same unlocked browser profile')
  })
})
