import { createHash } from 'node:crypto'
import { readFileSync, readdirSync } from 'node:fs'
import type { Page, Route } from '@playwright/test'
import { describe, expect, it, vi } from 'vitest'
import { QUALITY_FEATURES } from '../../e2e/quality/mock-api'
import { installMockWorkboxRegistration } from '../../e2e/helpers/mock-workbox-registration'
import { captureClipboardText, fulfillEngineResponse, mockEngineRoute, mockEngineAncillaryApi, mockPublicEngineDocument } from '../../e2e/quality/engine-fixtures'

function mockedPage() {
  const register = vi.fn()
  return { page: { route: register } as unknown as Page, register }
}

function mockedRoute(url: string, resourceType = 'fetch', headers: Record<string, string> = {}, method = 'GET') {
  const fulfill = vi.fn()
  const fallback = vi.fn()
  const route = {
    request: () => ({ url: () => url, resourceType: () => resourceType, headers: () => headers, method: () => method }),
    fulfill, fallback,
  } as unknown as Route
  return { route, fulfill, fallback }
}

describe('isolated engine browser fixtures', () => {
  it('returns a valid closed feature map and honors only explicit suite overrides', async () => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page, 'fixture-owner')
    const [, handle] = register.mock.calls[0]
    const r = mockedRoute('http://127.0.0.1:7182/config/entitlements')
    await handle(r.route)
    const defaults = r.fulfill.mock.calls[0][0].json.features
    expect(defaults).toEqual(QUALITY_FEATURES)
    expect(defaults).toMatchObject({ b08: false, b10: false, c06: false, d01: false, d18: false })
    expect(defaults.unknown_feature).toBeUndefined()

    const overridden = mockedPage()
    await mockEngineAncillaryApi(overridden.page, 'fixture-owner', { b10: true, c06: true, b06: false })
    const deniedImport = mockedRoute('http://127.0.0.1:7182/config/entitlements')
    await overridden.register.mock.calls[0][1](deniedImport.route)
    expect(deniedImport.fulfill.mock.calls[0][0].json.features).toMatchObject({ b10: true, c06: true, b06: false, d01: false, d18: false })
    expect(QUALITY_FEATURES).toMatchObject({ b10: false, c06: false, b06: true })
  })

  it('rejects unknown feature overrides before registering a route', async () => {
    const { page, register } = mockedPage()
    await expect(mockEngineAncillaryApi(page, 'fixture-owner', { unknown_feature: true }))
      .rejects.toThrow('Unknown quality capability: unknown_feature')
    expect(register).not.toHaveBeenCalled()
  })

  it('answers preflight before body reads, mutation counters or handler side effects', async () => {
    const { page, register } = mockedPage()
    const mutation = vi.fn()
    await mockEngineRoute(page, '**/resumes/fixture/engine/document', mutation)
    const [, handle] = register.mock.calls[0]
    const r = mockedRoute('http://127.0.0.1:7182/resumes/fixture/engine/document', 'fetch', {
      origin: 'http://localhost:5182', 'access-control-request-headers': 'authorization,content-type,x-device-fingerprint',
    }, 'OPTIONS')
    await handle(r.route)
    expect(mutation).not.toHaveBeenCalled()
    expect(r.fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 204, body: '', headers: expect.objectContaining({
      'access-control-allow-origin': 'http://localhost:5182', 'access-control-allow-credentials': 'true',
      'access-control-allow-headers': 'authorization,content-type,x-device-fingerprint',
    }) }))
  })

  it('uses credentialed CORS and preserves the binary PDF content type', async () => {
    const r = mockedRoute('http://127.0.0.1:7182/download/fixture', 'fetch', { origin: 'http://localhost:5182' })
    const body = Buffer.from('%PDF-fixture')
    await fulfillEngineResponse(r.route, { contentType: 'application/pdf', body })
    expect(r.fulfill).toHaveBeenCalledWith(expect.objectContaining({ contentType: 'application/pdf', body,
      headers: expect.objectContaining({ 'content-type': 'application/pdf', 'access-control-allow-origin': 'http://localhost:5182', 'access-control-allow-credentials': 'true' }),
    }))
  })

  it('protects every new engine API fixture with the preflight wrapper', () => {
    for (const file of ['engine-rollout-fallback', 'new-resume-latency', 'pdf-import-flow', 'resume-engine-preview', 'resume-preview-recovery', 'resume-structure-flow']) {
      const source = readFileSync(new URL(`../../e2e/quality/${file}.spec.ts`, import.meta.url), 'utf8')
      expect(source, file).toContain('mockEngineRoute(page, ')
      expect(source, file).not.toContain('await page.route(')
      expect(source, file).not.toContain('route.fulfill(')
    }
  })

  it.each([7182, 7483, 8030, 8530])('mocks ancillary API calls on backend port %s', async port => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page, 'fixture-owner')
    const [matches, handle] = register.mock.calls[0]
    const url = `http://127.0.0.1:${port}/me`
    expect(matches(new URL(url))).toBe(true)
    expect(matches(new URL(`http://127.0.0.1:${port}/jobs/submit`))).toBe(false)
    const { route, fulfill } = mockedRoute(url)
    await handle(route)
    expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ json: { id: 'fixture-owner', preferences: { has_onboarded: true } } }))
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

  it.each([
    ['/github/status', { connected: false }],
    ['/dropbox/status', { connected: false }],
    ['/subscription/current', { planId: 'free' }],
    ['/ws/ticket', { ticket: 'contract-ticket' }],
    ['/resumes/fixture-id/academic-cv-report', { is_academic_cv: false }],
  ])('mocks known editor dependencies without catching engine mutations: %s', async (path, expected) => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page)
    const [matches, handle] = register.mock.calls[0]
    const url = `http://127.0.0.1:7182${path}`
    expect(matches(new URL(url))).toBe(true)
    expect(matches(new URL('http://127.0.0.1:7182/resumes/fixture-id/engine/structure'))).toBe(false)
    expect(matches(new URL('http://127.0.0.1:7182/resumes/fixture-id/engine/document'))).toBe(false)
    const { route, fulfill } = mockedRoute(url)
    await handle(route)
    expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ json: expect.objectContaining(expected) }))
  })

  it('acknowledges synthetic telemetry beacons and explicitly omits optional SyncTeX', async () => {
    const { page, register } = mockedPage()
    await mockEngineAncillaryApi(page)
    const [matches, handle] = register.mock.calls[0]
    for (const path of ['/telemetry/frontend', '/analytics/track/compilation?compilation_id=fixture', '/analytics/track/feature-usage?feature=compile']) {
      const url = `http://127.0.0.1:7182${path}`
      expect(matches(new URL(url))).toBe(true)
      const { route, fulfill } = mockedRoute(url, 'ping')
      await handle(route)
      expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 204 }))
    }
    const url = 'http://127.0.0.1:7182/download/fixture/preview/artifact/synctex'
    expect(matches(new URL(url))).toBe(true)
    const { route, fulfill } = mockedRoute(url)
    await handle(route)
    expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 404, json: expect.any(Object) }))
  })

  it('installs the existing Workbox registration stub for every quality contract only', () => {
    const qualityDir = new URL('../../e2e/quality/', import.meta.url)
    const fixture = readFileSync(new URL('quality-test.ts', qualityDir), 'utf8')
    expect(fixture).toContain('context: async ({ context }, runTest)')
    expect(fixture).toContain('await installMockWorkboxRegistration(context)')
    for (const file of readdirSync(qualityDir).filter(file => file.endsWith('.spec.ts'))) {
      expect(readFileSync(new URL(file, qualityDir), 'utf8')).toContain("from './quality-test'")
    }
    const pwa = readFileSync(new URL('../../e2e/pwa-production.spec.ts', import.meta.url), 'utf8')
    expect(pwa).toContain("from '@playwright/test'")
    expect(pwa).toContain('navigator.serviceWorker.ready')
  })

  it.each(['about:blank', 'http://localhost:5182/try', 'https://example.test/workspace'])('stubs Workbox safely on every context page: %s', async href => {
    const addInitScript = vi.fn()
    await installMockWorkboxRegistration({ addInitScript } as unknown as Page)
    const navigatorMock: { serviceWorker?: { register(): Promise<{ scope: string }> } } = {}
    try {
      vi.stubGlobal('window', { location: new URL(href) })
      vi.stubGlobal('navigator', navigatorMock)
      addInitScript.mock.calls[0][0]()
      expect(await navigatorMock.serviceWorker?.register()).toMatchObject({
        scope: href === 'about:blank' ? href : new URL('/', href).href,
      })
    } finally { vi.unstubAllGlobals() }
  })

  it('captures Copy text while preserving native rich clipboard writes and their promise handling', async () => {
    const evaluate = vi.fn()
    await captureClipboardText({ evaluate } as unknown as Page)
    const write = vi.fn()
    const clipboard = { write, writeText: vi.fn() }
    const windowMock: { copiedLatex?: string } = {}
    try {
      vi.stubGlobal('window', windowMock)
      vi.stubGlobal('navigator', { clipboard })
      evaluate.mock.calls[0][0]()
      expect(navigator.clipboard).toBe(clipboard)
      expect(navigator.clipboard.write).toBe(write)
      await navigator.clipboard.writeText('Preserved synthetic source')
      expect(windowMock.copiedLatex).toBe('Preserved synthetic source')
    } finally { vi.unstubAllGlobals() }
  })

  it('binds a public layout projection to the actual submitted source', async () => {
    const { page, register } = mockedPage()
    await mockPublicEngineDocument(page)
    const [pattern, handle] = register.mock.calls[0]
    expect(pattern).toBe('**/public/engine/document')
    const latex_content = 'synthetic layout source'
    const fulfill = vi.fn()
    await handle({ request: () => ({ method: () => 'POST', headers: () => ({}), postDataJSON: () => ({ latex_content }) }), fulfill })
    expect(fulfill).toHaveBeenCalledWith(expect.objectContaining({ json: {
      latex_content,
      document: {
        document_id: 'guest', source_mode: 'imported', content_revision: 1,
        source_sha256: createHash('sha256').update(latex_content).digest('hex'),
        structured_version: null, template_id: null, nodes: [], opaque_blocks: [], containers: [],
      },
    } }))
  })
})
