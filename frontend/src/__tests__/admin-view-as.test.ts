import { describe, expect, it } from 'vitest'
import type { AdminViewAsSession } from '@/lib/api-client'
import {
  formatViewAsRemaining,
  readStoredAdminViewAsSession,
  saveAdminViewAsSession,
  viewAsBannerLabel,
  viewAsIsExpired,
  viewAsRequestHeaders,
  viewAsTimeLeftSeconds,
} from '@/lib/admin-view-as'

function fakeStorage() {
  const values = new Map<string, string>()
  return {
    values,
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value)
    },
    removeItem: (key: string) => {
      values.delete(key)
    },
  }
}

function session(expiresAt: string): AdminViewAsSession {
  return {
    id: 'session-1',
    approval_id: 'approval-1',
    target: {
      id: 'target-1',
      email: 'vi****@example.com',
      name: 'Vi** As*****',
      pii_masked: true,
      role: 'user',
      subscription_plan: 'pro',
      subscription_status: 'active',
      trial_used: false,
      created_at: '2026-01-01T00:00:00+00:00',
    },
    scope: 'read_only',
    status: 'active',
    reason: 'Support triage',
    read_only: true,
    banner: 'READ-ONLY view-as snapshot. No writes, credentials or document content.',
    created_at: '2026-01-01T00:00:00+00:00',
    expires_at: expiresAt,
    ended_at: null,
    end_reason: null,
    seconds_remaining: 600,
  }
}

describe('admin view-as client helpers', () => {
  const now = Date.parse('2026-01-01T00:10:00+00:00')

  it('clamps remaining time and formats a bounded countdown', () => {
    expect(viewAsTimeLeftSeconds('2026-01-01T00:15:00+00:00', now)).toBe(300)
    expect(viewAsTimeLeftSeconds('2026-01-01T00:09:00+00:00', now)).toBe(0)
    expect(viewAsTimeLeftSeconds('not-a-date', now)).toBe(0)
    expect(viewAsIsExpired('2026-01-01T00:09:00+00:00', now)).toBe(true)
    expect(formatViewAsRemaining(0)).toBe('00:00')
    expect(formatViewAsRemaining(65)).toBe('01:05')
  })

  it('always labels the banner read-only with the explicit target and scope', () => {
    const label = viewAsBannerLabel(session('2026-01-01T00:15:00+00:00'), now)
    expect(label).toContain('READ-ONLY view-as')
    expect(label).toContain('vi****@example.com')
    expect(label).toContain('scope read_only')
    expect(label).toContain('expires in 05:00')
  })

  it('uses a dedicated read-only token header, never Authorization', () => {
    expect(viewAsRequestHeaders('lx_view_token')).toEqual({
      'X-View-As-Token': 'lx_view_token',
    })
  })

  it('drops expired or malformed stored previews instead of restoring them', () => {
    const storage = fakeStorage()
    saveAdminViewAsSession(session('2026-01-01T00:15:00+00:00'), 'lx_view_valid', storage)
    expect(readStoredAdminViewAsSession(storage, now)?.token).toBe('lx_view_valid')

    saveAdminViewAsSession(session('2026-01-01T00:09:00+00:00'), 'lx_view_expired', storage)
    expect(readStoredAdminViewAsSession(storage, now)).toBeNull()
    expect(storage.values.size).toBe(0)

    storage.setItem('latexy:admin:view-as', '{"token": "missing-session"}')
    expect(readStoredAdminViewAsSession(storage, now)).toBeNull()
    expect(storage.values.size).toBe(0)
  })
})
