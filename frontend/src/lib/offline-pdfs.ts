/**
 * Owner-scoped cache for the latest compiled PDF (Feature #1342).
 *
 * This intentionally lives in IndexedDB rather than Cache Storage. Service
 * worker caches are URL-scoped and are not partitioned by authenticated user;
 * an owner id is part of every key and every read is checked against it.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'

export const OFFLINE_DB_VERSION = 3

export const MAX_OFFLINE_PDF_BYTES = 5 * 1024 * 1024
export const MAX_OFFLINE_PDF_TOTAL_BYTES = 20 * 1024 * 1024
export const OFFLINE_PDF_OWNER_KEY = 'latexy:last-authenticated-owner'

export function getRememberedOfflinePdfOwner(): string | null {
  if (typeof window === 'undefined') return null
  try { return window.localStorage.getItem(OFFLINE_PDF_OWNER_KEY) }
  catch { return null }
}

export function rememberOfflinePdfOwner(ownerId: string): void {
  if (typeof window === 'undefined' || !ownerId.trim()) return
  try { window.localStorage.setItem(OFFLINE_PDF_OWNER_KEY, ownerId) } catch { /* storage may be disabled */ }
}

export function forgetOfflinePdfOwner(): void {
  if (typeof window === 'undefined') return
  try { window.localStorage.removeItem(OFFLINE_PDF_OWNER_KEY) } catch { /* storage may be disabled */ }
}

export interface OfflineCompiledPdf {
  key: string
  ownerId: string
  resumeId: string
  title: string
  pdf: Blob
  byteSize: number
  savedAt: number
  lastAccessedAt: number
}

interface OfflinePdfDB extends DBSchema {
  drafts: {
    key: string
    value: {
      key: string
      ownerId: string
      resumeId: string
      title: string
      latexContent: string
      savedAt: Date
      syncStatus: 'pending' | 'synced' | 'conflict'
    }
    indexes: { 'by-status': string; 'by-owner': string }
  }
  'compiled-pdfs': {
    key: string
    value: OfflineCompiledPdf
    indexes: { 'by-owner': string; 'by-accessed': number }
  }
}

let dbPromise: Promise<IDBPDatabase<OfflinePdfDB>> | null = null

function getKey(ownerId: string, resumeId: string): string {
  // JSON avoids ambiguous collisions if either identifier contains a colon.
  return JSON.stringify([ownerId, resumeId])
}

async function getDb(): Promise<IDBPDatabase<OfflinePdfDB>> {
  if (!dbPromise) {
    dbPromise = openDB<OfflinePdfDB>('latexy-offline', OFFLINE_DB_VERSION, {
      upgrade(db, oldVersion) {
        // The shared offline-drafts module owns the drafts store. This branch
        // also makes this module safe when it is the first opener on a fresh
        // browser profile.
        if (oldVersion < OFFLINE_DB_VERSION && db.objectStoreNames.contains('drafts')) {
          // v2 draft rows had no owner. Deleting them avoids guessing and
          // accidentally exposing one account's source to another.
          db.deleteObjectStore('drafts')
        }
        if (!db.objectStoreNames.contains('drafts')) {
          const drafts = db.createObjectStore('drafts', { keyPath: 'key' })
          drafts.createIndex('by-status', 'syncStatus')
          drafts.createIndex('by-owner', 'ownerId')
        }
        if (!db.objectStoreNames.contains('compiled-pdfs')) {
          const store = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
          store.createIndex('by-owner', 'ownerId')
          store.createIndex('by-accessed', 'lastAccessedAt')
        }
      },
    })
  }
  return dbPromise
}

function assertIdentity(ownerId: string, resumeId: string): void {
  if (!ownerId.trim() || !resumeId.trim()) throw new Error('Offline PDF identity is missing')
}

async function assertPdf(blob: Blob): Promise<void> {
  if (!(blob instanceof Blob) || blob.size === 0 || blob.size > MAX_OFFLINE_PDF_BYTES) {
    throw new Error('This PDF is too large to store offline')
  }
  const header = await blob.slice(0, 5).text()
  if (header !== '%PDF-') throw new Error('Only valid PDF files can be stored offline')
}

/** Keep persisted/returned bytes unchanged while removing a caller-controlled MIME type. */
function normalizePdfBlob(blob: Blob): Blob {
  return new Blob([blob], { type: 'application/pdf' })
}

function storedBytes(record: OfflineCompiledPdf): number {
  const declared = Number(record.byteSize)
  const actual = record.pdf instanceof Blob ? record.pdf.size : 0
  // Never trust metadata from a previous version of the store. The Blob's
  // measured size is authoritative when metadata is absent or malformed.
  return Number.isFinite(declared) && declared >= 0 && declared === actual ? declared : actual
}

