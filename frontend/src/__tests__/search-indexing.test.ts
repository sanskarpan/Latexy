import { afterEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'
import { middleware } from '../middleware'
import robots from '../app/robots'
import sitemap from '../app/sitemap'
import { GET as llms } from '../app/llms.txt/route'
import {
  APP_ROBOTS_DIRECTIVE,
  isNonIndexableAppPath,
  NON_INDEXABLE_APP_ROOTS,
} from '../lib/search-indexing'

function request(url: string): NextRequest {
  return new NextRequest(url, { headers: { host: new URL(url).host } })
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.unstubAllGlobals()
})

describe('application search indexing policy', () => {
  it.each(NON_INDEXABLE_APP_ROOTS)('marks %s and descendants without matching similarly named public routes', root => {
    expect(isNonIndexableAppPath(root)).toBe(true)
    expect(isNonIndexableAppPath(`${root}/nested`)).toBe(true)
    expect(isNonIndexableAppPath(`${root}-guide`)).toBe(false)
  })

  it.each(NON_INDEXABLE_APP_ROOTS)('returns the noindex directive on the actual %s middleware response', async root => {
    const fetch = vi.fn(() => { throw new Error('Canonical app host must not resolve an integration') })
    vi.stubGlobal('fetch', fetch)
    const response = await middleware(request(`https://latexy.xyz${root}?intent=synthetic`))
    expect(response.headers.get('X-Robots-Tag')).toBe(APP_ROBOTS_DIRECTIVE)
    expect(fetch).not.toHaveBeenCalled()
  })

  it.each(['/', '/platform', '/templates', '/pricing', '/resources', '/faq', '/updates', '/privacy', '/terms', '/accessibility', '/try', '/u/alex', '/r/synthetic-share', '/api/auth/callback/google'])('does not add private-page directives to %s', async path => {
    expect(isNonIndexableAppPath(path)).toBe(false)
    const response = await middleware(request(`https://latexy.xyz${path}`))
    expect(response.headers.get('X-Robots-Tag')).toBeNull()
  })

  it('preserves verified tenant routing, its cookie and private-page directive', async () => {
    vi.stubEnv('BACKEND_URL', 'https://backend.example')
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ tenant: { slug: 'synthetic-tenant' } })))
    vi.stubGlobal('fetch', fetch)
    const response = await middleware(request('https://tenant.example/settings'))
    expect(response.headers.get('X-Robots-Tag')).toBe(APP_ROBOTS_DIRECTIVE)
    expect(response.cookies.get('latexy_tenant_slug')?.value).toBe('synthetic-tenant')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('does not accidentally noindex a public custom-domain portfolio rewrite', async () => {
    vi.stubEnv('BACKEND_URL', 'https://backend.example')
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ tenant: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ username: 'alex' })))
    vi.stubGlobal('fetch', fetch)
    const response = await middleware(request('https://cv.example/settings'))
    expect(response.headers.get('x-middleware-rewrite')).toBe('https://cv.example/u/alex')
    expect(response.headers.get('X-Robots-Tag')).toBeNull()
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('retains the private-page directive when custom-host resolution fails', async () => {
    vi.stubEnv('BACKEND_URL', 'https://backend.example')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Synthetic resolver outage')))
    const response = await middleware(request('https://unknown.example/workspaces'))
    expect(response.headers.get('X-Robots-Tag')).toBe(APP_ROBOTS_DIRECTIVE)
  })

  it('keeps robots coverage aligned and auth-only routes out of the public sitemap', async () => {
    vi.stubEnv('NEXT_PUBLIC_APP_URL', 'https://resume.example')
    const rules = robots().rules
    expect(Array.isArray(rules)).toBe(false)
    expect(rules).toMatchObject({
      userAgent: '*',
      allow: '/',
      disallow: ['/api/', '/r/', ...NON_INDEXABLE_APP_ROOTS],
    })
    const paths = sitemap().map(item => new URL(item.url).pathname)
    expect(paths).toEqual(['/', '/platform', '/templates', '/pricing', '/resources', '/faq', '/updates'])
    expect(paths.some(isNonIndexableAppPath)).toBe(false)
    const body = await llms().text()
    expect(body).toContain('[Developer tools](https://resume.example/developer): Account-only')
    expect(body).toContain('Sign in to use this portal')
    expect(body).toContain('https://resume.example/try?mode=visual')
  })
})
