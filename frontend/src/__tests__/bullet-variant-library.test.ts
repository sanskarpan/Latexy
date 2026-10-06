import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, type BulletVariantSet } from '../lib/api-client'

const WIDGET_SOURCE = readFileSync(
  new URL('../components/WritingAssistantWidget.tsx', import.meta.url),
  'utf8'
)

const VARIANT_SET: BulletVariantSet = {
  id: 'variant-set-1',
  resume_id: 'resume-1',
  source_text: '\\item Led a migration.',
  target_label: 'Acme — Staff Engineer',
  options: ['\\item Directed a migration.', '\\item Guided a migration.', '\\item Orchestrated a migration.'],
  created_at: '2026-09-08T00:00:00Z',
  updated_at: '2026-09-08T00:00:00Z',
}

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    headers: {},
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body == null ? '' : JSON.stringify(body)),
  }))
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('bullet variant API client', () => {
  it('creates a three-option set with job context', async () => {
    mockFetch(VARIANT_SET)
    const result = await apiClient.generateBulletVariants({
      resume_id: 'resume-1',
      source_text: '\\item Led a migration.',
      job_description: 'Lead platform migrations.',
      target_label: 'Acme — Staff Engineer',
    })

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/ai/bullet-variants')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toMatchObject({
      resume_id: 'resume-1',
      target_label: 'Acme — Staff Engineer',
    })
    expect(result.options).toHaveLength(3)
  })

  it('lists by encoded resume id and deletes by encoded set id', async () => {
    mockFetch([VARIANT_SET])
    await apiClient.getBulletVariants('resume/id')
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toContain('resume_id=resume%2Fid')

    mockFetch(null, 204)
    await apiClient.deleteBulletVariantSet('set/id')
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/ai/bullet-variants/set%2Fid')
    expect(init.method).toBe('DELETE')
  })
})

describe('bullet variant review UI', () => {
  it('offers three-option generation, saved library, diffs, and duplicate blocking', () => {
    expect(WIDGET_SOURCE).toContain('Generate 3 variants')
    expect(WIDGET_SOURCE).toContain('Saved bullet library')
    expect(WIDGET_SOURCE).toContain('Only its fingerprint and this label are saved')
    expect(WIDGET_SOURCE).toContain('Apply this variant')
    expect(WIDGET_SOURCE).toContain('Already in document')
    expect(WIDGET_SOURCE).toContain('line-through')
  })
})
