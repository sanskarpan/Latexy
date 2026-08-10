export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

interface RequestOptions {
  retryDelayMs?: number
  timeoutMs?: number
  signal?: AbortSignal
  /**
   * Force retry on or off. Defaults to true only for idempotent methods, so a
   * POST is never silently replayed. Set explicitly where a non-idempotent call
   * is genuinely safe to repeat.
   */
  retry?: boolean
}

/** Methods that are safe to replay. Everything else runs exactly once. */
const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])

export class ApiClient {
  private token: string | null = null
  private baseUrl: string
  private origin: string | null

  constructor(opts: { baseUrl: string; origin?: string }) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '')
    // Better Auth (mounted on the Next.js app) refuses any request it decides
    // came from a browser but carries no Origin, and Node's fetch trips that
    // heuristic while sending no Origin of its own:
    //
    //   403 {"message":"Missing or null Origin","code":"MISSING_OR_NULL_ORIGIN"}
    //
    // So sign-in from the TUI could never succeed. Callers talking to the auth
    // origin declare it here; requests to the FastAPI backend are unaffected.
    this.origin = opts.origin != null ? opts.origin.replace(/\/$/, '') : null
  }

  setToken(token: string | null): void {
    this.token = token
  }

  getWsUrl(): string {
    return this.baseUrl.replace(/^http/, 'ws') + '/ws/jobs'
  }

  private buildHeaders(): Headers {
    const h = new Headers({ 'Content-Type': 'application/json' })
    if (this.token) h.set('Authorization', `Bearer ${this.token}`)
    if (this.origin != null) h.set('Origin', this.origin)
    return h
  }

  async request<T>(
    method: string,
    path: string,
    body?: unknown,
    opts: RequestOptions = {},
  ): Promise<T> {
    const { retryDelayMs = 1000, timeoutMs = 30_000 } = opts
    const url = `${this.baseUrl}${path}`
    // Only replay requests that are safe to replay. A 5xx can be returned after
    // the server already did the work, and a network timeout says nothing about
    // whether it was processed — so retrying POST /jobs/submit could enqueue the
    // same job up to three times, and since #998 each one is a separate charge
    // against the caller's plan allowance. Callers that know a POST is safe to
    // repeat can opt in with `retry: true`.
    const idempotent = IDEMPOTENT_METHODS.has(method.toUpperCase())
    const mayRetry = opts.retry ?? idempotent
    const maxAttempts = mayRetry ? 3 : 1

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), timeoutMs)
      const signal = opts.signal
        ? AbortSignal.any([opts.signal, controller.signal])
        : controller.signal

      try {
        const res = await fetch(url, {
          method,
          headers: this.buildHeaders(),
          body: body !== undefined ? JSON.stringify(body) : undefined,
          signal,
        })
        clearTimeout(timer)

        if (res.status === 401) {
          const data = await res.json().catch(() => ({}))
          // Prefer the server's own wording ("Session expired", "Authentication
          // required") over a hardcoded label that tells the user nothing.
          throw new ApiError(errorMessage(data) ?? 'Unauthorized', 401, data)
        }

        if (res.status >= 500 && attempt < maxAttempts) {
          await sleep(retryDelayMs * attempt)
          continue
        }

        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          throw new ApiError(errorMessage(data) ?? res.statusText, res.status, data)
        }

        const ct = res.headers.get('Content-Type') ?? ''
        if (ct.includes('application/json')) return res.json() as Promise<T>
        return res.text() as unknown as T
      } catch (err) {
        clearTimeout(timer)
        if (err instanceof ApiError) throw err
        // Nothing is listening, or the host does not resolve. That will not
        // change within the backoff, so retrying only made every command sit for
        // ~3 seconds before admitting the backend was down.
        if (isUnreachable(err)) throw err
        if (attempt === maxAttempts) throw err
        await sleep(retryDelayMs * attempt)
      }
    }

    throw new ApiError('Max retries exceeded', 0, null)
  }

  get<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, undefined, opts)
  }

  /**
   * Fetch raw bytes, authenticated.
   *
   * request() decodes anything non-JSON with res.text(), which mangles binary:
   * a .docx round-tripped through a UTF-8 string grew from 36,666 to 65,425
   * bytes and no longer unzipped. Exports and PDF downloads must not go through
   * that path.
   */
  async getBinary(path: string, opts: RequestOptions = {}): Promise<Buffer> {
    const { timeoutMs = 60_000, retryDelayMs = 1000 } = opts
    // Binary GETs are idempotent, so they retry like every other GET. Skipping
    // the loop made a single transient 5xx fail an export outright.
    const maxAttempts = (opts.retry ?? true) ? 3 : 1
    let lastErr: unknown

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), timeoutMs)
      // Honour the caller's signal too — hardcoding our own meant a download
      // could not be cancelled.
      const signal = opts.signal
        ? AbortSignal.any([opts.signal, controller.signal])
        : controller.signal

      try {
        const headers = new Headers()
        if (this.token) headers.set('Authorization', `Bearer ${this.token}`)
        const res = await fetch(`${this.baseUrl}${path}`, { headers, signal })
        clearTimeout(timer)

        if (res.status >= 500 && attempt < maxAttempts) {
          await sleep(retryDelayMs * attempt)
          continue
        }
        if (!res.ok) throw await binaryError(res)

        const buf = Buffer.from(await res.arrayBuffer())
        // A zero-byte 200 is not a successful download. Writing it produced an
        // empty .docx that was reported as a completed export.
        if (buf.length === 0) {
          throw new ApiError('The server returned an empty file.', res.status, null)
        }
        return buf
      } catch (err) {
        clearTimeout(timer)
        if (err instanceof ApiError) throw err
        // A deliberate cancellation is not a transient failure. Retrying it made
        // an aborted export take ~3s to stop while it slept between attempts.
        if (opts.signal?.aborted === true) throw err
        if (isUnreachable(err)) throw err
        if (attempt === maxAttempts) throw err
        lastErr = err
        await sleep(retryDelayMs * attempt)
      }
    }
    throw lastErr instanceof Error ? lastErr : new ApiError('Download failed', 0, null)
  }


  post<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>('POST', path, body, opts)
  }

  put<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
    return this.request<T>('PUT', path, body, opts)
  }

  delete<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>('DELETE', path, undefined, opts)
  }

  async postForm<T>(path: string, form: FormData, opts?: RequestOptions): Promise<T> {
    const { timeoutMs = 30_000 } = opts ?? {}
    const url = `${this.baseUrl}${path}`
    const headers = new Headers()
    if (this.token) headers.set('Authorization', `Bearer ${this.token}`)
    const res = await fetch(url, {
      method: 'POST',
      headers,
      body: form,
      signal: AbortSignal.timeout(timeoutMs),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const msg = (data as Record<string, unknown>)['detail'] as string ?? res.statusText
      throw new ApiError(msg, res.status, data)
    }
    return res.json() as Promise<T>
  }
}

