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
  resumeId: string
  latexContent: string
  queuedAt: Date
}

interface LatexyCompileDB extends DBSchema {
  'compile-queue': {
    key: string // QueuedCompile.id
    value: QueuedCompile
  }
}

let _db: IDBPDatabase<LatexyCompileDB> | null = null

async function getDb(): Promise<IDBPDatabase<LatexyCompileDB>> {
  if (_db) return _db
  _db = await openDB<LatexyCompileDB>('latexy-compile-queue', 1, {
    upgrade(db) {
      db.createObjectStore('compile-queue', { keyPath: 'id' })
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
  resumeId: string,
  latexContent: string,
): Promise<string> {
  const db = await getDb()
  const id = uuid()
  await db.add('compile-queue', { id, resumeId, latexContent, queuedAt: new Date() })
  return id
}

/** Return all queued compiles in insertion order. */
export async function getQueuedCompiles(): Promise<QueuedCompile[]> {
  const db = await getDb()
  return db.getAll('compile-queue')
}

/** Remove a single queued compile (after successful submission). */
export async function dequeueCompile(id: string): Promise<void> {
  const db = await getDb()
  await db.delete('compile-queue', id)
}

/** Remove all queued compiles. */
export async function clearCompileQueue(): Promise<void> {
  const db = await getDb()
  await db.clear('compile-queue')
}

/** Number of pending compiles (for badge display). */
export async function queuedCompileCount(): Promise<number> {
  const db = await getDb()
  return db.count('compile-queue')
}
