import type { Page, Response as PageResponse } from '@playwright/test'
import { describe, expect, it, vi } from 'vitest'
import { digest, observeRealPreview, semanticFieldHitTarget } from '../../e2e/real-preview/observe-real-preview'
import type { BrowserPdfCapture } from '../../e2e/real-preview/capture-browser-pdf'

const origin = 'http://127.0.0.1:8030'
const jobId = '11111111-1111-4111-8111-111111111111'
const artifactId = 'a'.repeat(64)
const pdfBytes = Buffer.from([37, 80, 68, 70, 45, 0, 255, 128, 10])
const fingerprint = 'synthetic-unit-device'
const requestId = 'synthetic-unit-request'

function browserCapture(overrides: Partial<BrowserPdfCapture> = {}): BrowserPdfCapture {
  return { jobId, artifactId, fingerprint, requestId, status: 200, deadlineAt: Date.now() + 10_000,
    bodyBytes: pdfBytes.length, bodyBase64: pdfBytes.toString('base64'), ...overrides }
}

function pageResponse(options: { method?: string; jobId?: string; artifactId?: string; fingerprint?: string;
  requestId?: string; status?: number; kind?: 'pdf' | 'geometry' | 'synctex'; foreignOrigin?: boolean; fromServiceWorker?: boolean;
  body?: Buffer; bodyFailure?: boolean } = {}) {
  const kind = options.kind ?? 'pdf'
  const body = vi.fn(async () => {
    if (options.bodyFailure) throw new Error('synthetic response body must not escape')
    return options.body ?? pdfBytes
  })
  const response = { url: () => `${options.foreignOrigin ? 'http://example.invalid' : origin}/download/${options.jobId ?? jobId}/preview/${options.artifactId ?? artifactId}${kind === 'pdf' ? '' : `/${kind}`}`,
    status: () => options.status ?? 200, ok: () => (options.status ?? 200) === 200,
    headers: () => ({ 'content-type': kind === 'pdf' ? 'application/pdf' : kind === 'geometry' ? 'application/json' : 'text/plain',
      'content-length': String((options.body ?? pdfBytes).length), 'content-encoding': 'identity' }),
    request: () => ({ method: () => options.method ?? 'GET', resourceType: () => 'fetch',
      headers: () => ({ 'x-device-fingerprint': options.fingerprint ?? fingerprint, 'x-request-id': options.requestId ?? requestId }) }),
    fromServiceWorker: () => options.fromServiceWorker ?? false, body } as unknown as PageResponse
  return { response, body }
}

async function observer() {
  const get = vi.fn(async () => ({ ok: (): boolean => true, json: async () => ({ status: 'completed' }) }))
  const handlers = new Map<string, (value: unknown) => void>()
  let receive = (_value: BrowserPdfCapture) => {}
  const evaluate = vi.fn(async (): Promise<string[]> => [])
  const disposeBinding = vi.fn(async () => {})
  const disposeInit = vi.fn(async () => {})
  const page = { on: (event: string, handler: (value: unknown) => void) => handlers.set(event, handler), request: { get },
    exposeFunction: async (_name: string, callback: typeof receive) => { receive = callback; return { dispose: disposeBinding } },
    addInitScript: vi.fn(async () => ({ dispose: disposeInit })),
    evaluate } as unknown as Page
  return { observed: await observeRealPreview(page, origin), get, handlers, receive: (value: BrowserPdfCapture) => receive(value), evaluate,
    disposeBinding, disposeInit }
}

