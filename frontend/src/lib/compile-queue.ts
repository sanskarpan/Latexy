/**
 * Offline Compile Queue (Feature 79D).
 *
 * When the user triggers a compilation while offline, instead of showing
 * an error the editor calls `enqueueCompile`.  On reconnect, `flushQueue`
 * iterates the queue and submits each job to the backend.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'

export interface QueuedCompile {
  id: string
  ownerId: string
  resumeId: string
  latexContent: string
  queuedAt: Date
}

interface LatexyCompileDB extends DBSchema {
  'compile-queue': {
    key: string // QueuedCompile.id
    value: QueuedCompile
    indexes: { 'by-owner': string }
  }
}

let _db: IDBPDatabase<LatexyCompileDB> | null = null

async function getDb(): Promise<IDBPDatabase<LatexyCompileDB>> {
  if (_db) return _db
  _db = await openDB<LatexyCompileDB>('latexy-compile-queue', 2, {
    upgrade(db, _oldVersion, _newVersion, transaction) {
      const store = db.objectStoreNames.contains('compile-queue')
        ? transaction.objectStore('compile-queue')
        : db.createObjectStore('compile-queue', { keyPath: 'id' })
      if (!store.indexNames.contains('by-owner')) store.createIndex('by-owner', 'ownerId')
      // Preserve v1 work, but quarantine it: ownership cannot safely be
      // inferred from a document ID or whichever account signs in next.
      // Rows lacking ownerId never appear in owner-scoped reconnect queries.
    },
  })
  return _db
}

function uuid(): string {
  return crypto.randomUUID()
}

/**
 * Add a compile job to the offline queue.
 * Returns the generated job ID.
 */
export async function enqueueCompile(
  ownerId: string,
  resumeId: string,
  latexContent: string,
): Promise<string> {
  if (!ownerId.trim() || !resumeId.trim()) throw new Error('Offline compile identity is missing')
  const db = await getDb()
  const id = uuid()
  await db.add('compile-queue', { id, ownerId, resumeId, latexContent, queuedAt: new Date() })
  return id
}

/** Return only this owner's queued work, oldest first. */
export async function getQueuedCompiles(ownerId: string): Promise<QueuedCompile[]> {
  if (!ownerId.trim()) return []
  const db = await getDb()
  const rows = await db.getAllFromIndex('compile-queue', 'by-owner', ownerId)
  return rows.filter(row => row.ownerId === ownerId).sort((a, b) => a.queuedAt.getTime() - b.queuedAt.getTime())
}

/** Remove a single queued compile (after successful submission). */
export async function dequeueCompile(ownerId: string, id: string): Promise<void> {
  if (!ownerId.trim() || !id.trim()) return
  const db = await getDb()
  const tx = db.transaction('compile-queue', 'readwrite')
  const row = await tx.store.get(id)
  if (row?.ownerId === ownerId) await tx.store.delete(id)
  await tx.done
}

/** Remove all queued compiles. */
export async function clearCompileQueue(): Promise<void> {
  const db = await getDb()
  await db.clear('compile-queue')
}

/** Number of pending compiles (for badge display). */
export async function queuedCompileCount(ownerId: string): Promise<number> {
  return (await getQueuedCompiles(ownerId)).length
}
