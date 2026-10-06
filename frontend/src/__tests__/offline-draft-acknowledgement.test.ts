import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as FDB from 'fake-indexeddb'

Object.assign(globalThis, FDB)

const snapshot = () => ({
  ownerId: 'owner-a', resumeId: 'resume-a', title: 'Draft', latexContent: 'Original offline work',
  expectedLatexContent: 'Server baseline', savedAt: new Date('2026-10-04T00:00:00Z'), syncStatus: 'pending' as const,
})

describe('offline draft acknowledgement uses an atomic revision check', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.assign(globalThis, { indexedDB: new FDB.IDBFactory() })
  })

  it('removes an acknowledged unchanged revision', async () => {
    const drafts = await import('@/lib/offline-drafts')
    const original = snapshot()
    await drafts.saveDraft(original)
    expect(await drafts.deleteDraftIfUnchanged(original)).toBe(true)
    expect(await drafts.getDraft(original.ownerId, original.resumeId)).toBeNull()
  })

  it.each([
    { latexContent: 'Newer offline work' },
    { title: 'New title' },
    { expectedLatexContent: 'New server baseline' },
    { savedAt: new Date('2026-10-04T00:00:01Z') },
    { syncStatus: 'conflict' as const },
  ])('preserves a changed local revision (%j)', async changes => {
    const drafts = await import('@/lib/offline-drafts')
    const original = snapshot()
    await drafts.saveDraft(original)
    const replacement = { ...original, ...changes }
    await drafts.saveDraft(replacement)
    expect(await drafts.deleteDraftIfUnchanged(original)).toBe(false)
    expect(await drafts.getDraft(original.ownerId, original.resumeId)).toMatchObject(replacement)
  })

  it('never deletes another owner’s revision with the same document ID', async () => {
    const drafts = await import('@/lib/offline-drafts')
    const original = snapshot()
    await drafts.saveDraft(original)
    await drafts.saveDraft({ ...original, ownerId: 'owner-b' })
    expect(await drafts.deleteDraftIfUnchanged(original)).toBe(true)
    expect(await drafts.getDraft('owner-b', original.resumeId)).not.toBeNull()
  })
})
