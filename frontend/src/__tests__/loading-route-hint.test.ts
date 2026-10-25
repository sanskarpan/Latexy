import { NextRequest } from 'next/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { middleware } from '@/middleware'

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs() })

describe('presentation-only loading route hint', () => {
  it('overwrites a spoofed hint with the requested application pathname', async () => {
    const request = new NextRequest('https://latexy.xyz/pricing', {
      headers: { host: 'latexy.xyz', 'x-latexy-route-pathname': '/updates' },
    })
    const response = await middleware(request)
    expect(response.headers.get('x-middleware-request-x-latexy-route-pathname')).toBe('/pricing')
  })

  it('forwards the actual updates pathname on the app host', async () => {
    const response = await middleware(new NextRequest('https://latexy.xyz/updates', {
      headers: { host: 'latexy.xyz' },
    }))
    expect(response.headers.get('x-middleware-request-x-latexy-route-pathname')).toBe('/updates')
  })

  it('uses the rewritten portfolio destination rather than the incoming updates path', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce(Response.json({ tenant: null }))
      .mockResolvedValueOnce(Response.json({ username: 'alice' })))
    const response = await middleware(new NextRequest('https://portfolio.example/updates', {
      headers: { host: 'portfolio.example', 'x-latexy-route-pathname': '/updates' },
    }))
    expect(response.headers.get('x-middleware-rewrite')).toBe('https://portfolio.example/u/alice')
    expect(response.headers.get('x-middleware-request-x-latexy-route-pathname')).toBe('/u/alice')
  })
})
