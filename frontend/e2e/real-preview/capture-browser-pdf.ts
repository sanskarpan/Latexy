export type BrowserPdfCapture = {
  jobId: string; artifactId: string; fingerprint: string; requestId: string
  status: number; deadlineAt: number; bodyBytes?: number; bodyBase64?: string; error?: string
}

export type PdfCaptureOptions = {
  apiOrigin: string; bindingName: string; maxBytes: number; maxCaptures: number; deadlineMs: number
  /** Explicit opt-in for the saved-owner builder's normal /download/{job} fetch. */
  ownedDownloads?: boolean
}

export type PdfCaptureController = {
  settle(): Promise<string[]>
  cleanup(): void
}

/** Test-local observation only. Return the native Response unchanged; never
 * refetch, fulfill, alter headers/body, or wait for observation before returning.
 * A clone tee can affect timing, so this proves bytes/functionality, not latency.
 */
export function installBrowserPdfCapture(options: PdfCaptureOptions) {
  const target = window as typeof window & {
    __latexyRealPreviewCapture?: PdfCaptureController
    [binding: string]: unknown
  }
  const originalFetch = window.fetch
  const nativeFetch = originalFetch.bind(window)
  const active = new Set<Promise<void>>()
  const readers = new Set<ReadableStreamDefaultReader<Uint8Array>>()
  const errors: string[] = []
  let captures = 0
  let disposed = false
  const emit = async (value: BrowserPdfCapture) => {
    if (disposed) return
    const binding = target[options.bindingName] as (value: BrowserPdfCapture) => Promise<void>
    await binding(value)
  }
  const report = (identity: BrowserPdfCapture, error: string) => {
    if (errors.length < options.maxCaptures + 1) errors.push(error)
    // A broken binding must not hold report/settle past the capture deadline.
    void emit({ ...identity, error }).catch(() => {})
  }
  const wrapper: typeof fetch = async (input, init) => {
    const response = await nativeFetch(input, init)
    if (disposed) return response
    let requested: URL
    let returned: URL
    try {
      requested = new URL(input instanceof Request ? input.url : String(input), window.location.href)
      returned = new URL(response.url)
    } catch { return response }
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase()
    const match = /^\/download\/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})\/preview\/([a-f0-9]{64})$/.exec(requested.pathname)
      ?? (options.ownedDownloads ? /^\/download\/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/.exec(requested.pathname) : null)
    if (method !== 'GET' || requested.origin !== options.apiOrigin || requested.search || !match
      || returned.href !== requested.href) return response
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined))
    const identity: BrowserPdfCapture = { jobId: match[1], artifactId: match[2] ?? '', status: response.status,
      fingerprint: headers.get('x-device-fingerprint') ?? '', requestId: headers.get('x-request-id') ?? '',
      deadlineAt: Date.now() + options.deadlineMs }
    captures++
    if (captures > options.maxCaptures) {
      if (captures === options.maxCaptures + 1) void report(identity, 'pdf_capture_count_limit')
      return response
    }
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined
    let timer: ReturnType<typeof setTimeout> | undefined
    let timedOut = false
    const read = async () => {
      if (response.status !== 200) throw new Error('pdf_capture_http_status')
      if (response.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase() !== 'application/pdf') {
        throw new Error('pdf_capture_content_type')
      }
      const clone = response.clone()
      if (!clone.body) return new Uint8Array()
      reader = clone.body.getReader()
      readers.add(reader)
      const chunks: Uint8Array[] = []
      let bytes = 0
      try {
        while (true) {
          const chunk = await reader.read()
          if (chunk.done) break
          bytes += chunk.value.byteLength
          if (bytes > options.maxBytes) throw new Error('pdf_capture_byte_limit')
          chunks.push(chunk.value)
        }
        const body = new Uint8Array(bytes)
        let offset = 0
        for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength }
        return body
      } catch (error) {
        void reader.cancel().catch(() => {})
        throw error
      } finally { readers.delete(reader); reader.releaseLock() }
    }
    const readAndEmit = read().then(async body => {
      if (timedOut || disposed) return
      let binary = ''
      for (let index = 0; index < body.length; index += 16_384) {
        binary += String.fromCharCode(...body.subarray(index, index + 16_384))
      }
      await emit({ ...identity, bodyBytes: body.byteLength, bodyBase64: btoa(binary) })
    })
    const deadline = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        timedOut = true
        if (reader) void reader.cancel().catch(() => {})
        reject(new Error('pdf_capture_deadline'))
      }, options.deadlineMs)
    })
    const operation = Promise.race([readAndEmit, deadline]).catch(error => {
      if (reader) void reader.cancel().catch(() => {})
      const code = error instanceof Error && ['pdf_capture_http_status', 'pdf_capture_content_type',
        'pdf_capture_byte_limit', 'pdf_capture_deadline'].includes(error.message)
        ? error.message : 'pdf_capture_read_failure'
      report(identity, code)
    }).finally(() => { if (timer) clearTimeout(timer); active.delete(operation) })
    active.add(operation)
    return response
  }
  window.fetch = wrapper
  target.__latexyRealPreviewCapture = {
    async settle() { await Promise.all([...active]); return [...errors] },
    cleanup() {
      disposed = true
      if (window.fetch === wrapper) window.fetch = originalFetch
      for (const reader of readers) void reader.cancel().catch(() => {})
      delete target.__latexyRealPreviewCapture
    },
  }
}