/**
 * Pull a human-readable message out of an error body.
 *
 * `detail` was read as a string and handed straight to ApiError. On a 422 FastAPI
 * makes it an ARRAY of per-field objects, so the `as string` cast was a lie and
 * the `??` never fired — every validation failure reached the user as the literal
 * text `[object Object]`, naming neither the field nor the problem.
 *
 * The backend also sends a second envelope, {error:{code,message}}, which is the
 * better wording when `detail` is absent.
 */
function errorMessage(data: unknown): string | null {
  if (data == null || typeof data !== 'object') return null
  const body = data as Record<string, unknown>

  const detail = body['detail']
  if (typeof detail === 'string' && detail !== '') return detail

  if (Array.isArray(detail)) {
    // [{loc:["body","latex_content"], msg:"Field required"}, …]
    const parts = detail
      .map(d => {
        if (d == null || typeof d !== 'object') return null
        const item = d as Record<string, unknown>
        const msg = typeof item['msg'] === 'string' ? item['msg'] : null
        if (msg == null) return null
        const loc = Array.isArray(item['loc'])
          // Drop the leading "body"/"query" scope — the field name is what helps.
          ? (item['loc'] as unknown[]).slice(1).map(String).join('.')
          : ''
        return loc !== '' ? `${loc}: ${msg}` : msg
      })
      .filter((p): p is string => p !== null)
    if (parts.length > 0) return parts.slice(0, 4).join('; ')
  }

  const nested = body['error']
  if (nested != null && typeof nested === 'object') {
    const msg = (nested as Record<string, unknown>)['message']
    if (typeof msg === 'string' && msg !== '') return msg
  }

  // Better Auth puts its reason at the top level — {"message":"Missing or null
  // Origin","code":"MISSING_OR_NULL_ORIGIN"} — with no `detail` and no `error`
  // wrapper, so every sign-in failure reached the login prompt as bare
  // "Forbidden" instead of saying what was actually wrong.
  const flat = body['message']
  if (typeof flat === 'string' && flat !== '') return flat

  return null
}

/**
 * Turn a failed binary response into a readable ApiError.
 *
 * getBinary used to surface `res.text().slice(0, 200)`, so an export failure
 * printed the whole JSON envelope truncated mid-token — and a proxy's HTML 502
 * became the entire page as the message. request() reads `detail`; this matches.
 */
async function binaryError(res: Response): Promise<ApiError> {
  const raw = await res.text().catch(() => '')
  let message = res.statusText || `HTTP ${res.status}`
  try {
    message = errorMessage(JSON.parse(raw)) ?? message
  } catch {
    // Not JSON (an HTML error page from a proxy) — do not dump the markup.
    if (res.status === 401 || res.status === 403) message = 'Unauthorized'
  }
  return new ApiError(message, res.status, raw.slice(0, 500))
}

/**
 * A connection that cannot succeed on retry — no host, or nothing listening.
 *
 * Node tries IPv4 and IPv6 in parallel, so `cause` is often an AggregateError
 * carrying one failure per address family and no `code` of its own. Reading only
 * `cause.code` missed those entirely and the request still burned its retries.
 */
const UNREACHABLE_CODES = new Set(['ECONNREFUSED', 'ENOTFOUND', 'EHOSTUNREACH', 'ENETUNREACH'])

function isUnreachable(err: unknown): boolean {
  const cause = (err as { cause?: unknown } | null)?.cause
  if (cause == null || typeof cause !== 'object') return false

  const code = (cause as { code?: string }).code
  if (code != null) return UNREACHABLE_CODES.has(code)

  const nested = (cause as { errors?: unknown }).errors
  if (Array.isArray(nested) && nested.length > 0) {
    return nested.every(e => UNREACHABLE_CODES.has((e as { code?: string })?.code ?? ''))
  }
  return false
}

function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}

let _client: ApiClient | null = null

export function getApiClient(): ApiClient {
  if (!_client) _client = new ApiClient({ baseUrl: 'http://localhost:8030' })
  return _client
}

export function initApiClient(baseUrl: string, token: string | null): ApiClient {
  _client = new ApiClient({ baseUrl })
  _client.setToken(token)
  return _client
}
