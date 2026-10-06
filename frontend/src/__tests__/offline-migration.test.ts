import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as FDB from 'fake-indexeddb'

Object.assign(globalThis, FDB)

const DB_NAME = 'latexy-offline'
const OWNER = 'migration-owner'
const RESUME = 'migration-resume'

async function createV2Database(factory: IDBFactory): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const request = factory.open(DB_NAME, 2)
    request.onupgradeneeded = () => {
      const db = request.result
      const drafts = db.createObjectStore('drafts', { keyPath: 'resumeId' })
      drafts.createIndex('by-status', 'syncStatus')
      const pdfs = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
      pdfs.createIndex('by-owner', 'ownerId')
      pdfs.createIndex('by-accessed', 'lastAccessedAt')
      const tx = request.transaction!
      drafts.put({
        resumeId: RESUME,
        title: 'Legacy private draft',
        latexContent: 'legacy content',
        savedAt: new Date(),
        syncStatus: 'pending',
      })
      pdfs.put({
        key: JSON.stringify([OWNER, RESUME]),
        ownerId: OWNER,
        resumeId: RESUME,
        title: 'Preserved PDF',
        pdf: new Blob(['%PDF-1.4 preserved'], { type: 'application/pdf' }),
        byteSize: 19,
        savedAt: Date.now(),
        lastAccessedAt: Date.now(),
      })
      tx.oncomplete = () => {
        db.close()
        resolve()
      }
      tx.onerror = () => reject(tx.error)
    }
    request.onerror = () => reject(request.error)
  })
}

describe('offline IndexedDB v2 to v3 migration', () => {
  beforeEach(async () => {
    vi.resetModules()
  })

  it.each([
    ['draft module opens first', '@/lib/offline-drafts', '@/lib/offline-pdfs'],
    ['PDF module opens first', '@/lib/offline-pdfs', '@/lib/offline-drafts'],
  ])('%s deletes unowned v2 drafts but preserves compiled PDFs', async (_label, firstPath, secondPath) => {
    const factory = new FDB.IDBFactory()
    Object.assign(globalThis, { indexedDB: factory })
    await createV2Database(factory)
    if (firstPath.endsWith('offline-drafts')) {
      const drafts = await import('@/lib/offline-drafts')
      const pdfs = await import('@/lib/offline-pdfs')
      expect(await drafts.getDraft(OWNER, RESUME)).toBeNull()
      expect(await pdfs.getOfflineCompiledPdf(OWNER, RESUME)).not.toBeNull()
    } else {
      const pdfs = await import('@/lib/offline-pdfs')
      const drafts = await import('@/lib/offline-drafts')
      expect(await pdfs.getOfflineCompiledPdf(OWNER, RESUME)).not.toBeNull()
      expect(await drafts.getDraft(OWNER, RESUME)).toBeNull()
    }
  })
})
