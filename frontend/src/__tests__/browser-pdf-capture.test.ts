import { afterEach, describe, expect, it, vi } from 'vitest'
import { installBrowserPdfCapture, type BrowserPdfCapture, type PdfCaptureController } from '../../e2e/real-preview/capture-browser-pdf'

const origin = 'http://127.0.0.1:8030'
const url = `${origin}/download/11111111-1111-4111-8111-111111111111/preview/${'a'.repeat(64)}`
const bytes = new Uint8Array([37, 80, 68, 70, 45, 0, 255, 128, 10])
const headers = { 'X-Device-Fingerprint': 'synthetic-unit-device', 'X-Request-ID': 'synthetic-unit-request' }

function response(options: { status?: number; type?: string; url?: string } = {}) {
  const value = new Response(bytes, { status: options.status ?? 200,
    headers: { 'Content-Type': options.type ?? 'application/pdf' } })
  Object.defineProperty(value, 'url', { value: options.url ?? url })
  return value
}

function setup(value: Response, options: { maxBytes?: number; maxCaptures?: number; deadlineMs?: number; hungBinding?: boolean } = {}) {
  const delivered: BrowserPdfCapture[] = []
  const native = vi.fn<typeof fetch>(async () => value)
  const binding = vi.fn(async (capture: BrowserPdfCapture) => {
    delivered.push(capture)
    if (options.hungBinding) await new Promise<void>(() => {})
  })
  const target = { fetch: native, location: { href: `${origin}/try` }, receivePdf: binding,
    __latexyRealPreviewCapture: undefined as PdfCaptureController | undefined }
  vi.stubGlobal('window', target)
  installBrowserPdfCapture({ apiOrigin: origin, bindingName: 'receivePdf', maxBytes: options.maxBytes ?? 1024,
    maxCaptures: options.maxCaptures ?? 6, deadlineMs: options.deadlineMs ?? 1000 })
  return { target, native, delivered, binding, controller: target.__latexyRealPreviewCapture! }
}

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

