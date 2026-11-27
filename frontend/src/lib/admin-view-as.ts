import type { AdminViewAsSession } from '@/lib/api-client'

export const VIEW_AS_STORAGE_KEY = 'latexy:admin:view-as'
export const VIEW_AS_EVENT = 'latexy:view-as-changed'

export interface StoredAdminViewAsSession {
  session: AdminViewAsSession
  token: string
}

interface MinimalStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

function browserStorage(): MinimalStorage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.sessionStorage
  } catch {
    return null
  }
}

export function viewAsTimeLeftSeconds(expiresAt: string, now: number = Date.now()): number {
  const deadline = Date.parse(expiresAt)
  if (!Number.isFinite(deadline)) return 0
  return Math.max(0, Math.floor((deadline - now) / 1000))
}

export function viewAsIsExpired(expiresAt: string, now: number = Date.now()): boolean {
  return viewAsTimeLeftSeconds(expiresAt, now) <= 0
}

export function formatViewAsRemaining(seconds: number): string {
  const bounded = Math.max(0, Math.floor(seconds))
  const minutes = Math.floor(bounded / 60)
  const remainder = bounded % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

export function viewAsBannerLabel(
  session: Pick<AdminViewAsSession, 'target' | 'scope' | 'expires_at'>,
  now: number = Date.now(),
): string {
  const email = session.target.email || session.target.id
  const remaining = formatViewAsRemaining(viewAsTimeLeftSeconds(session.expires_at, now))
  return `READ-ONLY view-as ${email} · scope ${session.scope} · expires in ${remaining}`
}

export function viewAsRequestHeaders(token: string): Record<string, string> {
  return { 'X-View-As-Token': token }
}

export function readStoredAdminViewAsSession(
  storage: MinimalStorage | null = browserStorage(),
  now: number = Date.now(),
): StoredAdminViewAsSession | null {
  if (!storage) return null
  try {
    const raw = storage.getItem(VIEW_AS_STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredAdminViewAsSession
    if (
      !parsed ||
      typeof parsed !== 'object' ||
      typeof parsed.token !== 'string' ||
      !parsed.session ||
      typeof parsed.session.id !== 'string' ||
      typeof parsed.session.expires_at !== 'string'
    ) {
      storage.removeItem(VIEW_AS_STORAGE_KEY)
      return null
    }
    if (viewAsIsExpired(parsed.session.expires_at, now)) {
      storage.removeItem(VIEW_AS_STORAGE_KEY)
      return null
    }
    return parsed
  } catch {
    try {
      storage.removeItem(VIEW_AS_STORAGE_KEY)
    } catch {
      // Storage can be unavailable in private browsing; fail closed above.
    }
    return null
  }
}

export function saveAdminViewAsSession(
  session: AdminViewAsSession,
  token: string,
  storage: MinimalStorage | null = browserStorage(),
): void {
  if (!storage) return
  try {
    storage.setItem(VIEW_AS_STORAGE_KEY, JSON.stringify({ session, token }))
  } catch {
    return
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(VIEW_AS_EVENT))
  }
}

export function clearAdminViewAsSession(
  storage: MinimalStorage | null = browserStorage(),
): void {
  if (storage) {
    try {
      storage.removeItem(VIEW_AS_STORAGE_KEY)
    } catch {
      // Best effort: an unavailable store cannot hold a preview token anyway.
    }
  }
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new Event(VIEW_AS_EVENT))
  }
}
