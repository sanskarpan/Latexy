import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import {
  ACTIVITY_CATEGORY_META,
  ACTIVITY_POLL_MS,
  MAX_ACTIVITY_ROWS,
  formatActivityTime,
  mergeActivityRows,
} from '@/lib/admin-activity'
import type { AdminActivityEvent } from '@/lib/api-client'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

function event(id: string, created_at = '2026-11-26T08:00:00+00:00'): AdminActivityEvent {
  return {
    id,
    category: 'compile',
    event: 'compile_completed',
    created_at,
    href: '/admin?tab=analytics',
  }
}

describe('admin live activity feed helpers', () => {
  it('dedupes replayed rows and keeps the newest-first order', () => {
    const previous = [event('compile:b'), event('compile:a')]
    const incoming = [event('compile:c'), event('compile:b')]
    const merged = mergeActivityRows(previous, incoming)
    expect(merged.map((row) => row.id)).toEqual(['compile:c', 'compile:b', 'compile:a'])
  })

  it('bounds the retained buffer', () => {
    const rows = Array.from({ length: MAX_ACTIVITY_ROWS + 40 }, (_, index) =>
      event(`compile:${index}`),
    )
    const merged = mergeActivityRows([], rows)
    expect(merged).toHaveLength(MAX_ACTIVITY_ROWS)
    expect(merged[0].id).toBe('compile:0')
    expect(merged[MAX_ACTIVITY_ROWS - 1].id).toBe(`compile:${MAX_ACTIVITY_ROWS - 1}`)
  })

  it('refreshes at or below the five-second acceptance window', () => {
    expect(ACTIVITY_POLL_MS).toBeLessThanOrEqual(5000)
  })

  it('defines a distinct badge for every required category', () => {
    expect(Object.keys(ACTIVITY_CATEGORY_META).sort()).toEqual([
      'compile',
      'error',
      'optimize',
      'payment',
      'signup',
    ])
    const classes = Object.values(ACTIVITY_CATEGORY_META).map((meta) => meta.badgeClassName)
    expect(new Set(classes).size).toBe(classes.length)
  })

  it('formats recent and older timestamps with a safe fallback', () => {
    const now = Date.parse('2026-11-26T08:00:30+00:00')
    expect(formatActivityTime('2026-11-26T08:00:00+00:00', now)).toBe('30s ago')
    expect(formatActivityTime('2026-11-26T07:30:00+00:00', now)).toBe('30m ago')
    expect(formatActivityTime('not-a-date', now)).toBe('—')
  })
})

describe('admin live activity feed wiring', () => {
  const component = read('../components/admin/AdminActivityFeed.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('mounts a dedicated component in the Analytics tab', () => {
    expect(analytics).toContain("import AdminActivityFeed from '@/components/admin/AdminActivityFeed'")
    expect(analytics).toContain('<AdminActivityFeed />')
  })

  it('polls with pause/resume, bounded rows and explicit fallback state', () => {
    expect(component).toContain('Pause')
    expect(component).toContain('Resume')
    expect(component).toContain('aria-pressed={paused}')
    expect(component).toContain('Fallback mode.')
    expect(component).toContain('Live feed interrupted.')
    expect(component).toContain('mergeActivityRows')
    expect(component).toContain('MAX_ACTIVITY_ROWS')
    expect(component).toContain('getAdminActivityFeed')
    expect(component).toContain('visibilitychange')
  })

  it('uses the incremental cursor contract and never renders metadata or user ids', () => {
    expect(apiClient).toContain('getAdminActivityFeed')
    expect(apiClient).toContain('/admin/analytics/activity')
    expect(apiClient).toContain("mode: 'live' | 'fallback'")
    expect(apiClient).toContain('next_cursor')
    expect(component).not.toContain('metadata')
    expect(component).not.toContain('user_id')
    expect(component).not.toContain('ip_address')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('prompt:')
    expect(component).not.toContain('payment_method')
  })
})
