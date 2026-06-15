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
}

export class ApiClient {
  private token: string | null = null
  private baseUrl: string

  constructor(opts: { baseUrl: string }) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, '')
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
    const maxAttempts = 3

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
          throw new ApiError('Unauthorized', 401, data)
        }

        if (res.status >= 500 && attempt < maxAttempts) {
          await sleep(retryDelayMs * attempt)
          continue
        }

        if (!res.ok) {
          const data = await res.json().catch(() => ({}))
          const msg = (data as Record<string, unknown>)['detail'] as string ?? res.statusText
          throw new ApiError(msg, res.status, data)
        }

        const ct = res.headers.get('Content-Type') ?? ''
        if (ct.includes('application/json')) return res.json() as Promise<T>
        return res.text() as unknown as T
      } catch (err) {
        clearTimeout(timer)
        if (err instanceof ApiError) throw err
        if (attempt === maxAttempts) throw err
        await sleep(retryDelayMs * attempt)
      }
    }

    throw new ApiError('Max retries exceeded', 0, null)
  }

  get<T>(path: string, opts?: RequestOptions): Promise<T> {
    return this.request<T>('GET', path, undefined, opts)
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
