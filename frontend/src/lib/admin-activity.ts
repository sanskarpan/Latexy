import type { AdminActivityCategory, AdminActivityEvent } from '@/lib/api-client'

export const MAX_ACTIVITY_ROWS = 200
export const ACTIVITY_POLL_MS = 4000
export const ACTIVITY_PAGE_SIZE = 50

export interface ActivityCategoryMeta {
  label: string
  badgeClassName: string
}

export const ACTIVITY_CATEGORY_META: Record<AdminActivityCategory, ActivityCategoryMeta> = {
  signup: {
    label: 'Signup',
    badgeClassName: 'border-accent/30 bg-accent-soft text-accent-strong',
  },
  payment: {
    label: 'Payment',
    badgeClassName: 'border-ok/30 bg-ok/10 text-ok',
  },
  compile: {
    label: 'Compile',
    badgeClassName: 'border-line bg-surface-2 text-fg-2',
  },
  optimize: {
    label: 'Optimize',
    badgeClassName: 'border-warn/30 bg-warn/10 text-warn',
  },
  error: {
    label: 'Error',
    badgeClassName: 'border-err/30 bg-err/10 text-err',
  },
}

/**
 * Merge a newest-first page into a newest-first bounded buffer.
 *
 * The id set makes reconnect/replay idempotent, so a caller can retry the same
 * cursor after a dropped response without rendering the same row twice.
 */
export function mergeActivityRows(
  previous: AdminActivityEvent[],
  incoming: AdminActivityEvent[],
  maxRows: number = MAX_ACTIVITY_ROWS,
): AdminActivityEvent[] {
  const boundedMax = Number.isFinite(maxRows) && maxRows > 0 ? Math.floor(maxRows) : MAX_ACTIVITY_ROWS
  const seen = new Set<string>()
  const merged: AdminActivityEvent[] = []
  for (const row of [...incoming, ...previous]) {
    if (!row || typeof row.id !== 'string' || seen.has(row.id)) continue
    seen.add(row.id)
    merged.push(row)
    if (merged.length >= boundedMax) break
  }
  return merged
}

export function formatActivityTime(
  value: string,
  now: number = Date.now(),
  locale: string | undefined = undefined,
): string {
  const timestamp = Date.parse(value)
  if (!Number.isFinite(timestamp)) return '—'
  const deltaSeconds = Math.max(0, Math.round((now - timestamp) / 1000))
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`
  if (deltaSeconds < 3600) return `${Math.floor(deltaSeconds / 60)}m ago`
  if (deltaSeconds < 86_400) return `${Math.floor(deltaSeconds / 3600)}h ago`
  return new Date(timestamp).toLocaleString(locale)
}