describe('bounded original browser PDF response observation', () => {
  it('calls native fetch once and returns its identical consumable Response with exact binary clone bytes', async () => {
    const original = response()
    const { target, native, delivered, controller } = setup(original)
    const received = await target.fetch(url, { headers })
    expect(received).toBe(original)
    expect(new Uint8Array(await (await received.blob()).arrayBuffer())).toEqual(bytes)
    expect(await controller.settle()).toEqual([])
    expect(native).toHaveBeenCalledExactlyOnceWith(url, { headers })
    expect(delivered).toHaveLength(1)
    expect(Buffer.from(delivered[0].bodyBase64!, 'base64')).toEqual(Buffer.from(bytes))
    expect(delivered[0]).toMatchObject({ bodyBytes: bytes.length, fingerprint: headers['X-Device-Fingerprint'],
      requestId: headers['X-Request-ID'], status: 200 })
    controller.cleanup()
    expect(target.fetch).toBe(native)
    expect(target.__latexyRealPreviewCapture).toBeUndefined()
  })

  it('uses effective Request headers and init overrides without consuming the original request or response', async () => {
    const { target, delivered, controller } = setup(response())
    const request = new Request(url, { headers: { 'X-Device-Fingerprint': 'old-device', 'X-Request-ID': 'old-request' } })
    const original = await target.fetch(request, { headers })
    await original.arrayBuffer()
    expect(await controller.settle()).toEqual([])
    expect(delivered[0]).toMatchObject({ fingerprint: headers['X-Device-Fingerprint'], requestId: headers['X-Request-ID'] })
    controller.cleanup()
  })

  it.each([
    ['HEAD', url], ['OPTIONS', url], ['GET', url.replace('127.0.0.1', 'example.invalid')],
    ['GET', `${url}/geometry`], ['GET', `${url}?secret=ignored`], ['GET', url.replace('/preview/', '/other/')],
  ])('ignores unrelated %s transfers and never clones them', async (method, requestedUrl) => {
    const original = response({ url: requestedUrl })
    const clone = vi.spyOn(original, 'clone')
    const { target, native, delivered, controller } = setup(original)
    expect(await target.fetch(requestedUrl, { method, headers })).toBe(original)
    expect(await controller.settle()).toEqual([])
    expect(native).toHaveBeenCalledOnce()
    expect(clone).not.toHaveBeenCalled()
    expect(delivered).toEqual([])
    controller.cleanup()
  })

  it('honors an init method override and refuses redirected response identity', async () => {
    const original = response({ url: url.replace('a'.repeat(64), 'b'.repeat(64)) })
    const clone = vi.spyOn(original, 'clone')
    const { target, delivered, controller } = setup(original)
    await target.fetch(new Request(url), { method: 'HEAD', headers })
    await target.fetch(url, { headers })
    expect(await controller.settle()).toEqual([])
    expect(clone).not.toHaveBeenCalled()
    expect(delivered).toEqual([])
    controller.cleanup()
  })

  it.each([
    [{ status: 403 }, 'pdf_capture_http_status'], [{ type: 'text/html' }, 'pdf_capture_content_type'],
  ])('makes an invalid owned response a fatal bounded capture error', async (options, error) => {
    const original = response(options)
    const { target, native, delivered, controller } = setup(original)
    expect(await target.fetch(url, { headers })).toBe(original)
    expect(new Uint8Array(await original.arrayBuffer())).toEqual(bytes)
    expect(await controller.settle()).toEqual([error])
    expect(delivered).toHaveLength(1)
    expect(delivered[0].error).toBe(error)
    expect(delivered[0].bodyBase64).toBeUndefined()
    expect(native).toHaveBeenCalledOnce()
    controller.cleanup()
  })

  it('fails a clone exception without leaking exception contents or issuing another request', async () => {
    const original = response()
    vi.spyOn(original, 'clone').mockImplementation(() => { throw new Error('pdf_capture_private_secret') })
    const { target, native, delivered, controller } = setup(original)
    expect(await target.fetch(url, { headers })).toBe(original)
    expect(await controller.settle()).toEqual(['pdf_capture_read_failure'])
    expect(JSON.stringify(delivered)).not.toContain('private_secret')
    expect(native).toHaveBeenCalledOnce()
    expect(new Uint8Array(await original.arrayBuffer())).toEqual(bytes)
    controller.cleanup()
  })

  it('cancels an over-limit clone before releasing its reader and preserves the original body', async () => {
    const original = response()
    const order: string[] = []
    const reader = { read: vi.fn(async () => ({ done: false, value: bytes })),
      cancel: vi.fn(async () => { order.push('cancel') }), releaseLock: vi.fn(() => { order.push('release') }) }
    vi.spyOn(original, 'clone').mockReturnValue({ body: { getReader: () => reader } } as unknown as Response)
    const { target, native, delivered, controller } = setup(original, { maxBytes: 5 })
    expect(await target.fetch(url, { headers })).toBe(original)
    expect(await controller.settle()).toEqual(['pdf_capture_byte_limit'])
    expect(order.indexOf('cancel')).toBeLessThan(order.indexOf('release'))
    expect(delivered.every(value => value.bodyBase64 === undefined)).toBe(true)
    expect(native).toHaveBeenCalledOnce()
    expect(new Uint8Array(await original.arrayBuffer())).toEqual(bytes)
    controller.cleanup()
  })

  it('bounds a delayed stream, cancels it, and cannot emit late partial success', async () => {
    vi.useFakeTimers()
    const original = response()
    const order: string[] = []
    let finish!: (value: { done: boolean; value?: Uint8Array }) => void
    const reader = { read: vi.fn(() => new Promise(resolve => { finish = resolve })),
      cancel: vi.fn(async () => { order.push('cancel') }), releaseLock: vi.fn(() => { order.push('release') }) }
    vi.spyOn(original, 'clone').mockReturnValue({ body: { getReader: () => reader } } as unknown as Response)
    const { target, delivered, controller } = setup(original, { deadlineMs: 10 })
    expect(await target.fetch(url, { headers })).toBe(original)
    await vi.advanceTimersByTimeAsync(10)
    expect(await controller.settle()).toEqual(['pdf_capture_deadline'])
    expect(reader.cancel).toHaveBeenCalled()
    finish({ done: true })
    await Promise.resolve(); await Promise.resolve()
    expect(delivered).toHaveLength(1)
    expect(delivered[0].error).toBe('pdf_capture_deadline')
    expect(reader.releaseLock).toHaveBeenCalledOnce()
    expect(order.indexOf('cancel')).toBeLessThan(order.indexOf('release'))
    controller.cleanup()
  })

  it('cancels a failed read before releasing its lock and reports only a safe error code', async () => {
    const original = response()
    const order: string[] = []
    const reader = { read: vi.fn(async () => { throw new Error('private stream failure') }),
      cancel: vi.fn(async () => { order.push('cancel') }), releaseLock: vi.fn(() => { order.push('release') }) }
    vi.spyOn(original, 'clone').mockReturnValue({ body: { getReader: () => reader } } as unknown as Response)
    const { target, delivered, controller } = setup(original)
    expect(await target.fetch(url, { headers })).toBe(original)
    expect(await controller.settle()).toEqual(['pdf_capture_read_failure'])
    expect(order.indexOf('cancel')).toBeLessThan(order.indexOf('release'))
    expect(JSON.stringify(delivered)).not.toContain('private stream failure')
    controller.cleanup()
  })

  it('restores native fetch and cancels active reads on disposal without later delivery', async () => {
    const original = response()
    let finish!: (value: { done: boolean }) => void
    const reader = { read: vi.fn(() => new Promise(resolve => { finish = resolve })),
      cancel: vi.fn(async () => {}), releaseLock: vi.fn() }
    vi.spyOn(original, 'clone').mockReturnValue({ body: { getReader: () => reader } } as unknown as Response)
    const { target, native, delivered, controller } = setup(original)
    expect(await target.fetch(url, { headers })).toBe(original)
    controller.cleanup()
    expect(target.fetch).toBe(native)
    expect(reader.cancel).toHaveBeenCalledOnce()
    finish({ done: true })
    expect(await controller.settle()).toEqual([])
    expect(delivered).toEqual([])
    expect(reader.releaseLock).toHaveBeenCalledOnce()
    expect(new Uint8Array(await original.arrayBuffer())).toEqual(bytes)
  })

  it('bounds a hung delivery and error-report binding so settle and cleanup still complete', async () => {
    vi.useFakeTimers()
    const original = response()
    const reader = { read: vi.fn().mockResolvedValueOnce({ done: false, value: bytes }).mockResolvedValueOnce({ done: true }),
      cancel: vi.fn(async () => {}), releaseLock: vi.fn() }
    vi.spyOn(original, 'clone').mockReturnValue({ body: { getReader: () => reader } } as unknown as Response)
    const { target, native, binding, controller } = setup(original, { deadlineMs: 10, hungBinding: true })
    expect(await target.fetch(url, { headers })).toBe(original)
    await vi.advanceTimersByTimeAsync(10)
    expect(await controller.settle()).toEqual(['pdf_capture_deadline'])
    expect(binding).toHaveBeenCalledTimes(2)
    expect(native).toHaveBeenCalledOnce()
    controller.cleanup()
    expect(target.fetch).toBe(native)
  })

  it('bounds capture count without blocking or replacing any native responses', async () => {
    const { target, native, delivered, controller } = setup(response(), { maxCaptures: 1 })
    await target.fetch(url, { headers })
    await target.fetch(url, { headers })
    await target.fetch(url, { headers })
    expect(await controller.settle()).toEqual(['pdf_capture_count_limit'])
    expect(native).toHaveBeenCalledTimes(3)
    expect(delivered.filter(value => value.bodyBase64 !== undefined)).toHaveLength(1)
    expect(delivered.filter(value => value.error)).toHaveLength(1)
    controller.cleanup()
  })
})
