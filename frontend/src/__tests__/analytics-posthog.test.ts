import { describe, expect, it } from 'vitest'
import {
  analyticsDashboardLinks,
  analyticsReplayLinkConfig,
  analyticsReplayTriageLinks,
  isAnalyticsConfigured,
  isBlockedAnalyticsPath,
  sanitizeAnalyticsEvent,
  sanitizeAnalyticsPath,
  sanitizeAnalyticsProperties,
  sanitizeAnalyticsRelease,
  sanitizeExceptionText,
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

describe('analytics event boundary', () => {
  it('blocks document, share, portfolio, and guest-editor surfaces entirely', () => {
    for (const path of [
      '/workspace/abc/edit',
      '/workspaces/team/recruiter',
      '/try',
      '/r/secret-token',
      '/u/sanskar',
      '/share/secret-token',
      '/portfolio/sanskar',
    ]) {
      expect(isBlockedAnalyticsPath(path)).toBe(true)
      expect(isBlockedAnalyticsPath(`https://latexy.xyz${path}?token=secret`)).toBe(true)
      expect(
        sanitizeAnalyticsEvent({
          event: '$exception',
          properties: {
            $current_url: `https://latexy.xyz${path}?token=secret`,
            $exception_list: [{ type: 'TypeError', value: 'document error' }],
          },
        }),
      ).toBeNull()
    }
    expect(isBlockedAnalyticsPath('/dashboard')).toBe(false)
    expect(isBlockedAnalyticsPath('/templates?tab=modern')).toBe(false)
  })

  it('keeps templated pageviews on share pages while blocking content events', () => {
    const pageview = sanitizeAnalyticsEvent({
      event: '$pageview',
      properties: {
        $current_url: 'https://latexy.xyz/r/abc123?token=secret#preview',
        $pathname: '/r/abc123',
      },
    })
    expect(pageview).not.toBeNull()
    expect(pageview?.properties).toMatchObject({
      $current_url: 'https://latexy.xyz/r/:token',
      $pathname: '/r/:token',
      route: '/r/:token',
    })

    for (const eventName of ['$exception', '$rageclick', '$dead_click']) {
      expect(
        sanitizeAnalyticsEvent({
          event: eventName,
          properties: { $current_url: 'https://latexy.xyz/r/abc123?token=secret' },
        }),
      ).toBeNull()
    }
  })

  it('templates URLs and derives a low-cardinality route before send', () => {
    const event = sanitizeAnalyticsEvent({
      event: '$pageview',
      properties: {
        $current_url: 'https://latexy.xyz/templates?token=secret#preview',
        $referrer: 'https://news.ycombinator.com/item?id=1',
        $pathname: '/templates',
        $input: 'private input',
        $selected_content: 'document text',
      },
    })
    expect(event).not.toBeNull()
    expect(event?.properties).toMatchObject({
      $current_url: 'https://latexy.xyz/templates',
      $pathname: '/templates',
      route: '/templates',
      $referrer: 'https://news.ycombinator.com/item',
    })
    expect(event?.properties?.$input).toBeUndefined()
    expect(event?.properties?.$selected_content).toBeUndefined()
  })

  it('strips clicked element text from rage and dead-click events', () => {
    for (const eventName of ['$rageclick', '$dead_click']) {
      const event = sanitizeAnalyticsEvent({
        event: eventName,
        properties: {
          $current_url: 'https://latexy.xyz/templates',
          $el_text: 'Download my résumé',
          $elements_chain: 'button:text="Download my résumé"',
          $elements: [{ tag_name: 'button', attr_class: 'primary' }],
        },
      })
      const properties = (event?.properties ?? {}) as Record<string, unknown>
      expect(properties.$el_text).toBeUndefined()
      expect(properties.$elements_chain).toBeUndefined()
      expect(properties.$elements).toBeUndefined()
      expect(properties.route).toBe('/templates')
    }
  })

  it('redacts exception values, stack filenames, emails, tokens, and identifiers', () => {
    const event = sanitizeAnalyticsEvent({
      event: '$exception',
      properties: {
        $current_url: 'https://latexy.xyz/dashboard?token=secret',
        $exception_list: [
          {
            type: 'TypeError',
            value:
              'Failed for person@example.com with phc_abcdefgh12345678 at https://latexy.xyz/app.js?token=secret id 550e8400-e29b-41d4-a716-446655440000',
            stacktrace: {
              type: 'raw',
              frames: [
                {
                  filename: 'https://latexy.xyz/static/app.js?token=secret',
                  function: 'runOptimization',
                  lineno: 12,
                  colno: 4,
                },
              ],
            },
          },
        ],
        $exception_steps: [{ message: 'private resume text' }],
      },
    })
    expect(event).not.toBeNull()
    const properties = (event?.properties ?? {}) as Record<string, unknown>
    expect(properties.route).toBe('/dashboard')
    expect(properties.error_type).toBe('TypeError')
    expect(properties.$exception_steps).toBeUndefined()
    const exception = (properties.$exception_list as Array<Record<string, unknown>>)[0]
    expect(exception.type).toBe('TypeError')
    expect(String(exception.value)).not.toContain('@')
    expect(String(exception.value)).not.toContain('phc_')
    expect(String(exception.value)).not.toContain('550e8400')
    expect(String(exception.value)).not.toContain('token=secret')
    const frame = (
      (exception.stacktrace as { frames: Array<Record<string, unknown>> }).frames
    )[0]
    expect(frame.filename).toBe('https://latexy.xyz/static/app.js')
  })

  it('bounds exception text and rejects unsafe release identifiers', () => {
    expect(sanitizeExceptionText('x'.repeat(500))).toHaveLength(240)
    expect(sanitizeExceptionText('mail person@example.com')).toBe('mail [email]')
    expect(sanitizeAnalyticsRelease('v1.2.3')).toBe('v1.2.3')
    expect(sanitizeAnalyticsRelease('abc123')).toBe('abc123')
    expect(sanitizeAnalyticsRelease('release one')).toBeNull()
    expect(sanitizeAnalyticsRelease('/etc/passwd')).toBeNull()
    expect(sanitizeAnalyticsRelease('phc_notarealkey123456')).toBeNull()
    expect(sanitizeAnalyticsRelease('a'.repeat(65))).toBeNull()
    expect(sanitizeAnalyticsRelease(null)).toBeNull()
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
