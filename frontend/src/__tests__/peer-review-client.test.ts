import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../lib/api-client'

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

function response(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

describe('peer review API contracts', () => {
  it('does not overwrite an existing review capability when omitted', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      share_token: 'token', share_url: '/r/token', created_at: '', anonymous: false,
      review_comments: true,
    })))

    await apiClient.createShareLink('resume', false, false)
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ anonymous: false })
  })

  it('sends an explicit capability update, including false', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      share_token: 'token', share_url: '/r/token', created_at: '', anonymous: false,
      review_comments: false,
    })))

    await apiClient.createShareLink('resume', false, false, false)
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toEqual({ anonymous: false, review_comments: false })
  })

  it('keeps public review text as exact JSON text and uses the capability path', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      id: 'comment', reviewer_label: 'Reviewer ABC123', content: '<script>alert(1)</script>',
      line_number: null, section_tag: null, resolved: false, created_at: '', updated_at: '',
    })))

    await apiClient.addPublicReviewComment('a token', { content: '<script>alert(1)</script>' })
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/share/a%20token/review-comments')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string).content).toBe('<script>alert(1)</script>')
  })

  it('sends normalized rendered-page anchors with a sticky comment', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({
      id: 'comment', reviewer_label: 'Reviewer ABC123', content: 'Move this',
      line_number: null, section_tag: null, page_number: 2, x: 0.25, y: 0.75,
      resolved: false, created_at: '', updated_at: '',
    })))

    await apiClient.addPublicReviewComment('token', {
      content: 'Move this', page_number: 2, x: 0.25, y: 0.75,
    })
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(init.body as string)).toMatchObject({ page_number: 2, x: 0.25, y: 0.75 })
  })

  it('uses an explicit idempotent resolved state rather than a toggle', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response({})))

    await apiClient.resolveReviewComment('resume', 'comment', true)
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(init.method).toBe('PATCH')
    expect(JSON.parse(init.body as string)).toEqual({ resolved: true })
  })

  it('exposes bounded authenticated history metadata to the review UI', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: { get: (name: string) => name === 'X-Review-Comments-Truncated' ? 'true' : 'application/json' },
      json: () => Promise.resolve([]),
    }))

    await expect(apiClient.listReviewComments('resume')).resolves.toEqual({ comments: [], truncated: true })
  })
})