describe('real preview observational state reads', () => {
  it('carries only the exact observed admission fingerprint with a bounded request', async () => {
    const { observed, get } = await observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'synthetic-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    expect(await observed.completedState(jobId)).toBe('completed')
    expect(get).toHaveBeenCalledExactlyOnceWith(`${origin}/jobs/${jobId}/state`, {
      headers: { 'X-Device-Fingerprint': 'synthetic-unit-device' }, timeout: 15_000,
    })
  })

  it('refuses unknown jobs or missing identities before any request', async () => {
    const { observed, get } = await observer()
    await expect(observed.completedState(jobId)).rejects.toThrow(/observed guest admission identity/)
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: '',
      status: 200, jobType: 'latex_compilation', jobId })
    await expect(observed.completedState(jobId)).rejects.toThrow(/observed guest admission identity/)
    expect(get).not.toHaveBeenCalled()
  })

  it('does not borrow another observed job identity for state reads', async () => {
    const { observed, get } = await observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'first-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    const otherJobId = '22222222-2222-4222-8222-222222222222'
    await expect(observed.completedState(otherJobId)).rejects.toThrow(/observed guest admission identity/)
    expect(get).not.toHaveBeenCalled()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'second-unit-device',
      status: 200, jobType: 'latex_compilation', jobId: otherJobId })
    await observed.completedState(otherJobId)
    expect(get).toHaveBeenCalledExactlyOnceWith(`${origin}/jobs/${otherJobId}/state`, {
      headers: { 'X-Device-Fingerprint': 'second-unit-device' }, timeout: 15_000,
    })
  })

  it('keeps failed state reads as failures without reporting their response contents', async () => {
    const { observed, get } = await observer()
    observed.admissions.push({ source: 'synthetic unit source', fingerprint: 'synthetic-unit-device',
      status: 200, jobType: 'latex_compilation', jobId })
    get.mockResolvedValue({ ok: () => false, json: async () => ({ status: 'failed' }) })
    await expect(observed.completedState(jobId)).rejects.toThrow('The real job state could not be read')
  })

  it('uses one exact semantic hit target when the same field wraps into multiple overlays', async () => {
    const lineTargets = [{ focus: vi.fn() }, { focus: vi.fn() }]
    const getByRole = vi.fn(() => ({ first: () => lineTargets[0] }))
    const target = semanticFieldHitTarget({ getByRole } as unknown as Page, 'synthetic wrapped field')
    await target.focus()
    expect(getByRole).toHaveBeenCalledExactlyOnceWith('button', {
      name: 'Edit resume field: synthetic wrapped field', exact: true,
    })
    expect(target).toBe(lineTargets[0])
    expect(lineTargets[0].focus).toHaveBeenCalledOnce()
    expect(lineTargets[1].focus).not.toHaveBeenCalled()
  })
})

