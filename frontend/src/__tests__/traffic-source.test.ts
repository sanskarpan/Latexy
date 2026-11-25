import { describe, expect, it } from 'vitest'
import {
  buildTrafficLandingPayload,
  externalReferrerHost,
  readUtmParams,
  sanitizeLandingPath,
} from '@/lib/analytics/traffic-source'

describe('traffic-source UTM allowlist', () => {
  it('keeps only the five bounded, valid UTM values', () => {
    expect(
      readUtmParams(
        '?utm_source=Google&utm_medium=CPC&utm_campaign=Launch-2026' +
          '&utm_content=hero&utm_term=resume-builder&email=person%40example.com',
      ),
    ).toEqual({
      utm_source: 'google',
      utm_medium: 'cpc',
      utm_campaign: 'launch-2026',
      utm_content: 'hero',
      utm_term: 'resume-builder',
    })
  })

  it('drops free-form, oversized, duplicate, and malformed values', () => {
    expect(readUtmParams('?utm_source=free%20form')).toEqual({})
    expect(readUtmParams('?utm_source=person%40example.com')).toEqual({})
    expect(readUtmParams(`?utm_campaign=${'a'.repeat(65)}`)).toEqual({})
    expect(readUtmParams('?utm_source=google&utm_source=bing')).toEqual({})
    expect(readUtmParams('?utm_source=%3Cscript%3E')).toEqual({})
  })
})

describe('traffic-source URL sanitation', () => {
  it('strips query strings and opaque path identifiers before persistence', () => {
    expect(sanitizeLandingPath('/r/abc123?token=secret#frag')).toBe('/r/:token')
    expect(sanitizeLandingPath('/pricing?utm_source=google')).toBe('/pricing')
    expect(sanitizeLandingPath('/u/sanskar')).toBe('/u/:username')
    expect(sanitizeLandingPath('/workspace/550e8400-e29b-41d4-a716-446655440000/edit')).toBe(
      '/workspace/:resumeId/edit',
    )
  })

  it('stores only an external referrer host and never a full URL or IP', () => {
    expect(
      externalReferrerHost(
        'https://news.ycombinator.com/item?id=123&token=secret',
        'latexy.com',
      ),
    ).toBe('news.ycombinator.com')
    expect(externalReferrerHost('https://latexy.com/pricing?token=x', 'latexy.com')).toBeNull()
    expect(externalReferrerHost('https://127.0.0.1/private', 'latexy.com')).toBeNull()
    expect(externalReferrerHost('javascript:alert(1)', 'latexy.com')).toBeNull()
    expect(externalReferrerHost('https://localhost/private', 'latexy.com')).toBeNull()
  })

  it('builds a payload with only allowlisted fields', () => {
    const payload = buildTrafficLandingPayload({
      search: '?utm_source=google&utm_content=hero&utm_term=resume-builder',
      pathname: '/r/abc123',
      referrer: 'https://www.google.com/search?q=latexy&token=secret',
      currentHost: 'latexy.com',
      sessionId: '550e8400-e29b-41d4-a716-446655440000',
    })

    expect(payload).toEqual({
      landing_path: '/r/:token',
      referrer: 'www.google.com',
      session_id: '550e8400-e29b-41d4-a716-446655440000',
      utm_source: 'google',
      utm_content: 'hero',
      utm_term: 'resume-builder',
    })
    const serialized = JSON.stringify(payload).toLowerCase()
    expect(serialized).not.toContain('secret')
    expect(serialized).not.toContain('?')
    expect(serialized).not.toContain('http')
  })
})
