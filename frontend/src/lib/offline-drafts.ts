/**
 * Offline Draft Storage (Feature 79C).
 *
 * Uses IndexedDB (via `idb`) to persist resume drafts when the user is
 * offline.  The editor calls `saveDraft` in place of the API when
 * `navigator.onLine === false`.  On reconnect, `flushPendingDrafts` is
 * called to push all pending drafts to the server.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'

export interface OfflineDraft {
  resumeId: string
  title: string
  latexContent: string
  savedAt: Date
  syncStatus: 'pending' | 'synced' | 'conflict'
}

interface LatexyOfflineDB extends DBSchema {
  drafts: {
    key: string // resumeId
    value: OfflineDraft
    indexes: { 'by-status': string }
  }
}

let _db: IDBPDatabase<LatexyOfflineDB> | null = null

async function getDb(): Promise<IDBPDatabase<LatexyOfflineDB>> {
  if (_db) return _db
  _db = await openDB<LatexyOfflineDB>('latexy-offline', 1, {
    upgrade(db) {
      const store = db.createObjectStore('drafts', { keyPath: 'resumeId' })
      store.createIndex('by-status', 'syncStatus')
    },
  })
  return _db
}

/** Persist a draft locally (called when offline or as backup). */
export async function saveDraft(draft: OfflineDraft): Promise<void> {
  const db = await getDb()
  await db.put('drafts', draft)
}

/** Retrieve a single draft by resume ID. */
export async function getDraft(resumeId: string): Promise<OfflineDraft | null> {
  const db = await getDb()
  return (await db.get('drafts', resumeId)) ?? null
}

/** Return all drafts with `syncStatus === 'pending'`. */
export async function getPendingDrafts(): Promise<OfflineDraft[]> {
  const db = await getDb()
  return db.getAllFromIndex('drafts', 'by-status', 'pending')
}

/** Mark a draft as synced (call after successful PATCH /resumes/{id}). */
export async function markSynced(resumeId: string): Promise<void> {
  const db = await getDb()
  const existing = await db.get('drafts', resumeId)
  if (existing) {
    await db.put('drafts', { ...existing, syncStatus: 'synced' })
  }
}

/** Delete a draft after a successful sync. */
export async function deleteDraft(resumeId: string): Promise<void> {
  const db = await getDb()
  await db.delete('drafts', resumeId)
}

/**
 * Delete every locally stored draft. Called on sign-out so a subsequent user
 * on a shared device cannot load the previous user's offline drafts.
 */
export async function clearAllDrafts(): Promise<void> {
  const db = await getDb()
  await db.clear('drafts')
}

/** Count pending (unsynced) drafts — used for badge display. */
export async function pendingDraftCount(): Promise<number> {
  const pending = await getPendingDrafts()
  return pending.length
}
