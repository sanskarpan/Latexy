import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as FDB from 'fake-indexeddb'

Object.assign(globalThis, FDB)

describe('owner-scoped offline compile queue', () => {
  beforeEach(() => {
    vi.resetModules()
    Object.assign(globalThis, { indexedDB: new FDB.IDBFactory() })
  })

  it('lists and counts only the requested owner, even for the same resume ID', async () => {
    const queue = await import('@/lib/compile-queue')
    await queue.enqueueCompile('owner-a', 'same-resume', 'Private A source')
    await queue.enqueueCompile('owner-b', 'same-resume', 'Private B source')
    expect(await queue.getQueuedCompiles('owner-b')).toMatchObject([
      { ownerId: 'owner-b', resumeId: 'same-resume', latexContent: 'Private B source' },
    ])
    expect(await queue.queuedCompileCount('owner-a')).toBe(1)
    expect(await queue.queuedCompileCount('owner-b')).toBe(1)
  })

  it('cannot dequeue another owner’s item', async () => {
    const queue = await import('@/lib/compile-queue')
    const id = await queue.enqueueCompile('owner-a', 'resume-a', 'Private source')
    await queue.dequeueCompile('owner-b', id)
    expect(await queue.getQueuedCompiles('owner-a')).toHaveLength(1)
    await queue.dequeueCompile('owner-a', id)
    expect(await queue.getQueuedCompiles('owner-a')).toEqual([])
  })

  it('refuses missing owner or document identities', async () => {
    const queue = await import('@/lib/compile-queue')
    await expect(queue.enqueueCompile('', 'resume-a', 'source')).rejects.toThrow()
    await expect(queue.enqueueCompile('owner-a', ' ', 'source')).rejects.toThrow()
    expect(await queue.getQueuedCompiles('')).toEqual([])
    expect(await queue.queuedCompileCount('')).toBe(0)
  })

  it('preserves but never transmits legacy unowned items on upgrade', async () => {
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open('latexy-compile-queue', 1)
      request.onupgradeneeded = () => {
        request.result.createObjectStore('compile-queue', { keyPath: 'id' }).put({
          id: 'legacy-item', resumeId: 'legacy-resume', latexContent: 'Unattributed private source', queuedAt: new Date(),
        })
      }
      request.onsuccess = () => { request.result.close(); resolve() }
      request.onerror = () => reject(request.error)
    })
    const queue = await import('@/lib/compile-queue')
    expect(await queue.getQueuedCompiles('owner-a')).toEqual([])
    await queue.enqueueCompile('owner-a', 'new-resume', 'Owned source')
    expect(await queue.getQueuedCompiles('owner-a')).toHaveLength(1)
    const { openDB } = await import('idb')
    const db = await openDB('latexy-compile-queue')
    expect(await db.get('compile-queue', 'legacy-item')).toMatchObject({ latexContent: 'Unattributed private source' })
    db.close()
  })

  it('keeps explicit sign-out cleanup available', async () => {
    const queue = await import('@/lib/compile-queue')
    await queue.enqueueCompile('owner-a', 'resume-a', 'source')
    await queue.enqueueCompile('owner-b', 'resume-b', 'source')
    await queue.clearCompileQueue()
    expect(await queue.getQueuedCompiles('owner-a')).toEqual([])
    expect(await queue.getQueuedCompiles('owner-b')).toEqual([])
  })
})
