/**
 * Offline Draft Storage (Feature 79C).
 *
 * Drafts are private device data, so every operation requires an owner id.
 * The owner is the authenticated id when online, or the remembered owner for
 * cold offline recovery inside the same unlocked browser profile.
 */

import { openDB, type DBSchema, type IDBPDatabase } from 'idb'
import type { OfflineCompiledPdf } from '@/lib/offline-pdfs'

export const OFFLINE_DB_VERSION = 3

export interface OfflineDraft {
  ownerId: string
  resumeId: string
  title: string
  latexContent: string
  /** Server source this draft was based on, when known. */
  expectedLatexContent?: string
  savedAt: Date
  syncStatus: 'pending' | 'synced' | 'conflict'
}

interface StoredOfflineDraft extends OfflineDraft {
  key: string
}

interface LatexyOfflineDB extends DBSchema {
  drafts: {
    key: string
    value: StoredOfflineDraft
    indexes: { 'by-status': string; 'by-owner': string }
  }
  'compiled-pdfs': {
    key: string
    value: OfflineCompiledPdf
    indexes: { 'by-owner': string; 'by-accessed': number }
  }
}

let _db: IDBPDatabase<LatexyOfflineDB> | null = null

function createDraftStore(db: IDBPDatabase<LatexyOfflineDB>): void {
  const store = db.createObjectStore('drafts', { keyPath: 'key' })
  store.createIndex('by-status', 'syncStatus')
  store.createIndex('by-owner', 'ownerId')
}

function draftKey(ownerId: string, resumeId: string): string {
  // JSON avoids ambiguous collisions if either identifier contains a colon.
  return JSON.stringify([ownerId, resumeId])
}

function assertIdentity(ownerId: string, resumeId: string): void {
  if (!ownerId.trim() || !resumeId.trim()) throw new Error('Offline draft identity is missing')
}

async function getDb(): Promise<IDBPDatabase<LatexyOfflineDB>> {
  if (_db) return _db
  _db = await openDB<LatexyOfflineDB>('latexy-offline', OFFLINE_DB_VERSION, {
    upgrade(db, oldVersion) {
      if (oldVersion < OFFLINE_DB_VERSION && db.objectStoreNames.contains('drafts')) {
        // v2 rows were keyed only by resumeId. Their owner cannot be inferred
        // safely, so migration intentionally deletes them rather than guessing.
        db.deleteObjectStore('drafts')
      }
      if (!db.objectStoreNames.contains('drafts')) createDraftStore(db)
      if (!db.objectStoreNames.contains('compiled-pdfs')) {
        const store = db.createObjectStore('compiled-pdfs', { keyPath: 'key' })
        store.createIndex('by-owner', 'ownerId')
        store.createIndex('by-accessed', 'lastAccessedAt')
      }
    },
  })
  return _db
}

/** Persist a draft under the unambiguous owner+resume key. */
export async function saveDraft(draft: OfflineDraft): Promise<void> {
  assertIdentity(draft.ownerId, draft.resumeId)
  const db = await getDb()
  await db.put('drafts', { ...draft, key: draftKey(draft.ownerId, draft.resumeId) })
}

/** Retrieve a draft only for the requested owner and resume. */
export async function getDraft(ownerId: string, resumeId: string): Promise<OfflineDraft | null> {
  assertIdentity(ownerId, resumeId)
  const db = await getDb()
  const draft = await db.get('drafts', draftKey(ownerId, resumeId))
  return draft?.ownerId === ownerId && draft.resumeId === resumeId ? draft : null
}

/** Return pending drafts belonging to exactly one owner. */
export async function getPendingDrafts(ownerId: string): Promise<OfflineDraft[]> {
  if (!ownerId.trim()) return []
  const db = await getDb()
  const drafts = await db.getAllFromIndex('drafts', 'by-owner', ownerId)
  return drafts.filter((draft) => draft.ownerId === ownerId && draft.syncStatus === 'pending')
}

export async function markSynced(ownerId: string, resumeId: string): Promise<void> {
  assertIdentity(ownerId, resumeId)
  const db = await getDb()
  const key = draftKey(ownerId, resumeId)
  const existing = await db.get('drafts', key)
  if (existing?.ownerId === ownerId && existing.resumeId === resumeId) {
    await db.put('drafts', { ...existing, syncStatus: 'synced' })
  }
}

export async function deleteDraft(ownerId: string, resumeId: string): Promise<void> {
  assertIdentity(ownerId, resumeId)
  const db = await getDb()
  await db.delete('drafts', draftKey(ownerId, resumeId))
}

/** Delete only the exact revision acknowledged by a reconnect save. */
export async function deleteDraftIfUnchanged(snapshot: OfflineDraft): Promise<boolean> {
  assertIdentity(snapshot.ownerId, snapshot.resumeId)
  const db = await getDb()
  const tx = db.transaction('drafts', 'readwrite')
  const key = draftKey(snapshot.ownerId, snapshot.resumeId)
  const current = await tx.store.get(key)
  const unchanged = Boolean(current &&
    current.ownerId === snapshot.ownerId && current.resumeId === snapshot.resumeId &&
    current.title === snapshot.title && current.latexContent === snapshot.latexContent &&
    current.expectedLatexContent === snapshot.expectedLatexContent &&
    current.syncStatus === snapshot.syncStatus &&
    current.savedAt instanceof Date && snapshot.savedAt instanceof Date &&
    current.savedAt.getTime() === snapshot.savedAt.getTime())
  if (unchanged) await tx.store.delete(key)
  await tx.done
  return unchanged
}

/** Delete every locally stored draft, used on sign-out. */
export async function clearAllDrafts(): Promise<void> {
  const db = await getDb()
  await db.clear('drafts')
}

/** On confirmed login, retain only the current account's drafts. */
export async function clearAllDraftsExcept(ownerId: string): Promise<void> {
  if (!ownerId.trim()) return
  const db = await getDb()
  const all = await db.getAll('drafts')
  for (const draft of all) {
    if (draft.ownerId !== ownerId) await db.delete('drafts', draft.key)
  }
}

/** Count pending drafts for one owner only. */
export async function pendingDraftCount(ownerId: string): Promise<number> {
  return (await getPendingDrafts(ownerId)).length
}