describe('original browser PDF byte capture and real network correlation', () => {
  it('accepts exact binary bytes only with matching real GET metadata, never reading CDP PDF body', async () => {
    const { observed, handlers, receive, get } = await observer()
    const { response, body } = pageResponse()
    receive(browserCapture()) // Delivery and Playwright metadata can arrive in either order.
    expect(observed.preview(jobId, artifactId, 'pdf')).toBeUndefined()
    handlers.get('response')!(response)
    await observed.settle()
    expect(observed.preview(jobId, artifactId, 'pdf')?.body).toEqual(pdfBytes)
    expect(digest(observed.preview(jobId, artifactId, 'pdf')!.body)).toBe(digest(pdfBytes))
    expect(body).not.toHaveBeenCalled()
    expect(get).not.toHaveBeenCalled() // No second network fetch replaces the observed bytes.
    expect(observed.transferDiagnostics().responses[0]).toMatchObject({ method: 'GET', status: 200,
      body_bytes: pdfBytes.length, body_sha256: digest(pdfBytes), from_service_worker: false,
      capture_channel: 'original-browser-response-clone' })
  })

  it.each([
    { method: 'OPTIONS' }, { method: 'HEAD' }, { status: 403 }, { foreignOrigin: true },
    { fingerprint: 'another-device' }, { requestId: 'another-request' },
    { jobId: '22222222-2222-4222-8222-222222222222' }, { artifactId: 'b'.repeat(64) },
  ])('cannot select PDF bytes against mismatched network metadata %j', async options => {
    const { observed, handlers, receive } = await observer()
    const { response, body } = pageResponse(options)
    handlers.get('response')!(response)
    receive(browserCapture())
    await observed.settle()
    expect(observed.preview(jobId, artifactId, 'pdf')).toBeUndefined()
    expect(body).not.toHaveBeenCalled()
  })

  it.each([
    { bodyBytes: 0, bodyBase64: '' }, { bodyBytes: 9, bodyBase64: Buffer.from('not-a-pdf').toString('base64') },
    { bodyBytes: pdfBytes.length + 1 }, { bodyBytes: -1 }, { bodyBytes: 20 * 1024 * 1024 + 1 },
    { bodyBase64: '$invalid' }, { status: 403 }, { fingerprint: '' }, { requestId: '' },
    { jobId: 'invalid-job' }, { artifactId: 'invalid-artifact' }, { deadlineAt: Date.now() - 1 },
  ])('keeps invalid or late received bytes fatal rather than selecting/refetching them %j', async overrides => {
    const { observed, handlers, receive, get } = await observer()
    handlers.get('response')!(pageResponse().response)
    receive(browserCapture(overrides))
    await observed.settle()
    expect(observed.captureErrors.length).toBeGreaterThan(0)
    expect(() => observed.preview(jobId, artifactId, 'pdf')).toThrow('The original browser artifact capture failed')
    expect(get).not.toHaveBeenCalled()
  })

  it('records actual Playwright service-worker metadata rather than inventing it from Fetch Response', async () => {
    const { observed, handlers, receive } = await observer()
    handlers.get('response')!(pageResponse({ fromServiceWorker: true }).response)
    receive(browserCapture())
    await observed.settle()
    expect(observed.transferDiagnostics().responses[0].from_service_worker).toBe(true)
  })

  it('retains the empty original-byte failure in bounded redacted diagnostics', async () => {
    const { observed, handlers, receive } = await observer()
    handlers.get('response')!(pageResponse().response)
    receive(browserCapture({ bodyBytes: 0, bodyBase64: '' }))
    await observed.settle()
    const diagnostics = observed.transferDiagnostics()
    expect(diagnostics.responses[0].body_bytes).toBe(0)
    expect(diagnostics.responses[0].body_sha256).toBe(digest(Buffer.alloc(0)))
    expect(JSON.stringify(diagnostics)).not.toContain(fingerprint)
    expect(JSON.stringify(diagnostics)).not.toContain(requestId)
    expect(JSON.stringify(diagnostics)).not.toContain(jobId)
    expect(JSON.stringify(diagnostics)).not.toContain(origin)
  })

  it('keeps a browser deadline fatal even if a later callback carries apparently valid bytes', async () => {
    const { observed, handlers, receive, evaluate } = await observer()
    handlers.get('response')!(pageResponse().response)
    evaluate.mockResolvedValue(['pdf_capture_deadline'])
    await observed.settle()
    receive(browserCapture())
    expect(() => observed.preview(jobId, artifactId, 'pdf')).toThrow(/capture failed/)
    expect(observed.captureErrors).toEqual(['pdf_capture_deadline'])
  })

  it('redacts unrecognized binding error text even when it resembles a capture code', async () => {
    const { observed, receive } = await observer()
    receive(browserCapture({ error: 'pdf_capture_private_secret' }))
    expect(observed.captureErrors).toEqual(['pdf_capture_failure'])
  })

  it('still captures genuine geometry/SyncTeX bodies and makes their capture failures fatal', async () => {
    const { observed, handlers } = await observer()
    const { response, body } = pageResponse({ kind: 'geometry', body: Buffer.from('{"boxes":[]}') })
    handlers.get('response')!(response)
    await observed.settle()
    expect(body).toHaveBeenCalledOnce()
    expect(observed.preview(jobId, artifactId, 'geometry')?.geometry).toEqual({ boxes: [] })
    handlers.get('response')!(pageResponse({ kind: 'synctex', bodyFailure: true }).response)
    await observed.settle()
    expect(observed.captureErrors).toEqual(['artifact_capture'])
    expect(() => observed.preview(jobId, artifactId, 'geometry')).toThrow(/capture failed/)
  })

  it('records failed requests without leaking their URL or response contents', async () => {
    const { observed, handlers } = await observer()
    handlers.get('requestfailed')!({ url: () => `${origin}/download/${jobId}/preview/${artifactId}`, method: () => 'GET' })
    expect(observed.transferDiagnostics().failed_requests).toEqual([{ kind: 'pdf', method: 'GET' }])
  })

  it('uses supported owned-handle disposal and ignores deliveries after disposal', async () => {
    const { observed, receive, evaluate, disposeBinding, disposeInit } = await observer()
    await observed.dispose()
    expect(evaluate).toHaveBeenCalledTimes(2)
    expect(disposeBinding).toHaveBeenCalledOnce()
    expect(disposeInit).toHaveBeenCalledOnce()
    receive(browserCapture())
    expect(observed.previews).toEqual([])
  })

  it('keeps a settle or cleanup failure fatal while disposing both owned handles', async () => {
    const { observed, evaluate, disposeBinding, disposeInit } = await observer()
    evaluate.mockRejectedValue(new Error('synthetic page failure'))
    await observed.dispose()
    expect(observed.captureErrors).toEqual(['pdf_capture_settle_failure', 'pdf_capture_cleanup_failure'])
    expect(disposeBinding).toHaveBeenCalledOnce()
    expect(disposeInit).toHaveBeenCalledOnce()
  })

  it('attempts binding disposal even if init-script disposal fails', async () => {
    const { observed, disposeBinding, disposeInit } = await observer()
    disposeInit.mockRejectedValue(new Error('synthetic disposal failure'))
    await observed.dispose()
    expect(disposeBinding).toHaveBeenCalledOnce()
    expect(observed.captureErrors).toEqual(['pdf_capture_cleanup_failure'])
  })

  it('limits callback delivery and exposes no selectable success after count overflow', async () => {
    const { observed, receive } = await observer()
    for (let index = 0; index < 100; index++) receive(browserCapture())
    expect(observed.previews).toHaveLength(7)
    expect(observed.captureErrors).toEqual(['pdf_capture_count_limit'])
    expect(() => observed.preview(jobId, artifactId, 'pdf')).toThrow(/capture failed/)
  })
})
