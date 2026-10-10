import { createHash } from 'node:crypto'
import type { Page, Route } from '@playwright/test'
import { describe, expect, it, vi } from 'vitest'
import { mockEngineAncillaryApi, mockPublicEngineDocument } from '../../e2e/quality/engine-fixtures'

function mockedPage() {
  const register = vi.fn()
  return { page: { route: register } as unknown as Page, register }
}

function mockedRoute(url: string, resourceType = 'fetch', headers: Record<string, string> = {}) {
  const fulfill = vi.fn()
  const fallback = vi.fn()
  const route = {
    request: () => ({ url: () => url, resourceType: () => resourceType, headers: () => headers }),
    fulfill, fallback,
  } as unknown as Route
  return { route, fulfill, fallback }
}

describe('isolated engine browser fixtures', () => {
  it.each([7182, 7483, 8030, 8530])('mocks ancillary API calls on backend port %s', async port => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page, 'fixture-owner')
    const [matches, handle] = register.mock.calls[0]
    const url = `http://127.0.0.1:${port}/me`
    expect(matches(new URL(url))).toBe(true)
    expect(matches(new URL(`http://127.0.0.1:${port}/jobs/submit`))).toBe(false)
    const { route, fulfill } = mockedRoute(url)
    await handle(route)
    expect(fulfill).toHaveBeenCalledWith({ json: { id: 'fixture-owner', preferences: { has_onboarded: true } } })
  })

  it.each([
    ['document', {}],
    ['fetch', { rsc: '1' }],
  ] as const)('does not replace a Next templates navigation (%s)', async (resourceType, headers) => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page)
    const [, handle] = register.mock.calls[0]
    const { route, fulfill, fallback } = mockedRoute('http://localhost:5182/templates', resourceType, headers)
    await handle(route)
    expect(fallback).toHaveBeenCalledOnce()
    expect(fulfill).not.toHaveBeenCalled()
  })

  it('binds a public layout projection to the actual submitted source', async () => {
    const { page, register } = mockedPage()
    await mockPublicEngineDocument(page)
    const [pattern, handle] = register.mock.calls[0]
    expect(pattern).toBe('**/public/engine/document')
    const latex_content = 'synthetic layout source'
    const fulfill = vi.fn()
    await handle({ request: () => ({ postDataJSON: () => ({ latex_content }) }), fulfill })
    expect(fulfill).toHaveBeenCalledWith({ json: {
      latex_content,
      document: {
        document_id: 'guest', source_mode: 'imported', content_revision: 1,
        source_sha256: createHash('sha256').update(latex_content).digest('hex'),
        structured_version: null, template_id: null, nodes: [], opaque_blocks: [], containers: [],
      },
    } })
  })
})
