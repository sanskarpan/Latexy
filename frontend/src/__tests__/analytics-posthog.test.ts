import { describe, expect, it } from 'vitest'
import {
  analyticsDashboardLinks,
  analyticsReplayLinkConfig,
  analyticsReplayTriageLinks,
  isAnalyticsConfigured,
  sanitizeAnalyticsPath,
  sanitizeAnalyticsProperties,
} from '@/lib/analytics/posthog'

describe('analytics path sanitization', () => {
  it('strips opaque share, portfolio, and workspace identifiers', () => {
    expect(sanitizeAnalyticsPath('/r/abc123?token=secret#x')).toBe('/r/:token')
    expect(sanitizeAnalyticsPath('/u/sanskar')).toBe('/u/:username')
    expect(sanitizeAnalyticsPath('/share/abc123')).toBe('/share/:token')
    expect(sanitizeAnalyticsPath('/portfolio/sanskar')).toBe('/portfolio/:username')
    expect(sanitizeAnalyticsPath('/workspace/550e8400-e29b-41d4-a716-446655440000/edit')).toBe(
      '/workspace/:resumeId/edit',
    )
    expect(sanitizeAnalyticsPath('/workspaces/team-id/recruiter')).toBe('/workspaces/:workspaceId/recruiter')
  })
})

describe('analytics property boundary', () => {
  it('drops direct identifiers, document content, secrets, and nested payloads', () => {
    const safe = sanitizeAnalyticsProperties({
      email: 'person@example.com',
      user_name: 'Person',
      resume_content: 'secret resume',
      latex_content: '\\documentclass',
      prompt: 'rewrite this',
      job_description: 'job text',
      access_token: 'token',
      feature_key: 'f01',
      plan: 'pro',
      duration_ms: 123,
      success: true,
      nested: { unsafe: 'value' },
      list: ['unsafe'],
    })

    expect(safe).toEqual({
      feature_key: 'f01',
      plan: 'pro',
      duration_ms: 123,
      success: true,
    })
  })

  it('bounds string length and property count', () => {
    const safe = sanitizeAnalyticsProperties({
      note: 'x'.repeat(500),
      ...Object.fromEntries(Array.from({ length: 40 }, (_, index) => [`key_${index}`, index])),
    })
    expect(String(safe.note)).toHaveLength(200)
    expect(Object.keys(safe).length).toBeLessThanOrEqual(25)
  })

  it('preserves bounded campaign attribution without allowing document content', () => {
    const safe = sanitizeAnalyticsProperties({
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'launch',
      utm_content: 'hero',
      utm_term: 'resume-builder',
      referrer_host: 'news.ycombinator.com',
      landing_path: '/r/abc123?token=secret',
      resume_content: 'private document text',
    })
    expect(safe).toEqual({
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'launch',
      utm_content: 'hero',
      utm_term: 'resume-builder',
      referrer_host: 'news.ycombinator.com',
      landing_path: '/r/:token',
    })
  })

  it('drops free-form campaign values before they reach PostHog', () => {
    const safe = sanitizeAnalyticsProperties({
      utm_source: 'free form',
      utm_content: 'person@example.com',
      utm_campaign: 'a'.repeat(65),
      referrer_host: '127.0.0.1',
      landing_path: 'https://evil.example/r/secret?token=x',
      resume_content: 'private document text',
    })
    expect(safe).toEqual({})
  })
})

describe('analytics configuration', () => {
  it('stays disabled when no public project key is configured', () => {
    expect(isAnalyticsConfigured()).toBe(false)
    expect(analyticsDashboardLinks()).toBeNull()
    expect(analyticsReplayLinkConfig(30)).toBeNull()
    expect(analyticsReplayTriageLinks(30)).toBeNull()
  })
})
