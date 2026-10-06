import { beforeEach, describe, expect, it, vi } from 'vitest'

const records = new Map<string, any>()
const store = {
  get: async (key: string) => records.get(key),
  getAll: async () => [...records.values()],
  put: async (value: any) => { records.set(value.key, value) },
  delete: async (key: string) => { records.delete(key) },
  clear: async () => { records.clear() },
}
const db = {
  transaction: () => {
    const snapshot = new Map(records)
    return {
      objectStore: () => store,
      abort: () => {
        records.clear()
        for (const [key, value] of snapshot) records.set(key, value)
      },
      done: Promise.resolve(),
    }
  },
  get: store.get,
  delete: store.delete,
  clear: store.clear,
}

vi.mock('idb', () => ({ openDB: vi.fn(async () => db) }))

import {
  clearAllOfflineCompiledPdfs,
  clearOfflineCompiledPdfsExcept,
  getOfflineCompiledPdf,
  MAX_OFFLINE_PDF_BYTES,
  MAX_OFFLINE_PDF_TOTAL_BYTES,
  saveOfflineCompiledPdf,
} from '@/lib/offline-pdfs'

function pdf(size: number): Blob {
  return new Blob([`%PDF-${'x'.repeat(Math.max(0, size - 5))}`], { type: 'application/pdf' })
}

describe('owner-scoped offline compiled PDFs', () => {
  beforeEach(async () => {
    records.clear()
    vi.useRealTimers()
    await clearAllOfflineCompiledPdfs()
  })

  it('rejects oversized/non-PDF data and never crosses owner boundaries', async () => {
    await expect(saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'r1', pdf: pdf(MAX_OFFLINE_PDF_BYTES + 1) }))
      .rejects.toThrow('too large')
    await expect(saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'r1', pdf: new Blob(['not a pdf']) }))
      .rejects.toThrow('valid PDF')

    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'r1', title: 'Private', pdf: pdf(32) })
    expect(await getOfflineCompiledPdf('u2', 'r1')).toBeNull()
    expect((await getOfflineCompiledPdf('u1', 'r1'))?.title).toBe('Private')
  })

  it('updates access time and evicts the least recently used document at the global cap', async () => {
    vi.useFakeTimers()
    const size = MAX_OFFLINE_PDF_BYTES
    for (const id of ['a', 'b', 'c', 'd']) {
      await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: id, pdf: pdf(size) })
      vi.advanceTimersByTime(10)
    }
    const before = (await getOfflineCompiledPdf('u1', 'a'))!.lastAccessedAt
    vi.advanceTimersByTime(10)
    const after = (await getOfflineCompiledPdf('u1', 'a'))!.lastAccessedAt
    expect(after).toBeGreaterThanOrEqual(before)

    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'e', pdf: pdf(1) })
    expect(await getOfflineCompiledPdf('u1', 'b')).toBeNull()
    expect(await getOfflineCompiledPdf('u1', 'a')).not.toBeNull()
    expect(MAX_OFFLINE_PDF_TOTAL_BYTES).toBe(size * 4)
  })

  it('purges other owners while retaining the signed-in owner cache', async () => {
    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'r1', pdf: pdf(32) })
    await saveOfflineCompiledPdf({ ownerId: 'u2', resumeId: 'r2', pdf: pdf(32) })
    await clearOfflineCompiledPdfsExcept('u1')
    expect(await getOfflineCompiledPdf('u1', 'r1')).not.toBeNull()
    expect(await getOfflineCompiledPdf('u2', 'r2')).toBeNull()
  })

  it('rejects a tampered snapshot without deleting a potentially replaced row', async () => {
    const key = JSON.stringify(['u1', 'tampered'])
    records.set(key, {
      key,
      ownerId: 'u1',
      resumeId: 'tampered',
      title: 'Tampered',
      pdf: new Blob(['not a PDF']),
      byteSize: 10,
      savedAt: Date.now(),
      lastAccessedAt: Date.now(),
    })
    await expect(getOfflineCompiledPdf('u1', 'tampered')).rejects.toThrow('invalid')
    expect(records.has(key)).toBe(true)
  })

  it('does not overwrite a newer PDF saved during asynchronous validation', async () => {
    const key = JSON.stringify(['u1', 'replacement'])
    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'replacement', pdf: pdf(32) })
    const original = records.get(key)
    const replacement = { ...original, pdf: pdf(48), byteSize: 48, title: 'Newest' }
    const originalBlob: Blob = original.pdf
    const slice = originalBlob.slice.bind(originalBlob)
    vi.spyOn(originalBlob, 'slice').mockImplementation((...args: Parameters<Blob['slice']>) => {
      records.set(key, replacement)
      return slice(...args)
    })
    expect((await getOfflineCompiledPdf('u1', 'replacement'))?.pdf.size).toBe(32)
    expect(records.get(key).pdf.size).toBe(48)
    expect(records.get(key).title).toBe('Newest')
  })

  it('does not reintroduce a PDF purged during asynchronous validation', async () => {
    const key = JSON.stringify(['u1', 'purged'])
    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'purged', pdf: pdf(32) })
    const blob: Blob = records.get(key).pdf
    const slice = blob.slice.bind(blob)
    vi.spyOn(blob, 'slice').mockImplementation((...args: Parameters<Blob['slice']>) => {
      records.delete(key)
      return slice(...args)
    })
    expect(await getOfflineCompiledPdf('u1', 'purged')).toBeNull()
    expect(records.has(key)).toBe(false)
  })

  it('normalizes persisted PDF MIME without changing the bytes or size', async () => {
    const bytes = '%PDF-1.7 header-prefixed fixture'
    const input = new Blob([bytes], { type: 'text/html' })
    await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: 'mime', pdf: input })

    const cached = await getOfflineCompiledPdf('u1', 'mime')
    expect(cached?.pdf.type).toBe('application/pdf')
    expect(cached?.pdf.size).toBe(input.size)
    expect(await cached?.pdf.text()).toBe(bytes)
    expect(records.get(JSON.stringify(['u1', 'mime'])).pdf.type).toBe('application/pdf')

    const legacyKey = JSON.stringify(['u1', 'legacy-mime'])
    records.set(legacyKey, {
      key: legacyKey,
      ownerId: 'u1',
      resumeId: 'legacy-mime',
      title: 'Legacy',
      pdf: new Blob([bytes], { type: '' }),
      byteSize: input.size,
      savedAt: Date.now(),
      lastAccessedAt: Date.now(),
    })
    expect((await getOfflineCompiledPdf('u1', 'legacy-mime'))?.pdf.type).toBe('application/pdf')
  })

  it('aborts an owner-switching save before LRU eviction can commit', async () => {
    const size = MAX_OFFLINE_PDF_BYTES
    for (const id of ['a', 'b', 'c', 'd']) {
      await saveOfflineCompiledPdf({ ownerId: 'u1', resumeId: id, pdf: pdf(size) })
    }
    const before = new Set(records.keys())
    let checks = 0
    await saveOfflineCompiledPdf({
      ownerId: 'u1',
      resumeId: 'replacement',
      pdf: pdf(1),
      shouldPersist: () => ++checks < 3,
    })
    expect(new Set(records.keys())).toEqual(before)
  })
})