/** Save/replace the newest compiled PDF while enforcing both byte bounds. */
export async function saveOfflineCompiledPdf(input: {
  ownerId: string
  resumeId: string
  title?: string
  pdf: Blob
  /** Abort persistence when the authenticated owner/route changed in-flight. */
  shouldPersist?: () => boolean
}): Promise<void> {
  assertIdentity(input.ownerId, input.resumeId)
  await assertPdf(input.pdf)
  const db = await getDb()
  const key = getKey(input.ownerId, input.resumeId)
  const now = Date.now()
  const tx = db.transaction('compiled-pdfs', 'readwrite')
  const store = tx.objectStore('compiled-pdfs')
  const abandon = async () => {
    try { tx.abort() } catch { /* already finished */ }
    await tx.done.catch(() => {})
  }
  const records = await store.getAll()
  if (input.shouldPersist && !input.shouldPersist()) {
    await abandon()
    return
  }
  const existing = records.find((item) => item.key === key)
  let total = records.reduce((sum, item) => sum + storedBytes(item), 0)
  if (existing) total -= storedBytes(existing)

  // Evict least-recently-used records, but never evict the record being saved.
  const evictable = records
    .filter((item) => item.key !== key)
    .sort((a, b) => (a.lastAccessedAt || a.savedAt) - (b.lastAccessedAt || b.savedAt))
  for (const item of evictable) {
    if (total + input.pdf.size <= MAX_OFFLINE_PDF_TOTAL_BYTES) break
    if (input.shouldPersist && !input.shouldPersist()) {
      await abandon()
      return
    }
    await store.delete(item.key)
    total -= storedBytes(item)
  }
  if (total + input.pdf.size > MAX_OFFLINE_PDF_TOTAL_BYTES) {
    throw new Error('Offline PDF storage is full')
  }
  if (input.shouldPersist && !input.shouldPersist()) {
    await abandon()
    return
  }

  await store.put({
    key,
    ownerId: input.ownerId,
    resumeId: input.resumeId,
    title: input.title?.trim() || 'Resume',
    pdf: normalizePdfBlob(input.pdf),
    byteSize: input.pdf.size,
    savedAt: now,
    lastAccessedAt: now,
  })
  await tx.done
}

/** Return a cached PDF only when both owner and resume ids match the request. */
export async function getOfflineCompiledPdf(ownerId: string, resumeId: string): Promise<OfflineCompiledPdf | null> {
  assertIdentity(ownerId, resumeId)
  const db = await getDb()
  const key = getKey(ownerId, resumeId)
  const read = db.transaction('compiled-pdfs', 'readonly')
  const record = await read.objectStore('compiled-pdfs').get(key)
  await read.done
  if (!record || record.key !== key || record.ownerId !== ownerId || record.resumeId !== resumeId) return null
  try {
    // Blob.text() yields to browser file I/O. Keeping a write transaction open
    // here makes it auto-commit before the later put(), even though test doubles
    // often keep their transactions alive indefinitely.
    await assertPdf(record.pdf)
  } catch {
    // Do not delete by key after asynchronous validation: another tab may have
    // replaced the invalid snapshot with a valid PDF during that await.
    throw new Error('Cached PDF is invalid')
  }
  const tx = db.transaction('compiled-pdfs', 'readwrite')
  const store = tx.objectStore('compiled-pdfs')
  const current = await store.get(key)
  if (!current || current.key !== key || current.ownerId !== ownerId || current.resumeId !== resumeId) {
    await tx.done
    return null // A sign-out/purge during validation must not recreate the row.
  }
  const accessedAt = Date.now()
  // Refresh only the current row's LRU metadata, not the previously validated
  // snapshot's bytes. A concurrent save must remain the newest cached PDF.
  await store.put({ ...current, lastAccessedAt: accessedAt })
  await tx.done
  return { ...record, pdf: normalizePdfBlob(record.pdf), lastAccessedAt: accessedAt }
}

export async function deleteOfflineCompiledPdf(ownerId: string, resumeId: string): Promise<void> {
  assertIdentity(ownerId, resumeId)
  await (await getDb()).delete('compiled-pdfs', getKey(ownerId, resumeId))
}

/** Clear all cached PDFs, used on sign-out and before switching accounts. */
export async function clearAllOfflineCompiledPdfs(): Promise<void> {
  await (await getDb()).clear('compiled-pdfs')
}

/** Clear only one owner’s records when an account changes without sign-out. */
export async function clearOfflineCompiledPdfsForOwner(ownerId: string): Promise<void> {
  if (!ownerId.trim()) return
  const db = await getDb()
  const tx = db.transaction('compiled-pdfs', 'readwrite')
  const store = tx.objectStore('compiled-pdfs')
  const records = await store.getAll()
  for (const record of records) {
    if (record.ownerId === ownerId) await store.delete(record.key)
  }
  await tx.done
}

/**
 * On every confirmed login, remove records belonging to other accounts. This
 * handles a browser reload/account switch where the previous in-memory owner
 * is unavailable, while retaining the current account’s latest PDFs.
 */
export async function clearOfflineCompiledPdfsExcept(ownerId: string): Promise<void> {
  if (!ownerId.trim()) return
  const db = await getDb()
  const tx = db.transaction('compiled-pdfs', 'readwrite')
  const store = tx.objectStore('compiled-pdfs')
  const records = await store.getAll()
  for (const record of records) {
    if (record.ownerId !== ownerId) await store.delete(record.key)
  }
  await tx.done
}
