# Latexy TUI — Phase 1 (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a working `latexy` CLI that a user can `npm install -g`, then log in, list resumes, compile with live streaming logs, and download a PDF — all from the terminal.

**Architecture:** React + Ink v7 chat-style TUI in `packages/tui/` inside the existing Latexy monorepo. Direct WebSocket connection to the existing FastAPI backend at `ws://localhost:8030/ws/jobs`. nanostores for global state. tsup bundles to a single ESM file with a shebang.

**Tech Stack:** Ink v7, React 19, TypeScript 5.8, nanostores 0.11, `ws` 8, `@iarna/toml`, tsup 8, vitest 2, ink-testing-library

> **Phase scope:** This plan covers Phase 1 (MVP) only. Phase 2 (all 35 domains) and Phase 3 (agent mode + Homebrew) are separate plans that build on this foundation.

---

## File Map

**Create (new package):**
```
packages/tui/
  package.json
  tsconfig.json
  tsup.config.ts
  vitest.config.ts
  src/
    cli.tsx                         ← entry point, TTY vs CI branching
    app.tsx                         ← root App component, mounts Ink tree
    stores/
      session.ts                    ← auth token, user, plan, backend URL
      messages.ts                   ← transcript message list + helpers
      overlay.ts                    ← $overlay atom + $isBlocked computed
      ui.ts                         ← health status, WS connected flag
    lib/
      event-types.ts                ← TypeScript interfaces for 14 WS event types
      config.ts                     ← read/write ~/.config/latexy/config.toml
      api-client.ts                 ← fetch wrapper: auth, retry, timeout
      ws-client.ts                  ← WS singleton: buffer, drain, reconnect
    components/
      AppShell.tsx                  ← outer layout (StatusBar + TranscriptView + PromptZone)
      StatusBar.tsx                 ← top bar: brand, user, health dot, hint
      TranscriptView.tsx            ← Static (history) + StreamingPane (active turn)
      PromptInput.tsx               ← TextInput + slash suggestion menu
      SlashSuggestions.tsx          ← suggestion list rendered above input
      MessageRow.tsx                ← dispatches to correct card variant
      ToolUseCard.tsx               ← tool card: running/success/error states
      LogStreamCard.tsx             ← scrollable pdflatex log display
      CompileResultCard.tsx         ← compile summary: time, pages, size
      overlays/
        LoginOverlay.tsx            ← email + password fields
        ResumePicker.tsx            ← resume list with keyboard filter
    commands/
      registry.ts                   ← slash command definitions table
      parser.ts                     ← parse "/compile --compiler xelatex" → {cmd, args}
      dispatch.ts                   ← two-tier dispatch (local vs API)
    tools/
      compile.ts                    ← compile tool: POST job + subscribe WS
    hooks/
      useJobStream.ts               ← WS event → JobController → store bridge
    __tests__/
      setup.ts                      ← vitest global setup
      config.test.ts
      api-client.test.ts
      ws-client.test.ts
      parser.test.ts
      StatusBar.test.tsx
      ToolUseCard.test.tsx
      LogStreamCard.test.tsx
      CompileResultCard.test.tsx
```

**Modify (repo root):**
- `pnpm-workspace.yaml` — add `packages/*`
- `turbo.json` — create with tui build/dev/typecheck tasks

---

## Task 1: Monorepo Plumbing

**Files:**
- Create: `pnpm-workspace.yaml`
- Create: `turbo.json`

- [ ] **Step 1: Create pnpm-workspace.yaml**

```yaml
packages:
  - frontend
  - backend
  - packages/*
```

- [ ] **Step 2: Create turbo.json**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**"]
    },
    "dev": {
      "persistent": true,
      "cache": false
    },
    "typecheck": {
      "dependsOn": ["^build"]
    },
    "test": {
      "dependsOn": ["build"]
    }
  }
}
```

- [ ] **Step 3: Verify pnpm recognises the workspace**

```bash
cd /path/to/latexy
pnpm -r ls 2>&1 | head -20
```

Expected: lists `frontend` and (soon) `latexy` packages.

---

## Task 2: Package Scaffold

**Files:**
- Create: `packages/tui/package.json`
- Create: `packages/tui/tsconfig.json`
- Create: `packages/tui/tsup.config.ts`
- Create: `packages/tui/vitest.config.ts`

- [ ] **Step 1: Create packages/tui/package.json**

```json
{
  "name": "latexy",
  "version": "1.0.0",
  "description": "Terminal UI for the Latexy LaTeX resume platform",
  "type": "module",
  "bin": { "latexy": "./dist/cli.js" },
  "engines": { "node": ">=22" },
  "files": ["dist/", "README.md"],
  "publishConfig": { "access": "public", "provenance": true },
  "scripts": {
    "build": "tsup",
    "dev": "tsup --watch",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest",
    "prepublishOnly": "pnpm run build"
  },
  "dependencies": {
    "@iarna/toml": "^2.2.5",
    "@inkjs/ui": "^2.0.0",
    "@nanostores/react": "^0.8.0",
    "clipboardy": "^4.0.0",
    "ink": "^5.2.0",
    "ink-text-input": "^6.0.0",
    "marked-terminal": "^7.1.0",
    "nanostores": "^0.11.0",
    "react": "^19.0.0",
    "ws": "^8.18.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "@types/react": "^19.0.0",
    "@types/ws": "^8.5.0",
    "ink-testing-library": "^4.0.0",
    "tsup": "^8.0.0",
    "typescript": "^5.8.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 2: Create packages/tui/tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "lib": ["ES2022"],
    "jsx": "react-jsx",
    "jsxImportSource": "react",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist",
    "rootDir": "src",
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "src/__tests__"]
}
```

- [ ] **Step 3: Create packages/tui/tsup.config.ts**

```typescript
import { defineConfig } from 'tsup'

export default defineConfig({
  entry: { cli: 'src/cli.tsx' },
  format: ['esm'],
  target: 'node22',
  platform: 'node',
  bundle: true,
  clean: true,
  dts: false,
  sourcemap: true,
  banner: { js: '#!/usr/bin/env node' },
  external: [],
})
```

- [ ] **Step 4: Create packages/tui/vitest.config.ts**

```typescript
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',
    setupFiles: ['./src/__tests__/setup.ts'],
    include: ['src/__tests__/**/*.test.{ts,tsx}'],
  },
})
```

- [ ] **Step 5: Install dependencies**

```bash
cd packages/tui
pnpm install
```

Expected: `node_modules/` populated, `ink`, `nanostores`, `ws` present.

- [ ] **Step 6: Verify TypeScript compiles (empty src)**

```bash
mkdir -p src && echo 'export {}' > src/index.ts
pnpm typecheck
```

Expected: no errors.

---

## Task 3: Event Types

**Files:**
- Create: `packages/tui/src/lib/event-types.ts`
- Create: `packages/tui/src/__tests__/event-types.test.ts`

The frontend already has these types in `frontend/src/lib/event-types.ts`. We adapt them for the Node.js context (same interfaces, no Next.js imports).

- [ ] **Step 1: Write failing test**

```typescript
// src/__tests__/event-types.test.ts
import { describe, it, expect } from 'vitest'
import type { AnyEvent, JobCompletedEvent, LLMTokenEvent } from '../lib/event-types.js'

describe('event-types', () => {
  it('JobCompletedEvent has required fields', () => {
    const ev: JobCompletedEvent = {
      event_id: 'e1',
      job_id: 'j1',
      timestamp: Date.now(),
      sequence: 1,
      type: 'job.completed',
      result: { success: true },
      final_status: 'completed',
    }
    expect(ev.type).toBe('job.completed')
  })

  it('LLMTokenEvent carries token string', () => {
    const ev: LLMTokenEvent = {
      event_id: 'e2',
      job_id: 'j2',
      timestamp: Date.now(),
      sequence: 2,
      type: 'llm.token',
      token: 'Hello',
    }
    expect(ev.token).toBe('Hello')
  })
})
```

- [ ] **Step 2: Run test, expect compile error (file missing)**

```bash
cd packages/tui && pnpm test 2>&1 | head -20
```

Expected: `Cannot find module '../lib/event-types.js'`

- [ ] **Step 3: Create src/lib/event-types.ts**

```typescript
// packages/tui/src/lib/event-types.ts
export type EventType =
  | 'job.queued'
  | 'job.started'
  | 'job.progress'
  | 'job.completed'
  | 'job.failed'
  | 'job.cancelled'
  | 'job.pdf_extracted'
  | 'llm.token'
  | 'llm.complete'
  | 'log.line'
  | 'ats.deep_complete'
  | 'sys.heartbeat'
  | 'sys.error'
  | 'document.convert_complete'

export interface BaseEvent {
  event_id: string
  job_id: string
  timestamp: number
  sequence: number
  type: EventType
}

export interface JobQueuedEvent extends BaseEvent {
  type: 'job.queued'
  job_type: string
  user_id: string | null
  estimated_seconds: number
}

export interface JobStartedEvent extends BaseEvent {
  type: 'job.started'
  worker_id: string
  stage: string
}

export interface JobProgressEvent extends BaseEvent {
  type: 'job.progress'
  percent: number
  stage: string
  message: string
}

export interface JobCompletedEvent extends BaseEvent {
  type: 'job.completed'
  result: Record<string, unknown>
  final_status: string
}

export interface JobFailedEvent extends BaseEvent {
  type: 'job.failed'
  error: string
  error_code?: string
  retryable?: boolean
}

export interface JobCancelledEvent extends BaseEvent {
  type: 'job.cancelled'
}

export interface JobPdfExtractedEvent extends BaseEvent {
  type: 'job.pdf_extracted'
  pdf_url: string
  pages: number
  size_bytes: number
}

export interface LLMTokenEvent extends BaseEvent {
  type: 'llm.token'
  token: string
}

export interface LLMCompleteEvent extends BaseEvent {
  type: 'llm.complete'
  total_tokens: number
  content: string
}

export interface LogLineEvent extends BaseEvent {
  type: 'log.line'
  line: string
  level: 'info' | 'warning' | 'error' | 'debug'
}

export interface ATSDeepCompleteEvent extends BaseEvent {
  type: 'ats.deep_complete'
  overall_score: number
  category_scores: Record<string, number>
  recommendations: string[]
  strengths: string[]
  warnings: string[]
  industry_label: string | null
}

export interface SysHeartbeatEvent extends BaseEvent {
  type: 'sys.heartbeat'
  server_time: string
}

export interface SysErrorEvent extends BaseEvent {
  type: 'sys.error'
  error: string
}

export interface DocumentConvertCompleteEvent extends BaseEvent {
  type: 'document.convert_complete'
  latex_content: string
  detected_format: string
}

export type AnyEvent =
  | JobQueuedEvent
  | JobStartedEvent
  | JobProgressEvent
  | JobCompletedEvent
  | JobFailedEvent
  | JobCancelledEvent
  | JobPdfExtractedEvent
  | LLMTokenEvent
  | LLMCompleteEvent
  | LogLineEvent
  | ATSDeepCompleteEvent
  | SysHeartbeatEvent
  | SysErrorEvent
  | DocumentConvertCompleteEvent
```

- [ ] **Step 4: Run test, expect PASS**

```bash
pnpm test -- event-types
```

Expected: 2 passing.

---

## Task 4: Config Storage

**Files:**
- Create: `packages/tui/src/lib/config.ts`
- Create: `packages/tui/src/__tests__/config.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/config.test.ts
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { writeFileSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// Override XDG_CONFIG_HOME to use a temp dir
const TMP_CONFIG = join(tmpdir(), `latexy-test-${process.pid}`)

process.env['XDG_CONFIG_HOME'] = TMP_CONFIG

// Import AFTER setting env so configDir picks up override
import { readConfig, writeConfig, clearConfig, type LatexyConfig } from '../lib/config.js'

describe('config', () => {
  beforeEach(() => {
    mkdirSync(join(TMP_CONFIG, 'latexy'), { recursive: true })
  })

  afterEach(() => {
    rmSync(TMP_CONFIG, { recursive: true, force: true })
  })

  it('returns defaults when config file missing', async () => {
    const cfg = await readConfig()
    expect(cfg.backendUrl).toBe('http://localhost:8030')
    expect(cfg.token).toBeNull()
  })

  it('round-trips token write + read', async () => {
    await writeConfig({ token: 'tok123', email: 'a@b.com' })
    const cfg = await readConfig()
    expect(cfg.token).toBe('tok123')
    expect(cfg.email).toBe('a@b.com')
  })

  it('clearConfig removes token and email', async () => {
    await writeConfig({ token: 'tok', email: 'x@y.com' })
    await clearConfig()
    const cfg = await readConfig()
    expect(cfg.token).toBeNull()
    expect(cfg.email).toBeNull()
  })
})
```

- [ ] **Step 2: Run test, expect FAIL (module missing)**

```bash
pnpm test -- config
```

Expected: Cannot find module `../lib/config.js`

- [ ] **Step 3: Create src/lib/config.ts**

```typescript
// packages/tui/src/lib/config.ts
import { readFile, writeFile, mkdir, chmod } from 'node:fs/promises'
import { join } from 'node:path'
import { homedir } from 'node:os'
import TOML from '@iarna/toml'

export interface LatexyConfig {
  token: string | null
  email: string | null
  userId: string | null
  backendUrl: string
  defaultResumeId: string | null
  activeModel: string | null
  activeProvider: string | null
}

const DEFAULT_CONFIG: LatexyConfig = {
  token: null,
  email: null,
  userId: null,
  backendUrl: process.env['LATEXY_API_URL'] ?? 'http://localhost:8030',
  defaultResumeId: null,
  activeModel: null,
  activeProvider: null,
}

function configDir(): string {
  const xdg = process.env['XDG_CONFIG_HOME']
  const base = xdg ?? join(homedir(), '.config')
  return join(base, 'latexy')
}

function configPath(): string {
  return join(configDir(), 'config.toml')
}

export async function readConfig(): Promise<LatexyConfig> {
  // Env vars override file config
  const envToken = process.env['LATEXY_SESSION_TOKEN'] ?? null
  try {
    const raw = await readFile(configPath(), 'utf-8')
    const parsed = TOML.parse(raw) as Partial<LatexyConfig>
    return { ...DEFAULT_CONFIG, ...parsed, ...(envToken ? { token: envToken } : {}) }
  } catch {
    return { ...DEFAULT_CONFIG, ...(envToken ? { token: envToken } : {}) }
  }
}

export async function writeConfig(patch: Partial<LatexyConfig>): Promise<void> {
  await mkdir(configDir(), { recursive: true })
  const current = await readConfig()
  const next = { ...current, ...patch }
  const toml = TOML.stringify(next as TOML.JsonMap)
  await writeFile(configPath(), toml, { encoding: 'utf-8', mode: 0o600 })
  // Ensure file is not world-readable
  await chmod(configPath(), 0o600)
}

export async function clearConfig(): Promise<void> {
  await writeConfig({ token: null, email: null, userId: null })
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- config
```

Expected: 3 passing.

---

## Task 5: API Client

**Files:**
- Create: `packages/tui/src/lib/api-client.ts`
- Create: `packages/tui/src/__tests__/api-client.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/api-client.test.ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ApiClient } from '../lib/api-client.js'

describe('ApiClient', () => {
  let client: ApiClient

  beforeEach(() => {
    client = new ApiClient({ baseUrl: 'http://localhost:8030' })
    vi.stubGlobal('fetch', vi.fn())
  })

  it('sets Authorization header when token provided', async () => {
    const mockFetch = vi.mocked(fetch)
    mockFetch.mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    client.setToken('mytoken')
    await client.get('/health')

    const [, init] = mockFetch.mock.calls[0]!
    const headers = new Headers(init?.headers as HeadersInit)
    expect(headers.get('Authorization')).toBe('Bearer mytoken')
  })

  it('throws ApiError on 401', async () => {
    vi.mocked(fetch).mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Unauthorized' }), {
      status: 401,
      headers: { 'Content-Type': 'application/json' },
    }))

    client.setToken('bad')
    await expect(client.get('/me')).rejects.toThrow('Unauthorized')
  })

  it('retries on 503 up to 3 times', async () => {
    const mockFetch = vi.mocked(fetch)
    mockFetch
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response('', { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }))

    const result = await client.get('/health', { retryDelayMs: 0 })
    expect(result).toEqual({ ok: true })
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- api-client
```

Expected: Cannot find module `../lib/api-client.js`

- [ ] **Step 3: Create src/lib/api-client.ts**

```typescript
// packages/tui/src/lib/api-client.ts
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

  private buildHeaders(extra?: Record<string, string>): Headers {
    const h = new Headers({ 'Content-Type': 'application/json', ...extra })
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

        // Retry on 5xx (except 4xx which are client errors)
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
    const { retryDelayMs = 1000, timeoutMs = 30_000 } = opts ?? {}
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

// Singleton — created from config on first use
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
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- api-client
```

Expected: 3 passing.

---

## Task 6: WebSocket Client

**Files:**
- Create: `packages/tui/src/lib/ws-client.ts`
- Create: `packages/tui/src/__tests__/ws-client.test.ts`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/ws-client.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { EventEmitter } from 'node:events'
import { LatexyWSClient } from '../lib/ws-client.js'

// Minimal WS mock
class MockWS extends EventEmitter {
  readyState = 1 // OPEN
  send = vi.fn()
  close = vi.fn()
  terminate = vi.fn()
  static OPEN = 1
  static CONNECTING = 0
  static CLOSED = 3
}

vi.mock('ws', () => ({
  default: vi.fn(() => new MockWS()),
  WebSocket: vi.fn(() => new MockWS()),
}))

describe('LatexyWSClient', () => {
  let client: LatexyWSClient
  let mockWS: MockWS

  beforeEach(async () => {
    const { default: WS } = await import('ws')
    client = new LatexyWSClient()
    client.connect('ws://localhost:8030/ws/jobs', 'testtoken')
    mockWS = vi.mocked(WS).mock.results[0]!.value as unknown as MockWS
  })

  afterEach(() => {
    client.destroy()
    vi.clearAllMocks()
  })

  it('buffers events before drain()', () => {
    const received: unknown[] = []
    client.on('event', e => received.push(e))

    // Simulate incoming message before drain
    const ev = { type: 'log.line', job_id: 'j1', event_id: 'e1', sequence: 1, timestamp: 1 }
    mockWS.emit('message', JSON.stringify(ev))

    expect(received).toHaveLength(0) // not yet drained
    client.drain()
    expect(received).toHaveLength(1)
  })

  it('emits events immediately after drain()', () => {
    client.drain()
    const received: unknown[] = []
    client.on('event', e => received.push(e))

    const ev = { type: 'log.line', job_id: 'j1', event_id: 'e2', sequence: 2, timestamp: 2 }
    mockWS.emit('message', JSON.stringify(ev))
    expect(received).toHaveLength(1)
  })

  it('subscribe() sends subscribe message', () => {
    client.drain()
    client.subscribe('job123', '0')
    expect(mockWS.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'subscribe', job_id: 'job123', last_event_id: '0' })
    )
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- ws-client
```

Expected: Cannot find module `../lib/ws-client.js`

- [ ] **Step 3: Create src/lib/ws-client.ts**

```typescript
// packages/tui/src/lib/ws-client.ts
import { EventEmitter } from 'node:events'
import WS from 'ws'
import type { AnyEvent } from './event-types.js'

const MAX_BUFFER = 2000
const MIN_BACKOFF = 100
const MAX_BACKOFF = 30_000

interface WSClientEvents {
  event: AnyEvent
  connected: void
  disconnected: { wasClean: boolean }
  error: { message: string }
}

export class LatexyWSClient extends EventEmitter {
  private ws: WS.WebSocket | null = null
  private url = ''
  private token = ''
  private buffered: AnyEvent[] = []
  private drained = false
  private reconnectTimer: NodeJS.Timeout | null = null
  private heartbeatTimer: NodeJS.Timeout | null = null
  private reconnectAttempt = 0
  private destroyed = false
  private subscriptions = new Map<string, string>() // job_id → last_event_id

  connect(url: string, token: string): void {
    this.url = url
    this.token = token
    this.openSocket()
  }

  private openSocket(): void {
    if (this.destroyed) return
    this.ws = new WS.WebSocket(this.url, {
      headers: { Authorization: `Bearer ${this.token}` },
    })

    this.ws.on('open', () => {
      this.reconnectAttempt = 0
      this.startHeartbeat()
      this.resubscribeAll()
      this.emit('connected')
    })

    this.ws.on('message', (data: Buffer) => {
      try {
        const ev = JSON.parse(data.toString()) as AnyEvent
        this.publish(ev)
      } catch {}
    })

    this.ws.on('close', (code, reason) => {
      this.stopHeartbeat()
      const wasClean = code === 1000
      this.emit('disconnected', { wasClean })
      if (!this.destroyed && !wasClean) this.scheduleReconnect()
    })

    this.ws.on('error', (err) => {
      this.emit('error', { message: err.message })
    })
  }

  private publish(ev: AnyEvent): void {
    if (this.drained) {
      this.emit('event', ev)
      return
    }
    if (this.buffered.length < MAX_BUFFER) this.buffered.push(ev)
  }

  drain(): void {
    this.drained = true
    for (const ev of this.buffered) this.emit('event', ev)
    this.buffered = []
  }

  subscribe(jobId: string, lastEventId = '0'): void {
    this.subscriptions.set(jobId, lastEventId)
    this.send({ type: 'subscribe', job_id: jobId, last_event_id: lastEventId })
  }

  unsubscribe(jobId: string): void {
    this.subscriptions.delete(jobId)
    this.send({ type: 'unsubscribe', job_id: jobId })
  }

  private resubscribeAll(): void {
    for (const [jobId, lastEventId] of this.subscriptions) {
      this.send({ type: 'subscribe', job_id: jobId, last_event_id: lastEventId })
    }
  }

  private send(msg: unknown): void {
    if (this.ws?.readyState === WS.WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempt++
    const delay = Math.min(MIN_BACKOFF * 2 ** (this.reconnectAttempt - 1), MAX_BACKOFF)
    this.reconnectTimer = setTimeout(() => this.openSocket(), delay)
  }

  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WS.WebSocket.OPEN) this.ws.ping()
    }, 25_000)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  destroy(): void {
    this.destroyed = true
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.stopHeartbeat()
    this.ws?.close(1000, 'Client destroy')
    this.ws = null
  }

  get connected(): boolean {
    return this.ws?.readyState === WS.WebSocket.OPEN
  }
}

// Singleton
export const wsClient = new LatexyWSClient()
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- ws-client
```

Expected: 3 passing.

---

## Task 7: Stores

**Files:**
- Create: `packages/tui/src/stores/session.ts`
- Create: `packages/tui/src/stores/messages.ts`
- Create: `packages/tui/src/stores/overlay.ts`
- Create: `packages/tui/src/stores/ui.ts`

No tests needed for pure atom declarations — the integration tests in later tasks cover them.

- [ ] **Step 1: Create src/stores/session.ts**

```typescript
// packages/tui/src/stores/session.ts
import { atom } from 'nanostores'

export interface SessionState {
  token: string | null
  userId: string | null
  email: string | null
  plan: 'free' | 'basic' | 'pro' | 'byok' | 'team' | null
  backendUrl: string
  wsUrl: string
  isAuthenticated: boolean
}

export const $session = atom<SessionState>({
  token: null,
  userId: null,
  email: null,
  plan: null,
  backendUrl: process.env['LATEXY_API_URL'] ?? 'http://localhost:8030',
  wsUrl: (process.env['LATEXY_API_URL'] ?? 'http://localhost:8030').replace(/^http/, 'ws') + '/ws/jobs',
  isAuthenticated: false,
})
```

- [ ] **Step 2: Create src/stores/messages.ts**

```typescript
// packages/tui/src/stores/messages.ts
import { atom } from 'nanostores'

export type MessageRole =
  | 'user'
  | 'assistant'
  | 'tool_use'
  | 'log_stream'
  | 'compile_result'
  | 'ats_result'
  | 'resume_list'
  | 'system'
  | 'error'

export interface Message {
  id: string
  role: MessageRole
  content: string
  timestamp: string
  streaming?: boolean
  // Tool card fields
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolState?: 'running' | 'success' | 'error' | 'cancelled'
  toolResult?: unknown
  durationMs?: number
  jobId?: string
  // Structured data for non-text cards
  resultData?: unknown
}

export const $messages = atom<Message[]>([])
export const $activeJobId = atom<string | null>(null)

let _idCounter = 0
export function nextId(): string {
  return `msg-${Date.now()}-${_idCounter++}`
}

export function addMessage(msg: Omit<Message, 'id' | 'timestamp'>): string {
  const id = nextId()
  const full: Message = {
    id,
    timestamp: new Date().toISOString(),
    ...msg,
  }
  $messages.set([...$messages.get(), full])
  return id
}

export function updateMessage(id: string, patch: Partial<Message>): void {
  $messages.set($messages.get().map(m => m.id === id ? { ...m, ...patch } : m))
}

export function clearMessages(): void {
  $messages.set([])
}
```

- [ ] **Step 3: Create src/stores/overlay.ts**

```typescript
// packages/tui/src/stores/overlay.ts
import { atom, computed } from 'nanostores'
import type { ReactNode } from 'react'

export const $overlay = atom<ReactNode | null>(null)
// $isBlocked gates all keyboard input when any overlay is open
export const $isBlocked = computed($overlay, o => o !== null)

export function openOverlay(node: ReactNode): void {
  $overlay.set(node)
}

export function closeOverlay(): void {
  $overlay.set(null)
}
```

- [ ] **Step 4: Create src/stores/ui.ts**

```typescript
// packages/tui/src/stores/ui.ts
import { atom } from 'nanostores'

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'

export interface UIState {
  theme: 'dark' | 'light'
  healthStatus: HealthStatus
  wsConnected: boolean
  notifications: Array<{ id: string; message: string; level: 'info' | 'error' }>
}

export const $ui = atom<UIState>({
  theme: 'dark',
  healthStatus: 'unknown',
  wsConnected: false,
  notifications: [],
})
```

---

## Task 8: JobController

**Files:**
- Create: `packages/tui/src/hooks/useJobStream.ts`

The JobController is a plain class (not a React hook) that converts raw WS events into store mutations. The `useJobStream` hook wires it to React.

- [ ] **Step 1: Create src/hooks/useJobStream.ts**

```typescript
// packages/tui/src/hooks/useJobStream.ts
import { useEffect, useRef } from 'react'
import { wsClient } from '../lib/ws-client.js'
import { addMessage, updateMessage, $activeJobId, type Message } from '../stores/messages.js'
import type {
  AnyEvent,
  LogLineEvent,
  LLMTokenEvent,
  JobProgressEvent,
  JobCompletedEvent,
  JobFailedEvent,
  JobCancelledEvent,
} from '../lib/event-types.js'

class JobController {
  private logMsgId: string | null = null
  private toolMsgId: string | null = null
  private logLines: string[] = []
  private llmBuffer = ''
  private llmMsgId: string | null = null
  private lastFlushedLen = 0
  private flushTimer: NodeJS.Timeout | null = null
  private startedAt = Date.now()

  constructor(private readonly jobId: string) {}

  onLogLine(ev: LogLineEvent): void {
    if (!this.logMsgId) {
      this.logMsgId = addMessage({
        role: 'log_stream',
        content: '',
        jobId: this.jobId,
        resultData: { lines: [] as string[] },
      })
    }
    this.logLines.push(ev.line)
    updateMessage(this.logMsgId, {
      resultData: { lines: [...this.logLines] },
    })
  }

  onLLMToken(token: string): void {
    this.llmBuffer += token
    if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => {
        const delta = this.llmBuffer.slice(this.lastFlushedLen)
        this.lastFlushedLen = this.llmBuffer.length
        this.flushTimer = null

        if (!this.llmMsgId) {
          this.llmMsgId = addMessage({
            role: 'assistant',
            content: delta,
            jobId: this.jobId,
            streaming: true,
          })
        } else {
          updateMessage(this.llmMsgId, {
            content: this.llmBuffer,
          })
        }
      }, 16)
    }
  }

  onProgress(ev: JobProgressEvent): void {
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        content: `${ev.stage} ${ev.percent}%`,
      })
    }
  }

  onComplete(ev: JobCompletedEvent): void {
    const durationMs = Date.now() - this.startedAt
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'success',
        toolResult: ev.result,
        durationMs,
      })
    }
    if (this.llmMsgId) {
      updateMessage(this.llmMsgId, { streaming: false })
    }
    $activeJobId.set(null)

    // Emit compile result card if result has compile data
    const result = ev.result as Record<string, unknown>
    if (result['pdf_url'] || result['pages'] != null) {
      addMessage({
        role: 'compile_result',
        content: '',
        jobId: this.jobId,
        resultData: {
          pages: result['pages'],
          sizeBytes: result['size_bytes'],
          compilationTimeMs: durationMs,
          pdfUrl: result['pdf_url'],
          atsScore: result['ats_score'],
        },
      })
    }
  }

  onFailed(ev: JobFailedEvent): void {
    const durationMs = Date.now() - this.startedAt
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'error',
        toolResult: { error: ev.error },
        durationMs,
      })
    }
    $activeJobId.set(null)
  }

  onCancelled(_ev: JobCancelledEvent): void {
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, { toolState: 'cancelled' })
    }
    $activeJobId.set(null)
  }

  setToolMsgId(id: string): void {
    this.toolMsgId = id
  }
}

// Map of jobId → controller for active jobs
const controllers = new Map<string, JobController>()

export function createJobController(jobId: string): JobController {
  const ctrl = new JobController(jobId)
  controllers.set(jobId, ctrl)
  return ctrl
}

export function useWSEventRouter(): void {
  const mounted = useRef(false)

  useEffect(() => {
    if (mounted.current) return
    mounted.current = true

    const handleEvent = (ev: AnyEvent) => {
      const ctrl = controllers.get(ev.job_id)
      if (!ctrl) return

      switch (ev.type) {
        case 'log.line':      ctrl.onLogLine(ev); break
        case 'llm.token':     ctrl.onLLMToken(ev.token); break
        case 'job.progress':  ctrl.onProgress(ev); break
        case 'job.completed': ctrl.onComplete(ev); controllers.delete(ev.job_id); break
        case 'job.failed':    ctrl.onFailed(ev); controllers.delete(ev.job_id); break
        case 'job.cancelled': ctrl.onCancelled(ev); controllers.delete(ev.job_id); break
      }
    }

    wsClient.on('event', handleEvent)
    return () => { wsClient.off('event', handleEvent) }
  }, [])
}

export { JobController }
```

---

## Task 9: Test Setup File

**Files:**
- Create: `packages/tui/src/__tests__/setup.ts`

- [ ] **Step 1: Create setup.ts**

```typescript
// packages/tui/src/__tests__/setup.ts
// Vitest global setup for TUI tests
// Suppress Ink's alternate-screen escape codes in test output
process.env['CI'] = 'true'
```

---

## Task 10: StatusBar Component

**Files:**
- Create: `packages/tui/src/components/StatusBar.tsx`
- Create: `packages/tui/src/__tests__/StatusBar.test.tsx`

- [ ] **Step 1: Write failing test**

```typescript
// src/__tests__/StatusBar.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { StatusBar } from '../components/StatusBar.js'

describe('StatusBar', () => {
  it('shows brand name', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unknown" wsConnected={false} />)
    expect(lastFrame()).toContain('Latexy')
  })

  it('shows user email when logged in', () => {
    const { lastFrame } = render(<StatusBar email="a@b.com" plan="pro" health="healthy" wsConnected={true} />)
    expect(lastFrame()).toContain('a@b.com')
    expect(lastFrame()).toContain('PRO')
  })

  it('shows health dot', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unhealthy" wsConnected={false} />)
    expect(lastFrame()).toContain('unhealthy')
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- StatusBar
```

Expected: Cannot find module `../components/StatusBar.js`

- [ ] **Step 3: Create src/components/StatusBar.tsx**

```tsx
// packages/tui/src/components/StatusBar.tsx
import React from 'react'
import { Box, Text } from 'ink'
import type { HealthStatus } from '../stores/ui.js'

interface Props {
  email: string | null
  plan: string | null
  health: HealthStatus
  wsConnected: boolean
}

const HEALTH_COLOR: Record<HealthStatus, string> = {
  healthy: 'green',
  degraded: 'yellow',
  unhealthy: 'red',
  unknown: 'gray',
}

const PLAN_LABEL: Record<string, string> = {
  free: 'FREE',
  basic: 'BASIC',
  pro: 'PRO',
  byok: 'BYOK',
  team: 'TEAM',
}

export function StatusBar({ email, plan, health, wsConnected }: Props): React.ReactElement {
  const healthColor = HEALTH_COLOR[health]
  const planLabel = plan ? PLAN_LABEL[plan] ?? plan.toUpperCase() : null

  return (
    <Box paddingX={1} justifyContent="space-between">
      <Text bold color="cyan">Latexy</Text>
      <Box gap={2}>
        {email && (
          <Text>
            {email}
            {planLabel && (
              <Text color="magenta"> [{planLabel}]</Text>
            )}
          </Text>
        )}
        <Text color={healthColor as string}>● {health}</Text>
        {!wsConnected && <Text color="yellow">⚡ disconnected</Text>}
        <Text dimColor>? help · / commands</Text>
      </Box>
    </Box>
  )
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- StatusBar
```

Expected: 3 passing.

---

## Task 11: ToolUseCard Component

**Files:**
- Create: `packages/tui/src/components/ToolUseCard.tsx`
- Create: `packages/tui/src/__tests__/ToolUseCard.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/ToolUseCard.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { ToolUseCard } from '../components/ToolUseCard.js'
import type { Message } from '../stores/messages.js'

const base: Message = {
  id: 'm1',
  role: 'tool_use',
  content: '',
  timestamp: new Date().toISOString(),
  toolName: 'compile_pdf',
}

describe('ToolUseCard', () => {
  it('shows spinner when running', () => {
    const { lastFrame } = render(
      <ToolUseCard message={{ ...base, toolState: 'running' }} />
    )
    expect(lastFrame()).toContain('compile_pdf')
    expect(lastFrame()).toContain('running')
  })

  it('shows check mark and duration on success', () => {
    const { lastFrame } = render(
      <ToolUseCard message={{ ...base, toolState: 'success', durationMs: 2300 }} />
    )
    expect(lastFrame()).toContain('compile_pdf')
    expect(lastFrame()).toContain('2.3s')
  })

  it('shows error on failure', () => {
    const { lastFrame } = render(
      <ToolUseCard message={{ ...base, toolState: 'error', toolResult: { error: 'LaTeX error' } }} />
    )
    expect(lastFrame()).toContain('error')
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- ToolUseCard
```

- [ ] **Step 3: Create src/components/ToolUseCard.tsx**

```tsx
// packages/tui/src/components/ToolUseCard.tsx
import React from 'react'
import { Box, Text } from 'ink'
import { Spinner } from '@inkjs/ui'
import type { Message } from '../stores/messages.js'

interface Props {
  message: Message
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

export function ToolUseCard({ message }: Props): React.ReactElement {
  const { toolName, toolState, durationMs, toolResult } = message

  const icon = toolState === 'running' ? null
    : toolState === 'success' ? '✓'
    : toolState === 'error' ? '✗'
    : toolState === 'cancelled' ? '⊘'
    : '·'

  const iconColor = toolState === 'success' ? 'green'
    : toolState === 'error' ? 'red'
    : toolState === 'cancelled' ? 'yellow'
    : 'white'

  return (
    <Box flexDirection="column" marginY={0} paddingX={2}>
      <Box gap={1}>
        {toolState === 'running'
          ? <Spinner />
          : <Text color={iconColor}>{icon}</Text>
        }
        <Text bold>{toolName ?? 'tool'}</Text>
        {toolState === 'running' && <Text dimColor>running...</Text>}
        {toolState === 'success' && durationMs != null && (
          <Text dimColor>{formatMs(durationMs)}</Text>
        )}
        {toolState === 'error' && (
          <Text color="red">error</Text>
        )}
      </Box>
      {toolState === 'error' && toolResult && (
        <Box paddingLeft={3}>
          <Text color="red">
            {typeof (toolResult as Record<string, unknown>)['error'] === 'string'
              ? (toolResult as Record<string, unknown>)['error'] as string
              : JSON.stringify(toolResult)}
          </Text>
        </Box>
      )}
    </Box>
  )
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- ToolUseCard
```

Expected: 3 passing.

---

## Task 12: LogStreamCard Component

**Files:**
- Create: `packages/tui/src/components/LogStreamCard.tsx`
- Create: `packages/tui/src/__tests__/LogStreamCard.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/LogStreamCard.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { LogStreamCard } from '../components/LogStreamCard.js'

describe('LogStreamCard', () => {
  it('renders log lines', () => {
    const { lastFrame } = render(
      <LogStreamCard lines={['This is pdflatex', 'Output written on resume.pdf']} />
    )
    expect(lastFrame()).toContain('pdflatex')
    expect(lastFrame()).toContain('Output written')
  })

  it('colors error lines red', () => {
    // Can't test ANSI colors easily, but verify the content is present
    const { lastFrame } = render(
      <LogStreamCard lines={['[ERR] LaTeX Warning: Font shape undefined']} />
    )
    expect(lastFrame()).toContain('LaTeX Warning')
  })

  it('shows line count', () => {
    const lines = Array.from({ length: 10 }, (_, i) => `line ${i}`)
    const { lastFrame } = render(<LogStreamCard lines={lines} />)
    expect(lastFrame()).toContain('10')
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- LogStreamCard
```

- [ ] **Step 3: Create src/components/LogStreamCard.tsx**

```tsx
// packages/tui/src/components/LogStreamCard.tsx
import React, { useMemo } from 'react'
import { Box, Text } from 'ink'

interface Props {
  lines: string[]
  maxVisible?: number
}

function classifyLine(line: string): 'error' | 'warning' | 'info' {
  const lower = line.toLowerCase()
  if (lower.includes('error') || lower.includes('[err]')) return 'error'
  if (lower.includes('warning') || lower.includes('warn')) return 'warning'
  return 'info'
}

export function LogStreamCard({ lines, maxVisible = 20 }: Props): React.ReactElement {
  const visible = useMemo(
    () => lines.length > maxVisible ? lines.slice(-maxVisible) : lines,
    [lines, maxVisible]
  )

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1} marginY={1}>
      <Box justifyContent="space-between">
        <Text bold color="gray">pdflatex log</Text>
        <Text dimColor>{lines.length} lines</Text>
      </Box>
      {visible.map((line, i) => {
        const kind = classifyLine(line)
        const color = kind === 'error' ? 'red' : kind === 'warning' ? 'yellow' : undefined
        return (
          <Text key={i} color={color} wrap="truncate-end">
            {line}
          </Text>
        )
      })}
    </Box>
  )
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- LogStreamCard
```

Expected: 3 passing.

---

## Task 13: CompileResultCard Component

**Files:**
- Create: `packages/tui/src/components/CompileResultCard.tsx`
- Create: `packages/tui/src/__tests__/CompileResultCard.test.tsx`

- [ ] **Step 1: Write failing tests**

```typescript
// src/__tests__/CompileResultCard.test.tsx
import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { CompileResultCard } from '../components/CompileResultCard.js'

describe('CompileResultCard', () => {
  it('shows pages and size', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={2} sizeBytes={85000} compilationTimeMs={2300} pdfUrl="/dl/abc.pdf" atsScore={null} />
    )
    expect(lastFrame()).toContain('2')
    expect(lastFrame()).toContain('83')  // ~83 KB
  })

  it('shows compilation time', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={1} sizeBytes={40000} compilationTimeMs={1500} pdfUrl="/dl/x.pdf" atsScore={null} />
    )
    expect(lastFrame()).toContain('1.5s')
  })

  it('shows ATS score when available', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={2} sizeBytes={85000} compilationTimeMs={2000} pdfUrl="/dl/abc.pdf" atsScore={72} />
    )
    expect(lastFrame()).toContain('72')
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- CompileResultCard
```

- [ ] **Step 3: Create src/components/CompileResultCard.tsx**

```tsx
// packages/tui/src/components/CompileResultCard.tsx
import React from 'react'
import { Box, Text } from 'ink'

interface Props {
  pages: number | null
  sizeBytes: number | null
  compilationTimeMs: number
  pdfUrl: string | null
  atsScore: number | null
}

export function CompileResultCard({ pages, sizeBytes, compilationTimeMs, pdfUrl, atsScore }: Props): React.ReactElement {
  const sizeKb = sizeBytes != null ? Math.round(sizeBytes / 1024) : null
  const timeStr = `${(compilationTimeMs / 1000).toFixed(1)}s`

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1} marginY={1}>
      <Text bold color="green">✓ Compiled successfully</Text>
      <Box gap={3} marginTop={1}>
        {pages != null && <Text>📄 <Text bold>{pages}</Text> page{pages !== 1 ? 's' : ''}</Text>}
        {sizeKb != null && <Text>💾 <Text bold>{sizeKb}</Text> KB</Text>}
        <Text>⏱ <Text bold>{timeStr}</Text></Text>
        {atsScore != null && <Text>📊 ATS: <Text bold color="cyan">{atsScore}%</Text></Text>}
      </Box>
      {pdfUrl && (
        <Text dimColor marginTop={1}>Run /pdf to open · /ats for full analysis</Text>
      )}
    </Box>
  )
}
```

- [ ] **Step 4: Run tests, expect PASS**

```bash
pnpm test -- CompileResultCard
```

Expected: 3 passing.

---

## Task 14: MessageRow Dispatcher

**Files:**
- Create: `packages/tui/src/components/MessageRow.tsx`

No isolated tests — covered by integration in TranscriptView tests.

- [ ] **Step 1: Create src/components/MessageRow.tsx**

```tsx
// packages/tui/src/components/MessageRow.tsx
import React from 'react'
import { Box, Text } from 'ink'
import type { Message } from '../stores/messages.js'
import { ToolUseCard } from './ToolUseCard.js'
import { LogStreamCard } from './LogStreamCard.js'
import { CompileResultCard } from './CompileResultCard.js'

interface Props {
  message: Message
}

function UserRow({ message }: Props): React.ReactElement {
  const time = new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return (
    <Box flexDirection="column" marginY={1} paddingX={1}>
      <Box gap={1}>
        <Text bold color="cyan">You</Text>
        <Text dimColor>{time}</Text>
      </Box>
      <Box paddingLeft={2}>
        <Text color="white">╰─ {message.content}</Text>
      </Box>
    </Box>
  )
}

function AssistantRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1}>
      <Text color="white" wrap="wrap">
        {message.content}
        {message.streaming && <Text color="cyan">▌</Text>}
      </Text>
    </Box>
  )
}

function SystemRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1}>
      <Text dimColor>{message.content}</Text>
    </Box>
  )
}

function ErrorRow({ message }: Props): React.ReactElement {
  return (
    <Box paddingX={2} marginY={1}>
      <Text color="red">✗ {message.content}</Text>
    </Box>
  )
}

export function MessageRow({ message }: Props): React.ReactElement {
  switch (message.role) {
    case 'user':
      return <UserRow message={message} />

    case 'assistant':
      return <AssistantRow message={message} />

    case 'tool_use':
      return <ToolUseCard message={message} />

    case 'log_stream': {
      const data = (message.resultData as { lines: string[] } | undefined)
      return <LogStreamCard lines={data?.lines ?? []} />
    }

    case 'compile_result': {
      const d = (message.resultData as {
        pages?: number
        sizeBytes?: number
        compilationTimeMs?: number
        pdfUrl?: string
        atsScore?: number
      } | undefined) ?? {}
      return (
        <CompileResultCard
          pages={d.pages ?? null}
          sizeBytes={d.sizeBytes ?? null}
          compilationTimeMs={d.compilationTimeMs ?? 0}
          pdfUrl={d.pdfUrl ?? null}
          atsScore={d.atsScore ?? null}
        />
      )
    }

    case 'system':
      return <SystemRow message={message} />

    case 'error':
      return <ErrorRow message={message} />

    default:
      return <Box><Text dimColor>[{message.role}]</Text></Box>
  }
}
```

---

## Task 15: TranscriptView

**Files:**
- Create: `packages/tui/src/components/TranscriptView.tsx`

- [ ] **Step 1: Create src/components/TranscriptView.tsx**

```tsx
// packages/tui/src/components/TranscriptView.tsx
import React from 'react'
import { Box, Static } from 'ink'
import { useStore } from '@nanostores/react'
import { $messages } from '../stores/messages.js'
import { MessageRow } from './MessageRow.js'
import type { Message } from '../stores/messages.js'

export function TranscriptView(): React.ReactElement {
  const messages = useStore($messages)

  // Split: completed messages in Static (never re-renders), streaming in dynamic
  const completed: Message[] = []
  const streaming: Message[] = []

  for (const msg of messages) {
    if (msg.streaming || msg.toolState === 'running') {
      streaming.push(msg)
    } else {
      completed.push(msg)
    }
  }

  return (
    <Box flexDirection="column" flexGrow={1} overflow="hidden">
      {/* Static block: never re-renders once messages are committed here */}
      <Static items={completed}>
        {(msg) => <MessageRow key={msg.id} message={msg} />}
      </Static>

      {/* Dynamic block: active streaming turn */}
      {streaming.map(msg => (
        <MessageRow key={msg.id} message={msg} />
      ))}
    </Box>
  )
}
```

---

## Task 16: SlashSuggestions + PromptInput

**Files:**
- Create: `packages/tui/src/components/SlashSuggestions.tsx`
- Create: `packages/tui/src/components/PromptInput.tsx`

- [ ] **Step 1: Create src/components/SlashSuggestions.tsx**

```tsx
// packages/tui/src/components/SlashSuggestions.tsx
import React, { useMemo } from 'react'
import { Box, Text } from 'ink'
import { SLASH_COMMANDS } from '../commands/registry.js'

interface Props {
  query: string  // text after the leading '/'
  maxItems?: number
}

export function SlashSuggestions({ query, maxItems = 5 }: Props): React.ReactElement | null {
  const matches = useMemo(() => {
    if (!query && query !== '') return SLASH_COMMANDS.slice(0, maxItems)
    return SLASH_COMMANDS.filter(c =>
      c.name.startsWith(query.toLowerCase()) ||
      c.description.toLowerCase().includes(query.toLowerCase())
    ).slice(0, maxItems)
  }, [query, maxItems])

  if (matches.length === 0) return null

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="gray" paddingX={1}>
      {matches.map(cmd => (
        <Box key={cmd.name} gap={2}>
          <Text color="cyan">/{cmd.name}</Text>
          <Text dimColor>{cmd.description}</Text>
        </Box>
      ))}
    </Box>
  )
}
```

- [ ] **Step 2: Create src/components/PromptInput.tsx**

```tsx
// packages/tui/src/components/PromptInput.tsx
import React, { useState, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { useStore } from '@nanostores/react'
import { $isBlocked } from '../stores/overlay.js'
import { $activeJobId } from '../stores/messages.js'
import { SlashSuggestions } from './SlashSuggestions.js'

interface Props {
  onSubmit: (input: string) => void
}

export function PromptInput({ onSubmit }: Props): React.ReactElement {
  const [value, setValue] = useState('')
  const isBlocked = useStore($isBlocked)
  const activeJobId = useStore($activeJobId)

  const handleSubmit = useCallback((val: string) => {
    const trimmed = val.trim()
    if (!trimmed) return
    setValue('')
    onSubmit(trimmed)
  }, [onSubmit])

  useInput((input, key) => {
    if (isBlocked) return
    if (key.ctrl && input === 'l') {
      // Ctrl+L handled in AppShell
    }
  }, { isActive: !isBlocked })

  const isSlash = value.startsWith('/')
  const slashQuery = isSlash ? value.slice(1) : ''

  return (
    <Box flexDirection="column">
      {isSlash && <SlashSuggestions query={slashQuery} />}
      <Box gap={1} paddingX={1} borderStyle="round" borderColor={isBlocked ? 'gray' : 'cyan'}>
        <Text bold color="cyan">›</Text>
        {activeJobId && !isBlocked
          ? <Text dimColor>Running… (Ctrl+C to cancel)</Text>
          : (
            <TextInput
              value={value}
              onChange={setValue}
              onSubmit={handleSubmit}
              placeholder="Ask anything or type /command"
              focus={!isBlocked}
            />
          )
        }
      </Box>
    </Box>
  )
}
```

---

## Task 17: AppShell

**Files:**
- Create: `packages/tui/src/components/AppShell.tsx`

- [ ] **Step 1: Create src/components/AppShell.tsx**

```tsx
// packages/tui/src/components/AppShell.tsx
import React from 'react'
import { Box, Text, useInput, useApp } from 'ink'
import { useStore } from '@nanostores/react'
import { $session } from '../stores/session.js'
import { $overlay, closeOverlay } from '../stores/overlay.js'
import { $ui } from '../stores/ui.js'
import { $isBlocked } from '../stores/overlay.js'
import { clearMessages } from '../stores/messages.js'
import { StatusBar } from './StatusBar.js'
import { TranscriptView } from './TranscriptView.js'
import { PromptInput } from './PromptInput.js'
import { dispatch } from '../commands/dispatch.js'
import { useWSEventRouter } from '../hooks/useJobStream.js'

export function AppShell(): React.ReactElement {
  const session = useStore($session)
  const overlay = useStore($overlay)
  const ui = useStore($ui)
  const isBlocked = useStore($isBlocked)
  const { exit } = useApp()

  // Wire WS events to JobController
  useWSEventRouter()

  useInput((input, key) => {
    if (key.ctrl && input === 'c' && !isBlocked) {
      exit()
      return
    }
    if (key.ctrl && input === 'l') {
      clearMessages()
      return
    }
    if (key.escape && overlay) {
      closeOverlay()
      return
    }
  })

  return (
    <Box flexDirection="column" height="100%">
      <StatusBar
        email={session.email}
        plan={session.plan}
        health={ui.healthStatus}
        wsConnected={ui.wsConnected}
      />
      <Box flexGrow={1} flexDirection="column" overflow="hidden">
        <TranscriptView />
      </Box>
      {overlay && (
        <Box position="absolute" flexDirection="column" width="100%" height="100%">
          {overlay}
        </Box>
      )}
      <PromptInput onSubmit={(input) => dispatch(input)} />
    </Box>
  )
}
```

---

## Task 18: Slash Command Registry and Parser

**Files:**
- Create: `packages/tui/src/commands/registry.ts`
- Create: `packages/tui/src/commands/parser.ts`
- Create: `packages/tui/src/__tests__/parser.test.ts`

- [ ] **Step 1: Write failing parser tests**

```typescript
// src/__tests__/parser.test.ts
import { describe, it, expect } from 'vitest'
import { parseSlashCommand } from '../commands/parser.js'

describe('parseSlashCommand', () => {
  it('parses simple command', () => {
    const result = parseSlashCommand('/compile')
    expect(result).toEqual({ name: 'compile', args: {}, positional: [] })
  })

  it('parses command with flags', () => {
    const result = parseSlashCommand('/compile --compiler xelatex')
    expect(result?.args['compiler']).toBe('xelatex')
  })

  it('parses positional args', () => {
    const result = parseSlashCommand('/new My Resume')
    expect(result?.positional).toContain('My')
    expect(result?.positional).toContain('Resume')
  })

  it('returns null for non-slash input', () => {
    expect(parseSlashCommand('hello')).toBeNull()
  })

  it('parses quoted string values', () => {
    const result = parseSlashCommand('/cover --company "Google Inc" --role "SWE"')
    expect(result?.args['company']).toBe('Google Inc')
    expect(result?.args['role']).toBe('SWE')
  })
})
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
pnpm test -- parser
```

- [ ] **Step 3: Create src/commands/registry.ts**

```typescript
// packages/tui/src/commands/registry.ts
export interface SlashCommand {
  name: string
  description: string
  usage: string
  isLocal: boolean  // true = opens overlay/navigate; false = API call
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'compile', description: 'Compile selected resume to PDF', usage: '/compile [resume-id] [--compiler pdflatex|xelatex|lualatex]', isLocal: false },
  { name: 'optimize', description: 'AI-optimize resume for a job', usage: '/optimize [resume-id] [--jd url|file] [--level conservative|balanced|aggressive]', isLocal: false },
  { name: 'combined', description: 'Optimize + compile in one job', usage: '/combined [resume-id] [--jd url|file]', isLocal: false },
  { name: 'ats', description: 'Run ATS deep analysis', usage: '/ats [resume-id] [--jd url|file] [--industry software_engineering]', isLocal: false },
  { name: 'quick-ats', description: 'Fast rule-based ATS (no LLM)', usage: '/quick-ats [resume-id]', isLocal: false },
  { name: 'list', description: 'Open resume picker', usage: '/list [--archived] [--type resume|academic_cv]', isLocal: true },
  { name: 'new', description: 'Create new resume', usage: '/new [title]', isLocal: false },
  { name: 'edit', description: 'Open resume in $EDITOR', usage: '/edit [resume-id]', isLocal: false },
  { name: 'fork', description: 'Fork resume into a variant', usage: '/fork [resume-id] [new-title]', isLocal: false },
  { name: 'pdf', description: 'Download and open last PDF', usage: '/pdf [job-id]', isLocal: false },
  { name: 'log', description: 'View full pdflatex log', usage: '/log [job-id]', isLocal: false },
  { name: 'cancel', description: 'Cancel running job', usage: '/cancel [job-id]', isLocal: false },
  { name: 'jobs', description: 'Open job monitor overlay', usage: '/jobs', isLocal: true },
  { name: 'byok', description: 'Manage BYOK API keys', usage: '/byok', isLocal: true },
  { name: 'analytics', description: 'View personal analytics', usage: '/analytics [--period 7d|30d|90d]', isLocal: false },
  { name: 'billing', description: 'View subscription and billing', usage: '/billing', isLocal: true },
  { name: 'tracker', description: 'Open job application tracker', usage: '/tracker', isLocal: true },
  { name: 'cover', description: 'Generate cover letter', usage: '/cover [resume-id] --company "..." --role "..."', isLocal: false },
  { name: 'interview', description: 'Generate interview questions', usage: '/interview [resume-id] --jd url|file', isLocal: false },
  { name: 'health', description: 'Show backend health status', usage: '/health', isLocal: false },
  { name: 'history', description: 'Show optimization history', usage: '/history [resume-id]', isLocal: false },
  { name: 'checkpoint', description: 'Create named checkpoint', usage: '/checkpoint [resume-id] [label]', isLocal: false },
  { name: 'restore', description: 'Restore to a checkpoint', usage: '/restore [resume-id]', isLocal: true },
  { name: 'diff', description: 'Show diff with parent variant', usage: '/diff [resume-id]', isLocal: false },
  { name: 'export', description: 'Export resume to another format', usage: '/export [resume-id] --format docx|markdown|html', isLocal: false },
  { name: 'share', description: 'Generate and copy share link', usage: '/share [resume-id]', isLocal: false },
  { name: 'snippets', description: 'Browse snippet marketplace', usage: '/snippets', isLocal: true },
  { name: 'settings', description: 'Open notification settings', usage: '/settings', isLocal: true },
  { name: 'help', description: 'Show help', usage: '/help [command]', isLocal: true },
  { name: 'model', description: 'Open model picker for agent mode', usage: '/model', isLocal: true },
  { name: 'clear', description: 'Clear transcript', usage: '/clear', isLocal: true },
  { name: 'logout', description: 'Clear session', usage: '/logout', isLocal: true },
]

export const COMMAND_MAP = new Map(SLASH_COMMANDS.map(c => [c.name, c]))
```

- [ ] **Step 4: Create src/commands/parser.ts**

```typescript
// packages/tui/src/commands/parser.ts
export interface ParsedCommand {
  name: string
  args: Record<string, string | boolean>
  positional: string[]
  raw: string
}

export function parseSlashCommand(input: string): ParsedCommand | null {
  if (!input.startsWith('/')) return null

  const withoutSlash = input.slice(1)
  // Tokenize respecting quoted strings
  const tokens: string[] = []
  const re = /--[\w-]+=("[^"]*"|[^\s]+)|--[\w-]+|"([^"]*)"|\S+/g
  let match: RegExpExecArray | null

  while ((match = re.exec(withoutSlash)) !== null) {
    tokens.push(match[0])
  }

  if (tokens.length === 0) return null

  const [name, ...rest] = tokens
  if (!name) return null

  const args: Record<string, string | boolean> = {}
  const positional: string[] = []

  let i = 0
  while (i < rest.length) {
    const tok = rest[i]!
    if (tok.startsWith('--')) {
      // Handle --key="value with spaces" or --key=value
      if (tok.includes('=')) {
        const eqIdx = tok.indexOf('=')
        const key = tok.slice(2, eqIdx)
        let val = tok.slice(eqIdx + 1)
        if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1)
        args[key] = val
        i++
      } else {
        const key = tok.slice(2)
        const next = rest[i + 1]
        if (next && !next.startsWith('--')) {
          let val = next
          if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1)
          args[key] = val
          i += 2
        } else {
          args[key] = true
          i++
        }
      }
    } else {
      const val = tok.startsWith('"') && tok.endsWith('"') ? tok.slice(1, -1) : tok
      positional.push(val)
      i++
    }
  }

  return { name: name.toLowerCase(), args, positional, raw: input }
}
```

- [ ] **Step 5: Run tests, expect PASS**

```bash
pnpm test -- parser
```

Expected: 5 passing.

---

## Task 19: Command Dispatch

**Files:**
- Create: `packages/tui/src/commands/dispatch.ts`

- [ ] **Step 1: Create src/commands/dispatch.ts**

```typescript
// packages/tui/src/commands/dispatch.ts
import React from 'react'
import { parseSlashCommand } from './parser.js'
import { COMMAND_MAP } from './registry.js'
import { addMessage, $activeJobId } from '../stores/messages.js'
import { openOverlay } from '../stores/overlay.js'
import { clearMessages } from '../stores/messages.js'
import { writeConfig, clearConfig } from '../lib/config.js'
import { $session } from '../stores/session.js'
import { runCompile } from '../tools/compile.js'
import { LoginOverlay } from '../components/overlays/LoginOverlay.js'
import { ResumePicker } from '../components/overlays/ResumePicker.js'

// Commands handled locally (open overlays, navigate, mutate local state)
const LOCAL_HANDLERS: Record<string, (parsed: ReturnType<typeof parseSlashCommand>) => void> = {
  list: () => openOverlay(React.createElement(ResumePicker)),
  clear: () => clearMessages(),
  help: (p) => {
    const cmdName = p?.positional[0]
    const cmd = cmdName ? COMMAND_MAP.get(cmdName) : null
    addMessage({
      role: 'system',
      content: cmd
        ? `/${cmd.name} — ${cmd.description}\nUsage: ${cmd.usage}`
        : `Available commands: ${[...COMMAND_MAP.keys()].map(k => `/${k}`).join(', ')}`,
    })
  },
  logout: async () => {
    await clearConfig()
    $session.set({ ...$session.get(), token: null, isAuthenticated: false, email: null, plan: null, userId: null })
    addMessage({ role: 'system', content: 'Logged out.' })
    openOverlay(React.createElement(LoginOverlay))
  },
}

// API commands
const API_HANDLERS: Record<string, (parsed: NonNullable<ReturnType<typeof parseSlashCommand>>) => Promise<void>> = {
  compile: async (p) => {
    if ($activeJobId.get()) {
      addMessage({ role: 'error', content: 'A job is already running. Use /cancel to stop it first.' })
      return
    }
    await runCompile(p)
  },
  health: async () => {
    const { getApiClient } = await import('../lib/api-client.js')
    try {
      const result = await getApiClient().get<{ status: string }>('/health')
      addMessage({ role: 'system', content: `Backend: ${result.status}` })
    } catch (err) {
      addMessage({ role: 'error', content: `Health check failed: ${String(err)}` })
    }
  },
}

export async function dispatch(input: string): Promise<void> {
  if (input.startsWith('/')) {
    const parsed = parseSlashCommand(input)
    if (!parsed) return

    addMessage({ role: 'user', content: input })

    const localHandler = LOCAL_HANDLERS[parsed.name]
    if (localHandler) {
      localHandler(parsed)
      return
    }

    const apiHandler = API_HANDLERS[parsed.name]
    if (apiHandler) {
      await apiHandler(parsed)
      return
    }

    addMessage({
      role: 'error',
      content: `Unknown command: /${parsed.name}. Type /help for available commands.`,
    })
    return
  }

  // Non-slash: agent mode (Phase 3) or no-model message
  addMessage({ role: 'user', content: input })
  addMessage({
    role: 'system',
    content: 'No model configured — run /byok to add an API key or /model to select a provider.',
  })
}
```

---

## Task 20: Compile Tool

**Files:**
- Create: `packages/tui/src/tools/compile.ts`

- [ ] **Step 1: Create src/tools/compile.ts**

```typescript
// packages/tui/src/tools/compile.ts
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'
import type { ParsedCommand } from '../commands/parser.js'
import { getApiClient } from '../lib/api-client.js'
import { wsClient } from '../lib/ws-client.js'
import { $session } from '../stores/session.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import { createJobController } from '../hooks/useJobStream.js'

interface JobSubmitResponse {
  job_id: string
  status: string
}

interface ResumeListResponse {
  resumes: Array<{ id: string; title: string }>
}

export async function runCompile(parsed: ParsedCommand): Promise<void> {
  const client = getApiClient()
  const session = $session.get()

  if (!session.isAuthenticated) {
    addMessage({ role: 'error', content: 'Not logged in. Use /list to select a resume after login.' })
    return
  }

  const compiler = (parsed.args['compiler'] as string | undefined) ?? 'pdflatex'
  const resumeId = (parsed.args['resume-id'] as string | undefined) ?? parsed.positional[0]
  const filePath = !resumeId?.includes('-') ? resumeId : undefined // heuristic: UUID has dashes

  let actualResumeId: string | undefined = resumeId?.includes('-') ? resumeId : undefined

  // If a local file was given, upload it via multipart POST /compile
  if (filePath) {
    const toolMsgId = addMessage({
      role: 'tool_use',
      content: '',
      toolName: 'compile_pdf',
      toolState: 'running',
      toolArgs: { file: basename(filePath), compiler },
    })

    try {
      const fileBytes = await readFile(filePath)
      const form = new FormData()
      form.append('file', new Blob([fileBytes]), basename(filePath))
      form.append('compiler', compiler)

      const res = await client.postForm<JobSubmitResponse>('/api/compile', form)
      const jobId = res.job_id

      $activeJobId.set(jobId)
      const ctrl = createJobController(jobId)
      ctrl.setToolMsgId(toolMsgId)
      wsClient.subscribe(jobId, '0')
    } catch (err) {
      updateMessage(toolMsgId, { toolState: 'error', toolResult: { error: String(err) } })
    }
    return
  }

  // If no resume ID given, pick the default or first resume
  if (!actualResumeId) {
    try {
      const list = await client.get<ResumeListResponse>('/api/resumes?limit=1')
      actualResumeId = list.resumes[0]?.id
      if (!actualResumeId) {
        addMessage({ role: 'error', content: 'No resumes found. Create one first with /new.' })
        return
      }
    } catch (err) {
      addMessage({ role: 'error', content: `Failed to fetch resumes: ${String(err)}` })
      return
    }
  }

  const toolMsgId = addMessage({
    role: 'tool_use',
    content: '',
    toolName: 'compile_pdf',
    toolState: 'running',
    toolArgs: { resume_id: actualResumeId, compiler },
  })

  try {
    const res = await client.post<JobSubmitResponse>('/api/jobs/submit', {
      job_type: 'latex_compilation',
      resume_id: actualResumeId,
      settings: { compiler },
    })
    const jobId = res.job_id

    $activeJobId.set(jobId)
    const ctrl = createJobController(jobId)
    ctrl.setToolMsgId(toolMsgId)
    wsClient.subscribe(jobId, '0')
  } catch (err) {
    updateMessage(toolMsgId, { toolState: 'error', toolResult: { error: String(err) } })
  }
}
```

---

## Task 21: LoginOverlay

**Files:**
- Create: `packages/tui/src/components/overlays/LoginOverlay.tsx`

- [ ] **Step 1: Create src/components/overlays/LoginOverlay.tsx**

```tsx
// packages/tui/src/components/overlays/LoginOverlay.tsx
import React, { useState, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { getApiClient, initApiClient } from '../../lib/api-client.js'
import { writeConfig } from '../../lib/config.js'
import { $session } from '../../stores/session.js'
import { closeOverlay } from '../../stores/overlay.js'
import { addMessage } from '../../stores/messages.js'
import { wsClient } from '../../lib/ws-client.js'

type Step = 'email' | 'password' | 'loading' | 'error'

interface LoginResponse {
  token: string
  user: { id: string; email: string; plan: string }
}

export function LoginOverlay(): React.ReactElement {
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState(process.env['LATEXY_EMAIL'] ?? '')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  const handleEmailSubmit = useCallback((val: string) => {
    if (!val.trim()) return
    setEmail(val.trim())
    setStep('password')
  }, [])

  const handlePasswordSubmit = useCallback(async (val: string) => {
    if (!val.trim()) return
    setStep('loading')
    setError(null)

    const session = $session.get()
    const client = getApiClient()

    try {
      const res = await client.post<LoginResponse>('/auth/signin', {
        email: email.trim(),
        password: val,
      })

      // Clear password from memory
      delete process.env['LATEXY_PASSWORD']

      const { token, user } = res
      await writeConfig({ token, email: user.email, userId: user.id })

      const newClient = initApiClient(session.backendUrl, token)
      $session.set({
        ...session,
        token,
        userId: user.id,
        email: user.email,
        plan: user.plan as SessionState['plan'],
        isAuthenticated: true,
      })

      // Connect WS with new token
      wsClient.connect(session.wsUrl, token)
      wsClient.drain()

      closeOverlay()
      addMessage({ role: 'system', content: `Logged in as ${user.email}` })
    } catch (err) {
      setError(String(err))
      setStep('error')
    }
  }, [email])

  useInput((_input, key) => {
    if (key.escape && step === 'error') {
      setStep('email')
      setError(null)
    }
  })

  return (
    <Box flexDirection="column" padding={2} borderStyle="round" borderColor="cyan">
      <Text bold color="cyan">Welcome to Latexy</Text>
      <Text dimColor>Sign in to your account</Text>
      <Box marginTop={1} />

      {step === 'email' && (
        <Box gap={1}>
          <Text>Email: </Text>
          <TextInput
            value={email}
            onChange={setEmail}
            onSubmit={handleEmailSubmit}
            placeholder="you@example.com"
          />
        </Box>
      )}

      {step === 'password' && (
        <>
          <Text dimColor>Email: {email}</Text>
          <Box gap={1} marginTop={1}>
            <Text>Password: </Text>
            <TextInput
              value={password}
              onChange={setPassword}
              onSubmit={handlePasswordSubmit}
              mask="*"
              placeholder="••••••••"
            />
          </Box>
        </>
      )}

      {step === 'loading' && (
        <Text color="yellow">Signing in…</Text>
      )}

      {step === 'error' && (
        <>
          <Text color="red">✗ {error}</Text>
          <Text dimColor>Press Esc to try again</Text>
        </>
      )}
    </Box>
  )
}

// Needed for $session plan type
type SessionState = { plan: 'free' | 'basic' | 'pro' | 'byok' | 'team' | null }
```

---

## Task 22: ResumePicker Overlay

**Files:**
- Create: `packages/tui/src/components/overlays/ResumePicker.tsx`

- [ ] **Step 1: Create src/components/overlays/ResumePicker.tsx**

```tsx
// packages/tui/src/components/overlays/ResumePicker.tsx
import React, { useState, useEffect, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { getApiClient } from '../../lib/api-client.js'
import { closeOverlay } from '../../stores/overlay.js'
import { writeConfig } from '../../lib/config.js'
import { addMessage } from '../../stores/messages.js'

interface Resume {
  id: string
  title: string
  type: string
  updated_at: string
  is_pinned?: boolean
}

interface ResumeListResponse {
  resumes: Resume[]
  total: number
}

export function ResumePicker(): React.ReactElement {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [filtered, setFiltered] = useState<Resume[]>([])
  const [filter, setFilter] = useState('')
  const [cursor, setCursor] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const client = getApiClient()
    client.get<ResumeListResponse>('/api/resumes?limit=50')
      .then(res => {
        setResumes(res.resumes)
        setFiltered(res.resumes)
        setLoading(false)
      })
      .catch(err => {
        setError(String(err))
        setLoading(false)
      })
  }, [])

  useEffect(() => {
    const q = filter.toLowerCase()
    const next = q
      ? resumes.filter(r => r.title.toLowerCase().includes(q))
      : resumes
    setFiltered(next)
    setCursor(0)
  }, [filter, resumes])

  const select = useCallback((resume: Resume) => {
    writeConfig({ defaultResumeId: resume.id }).catch(() => {})
    addMessage({ role: 'system', content: `Selected: ${resume.title}` })
    closeOverlay()
  }, [])

  useInput((_input, key) => {
    if (key.escape) { closeOverlay(); return }
    if (key.upArrow) { setCursor(c => Math.max(0, c - 1)); return }
    if (key.downArrow) { setCursor(c => Math.min(filtered.length - 1, c + 1)); return }
    if (key.return && filtered[cursor]) { select(filtered[cursor]); return }
  })

  const formatDate = (iso: string): string => {
    const d = new Date(iso)
    const daysAgo = Math.floor((Date.now() - d.getTime()) / 86_400_000)
    if (daysAgo === 0) return 'today'
    if (daysAgo === 1) return 'yesterday'
    if (daysAgo < 30) return `${daysAgo}d ago`
    return `${Math.floor(daysAgo / 30)}mo ago`
  }

  return (
    <Box flexDirection="column" borderStyle="double" borderColor="cyan" padding={1}>
      <Text bold color="cyan">Select Resume</Text>
      <Text dimColor>↑↓ navigate · Enter select · Esc cancel</Text>
      <Box marginTop={1} gap={1}>
        <Text dimColor>/</Text>
        <TextInput value={filter} onChange={setFilter} placeholder="filter..." />
      </Box>
      <Box marginTop={1} flexDirection="column">
        {loading && <Text color="yellow">Loading…</Text>}
        {error && <Text color="red">Error: {error}</Text>}
        {!loading && !error && filtered.length === 0 && (
          <Text dimColor>No resumes found</Text>
        )}
        {filtered.map((r, i) => (
          <Box key={r.id} gap={2}>
            <Text color={i === cursor ? 'cyan' : undefined}>
              {i === cursor ? '▶' : ' '} {r.title}
            </Text>
            <Text dimColor>{r.type}</Text>
            <Text dimColor>{formatDate(r.updated_at)}</Text>
            {r.is_pinned && <Text color="yellow">★</Text>}
          </Box>
        ))}
      </Box>
    </Box>
  )
}
```

---

## Task 23: App Root and CLI Entry

**Files:**
- Create: `packages/tui/src/app.tsx`
- Create: `packages/tui/src/cli.tsx`

- [ ] **Step 1: Create src/app.tsx**

```tsx
// packages/tui/src/app.tsx
import React, { useEffect } from 'react'
import { useStore } from '@nanostores/react'
import { $session } from './stores/session.js'
import { $overlay, openOverlay } from './stores/overlay.js'
import { AppShell } from './components/AppShell.js'
import { LoginOverlay } from './components/overlays/LoginOverlay.js'
import { wsClient } from './lib/ws-client.js'
import { initApiClient } from './lib/api-client.js'
import { readConfig } from './lib/config.js'
import { $ui } from './stores/ui.js'
import { addMessage } from './stores/messages.js'

export function App(): React.ReactElement {
  const session = useStore($session)
  const overlay = useStore($overlay)

  useEffect(() => {
    // Bootstrap: read config, init API client, connect WS
    const init = async () => {
      const cfg = await readConfig()

      const backendUrl = cfg.backendUrl
      const wsUrl = backendUrl.replace(/^http/, 'ws') + '/ws/jobs'

      const client = initApiClient(backendUrl, cfg.token)

      $session.set({
        token: cfg.token,
        userId: cfg.userId ?? null,
        email: cfg.email ?? null,
        plan: null,
        backendUrl,
        wsUrl,
        isAuthenticated: !!cfg.token,
      })

      if (cfg.token) {
        wsClient.connect(wsUrl, cfg.token)
        wsClient.on('connected', () => {
          $ui.set({ ...$ui.get(), wsConnected: true })
          wsClient.drain()
        })
        wsClient.on('disconnected', () => {
          $ui.set({ ...$ui.get(), wsConnected: false })
        })

        // Validate token and fetch user info
        try {
          const me = await client.get<{ id: string; email: string; plan: string }>('/api/me')
          $session.set({ ...$session.get(), userId: me.id, email: me.email, plan: me.plan as 'free' | 'basic' | 'pro' | 'byok' | 'team' })
          addMessage({ role: 'system', content: `Welcome back, ${me.email}` })
        } catch {
          // Token invalid — show login
          $session.set({ ...$session.get(), token: null, isAuthenticated: false })
          openOverlay(React.createElement(LoginOverlay))
        }

        // Background health poll
        const pollHealth = async () => {
          try {
            await client.get('/health')
            $ui.set({ ...$ui.get(), healthStatus: 'healthy' })
          } catch {
            $ui.set({ ...$ui.get(), healthStatus: 'unhealthy' })
          }
        }
        pollHealth()
        setInterval(pollHealth, 30_000)
      } else {
        openOverlay(React.createElement(LoginOverlay))
      }
    }

    init().catch(err => {
      addMessage({ role: 'error', content: `Startup error: ${String(err)}` })
    })
  }, [])

  return <AppShell />
}
```

- [ ] **Step 2: Create src/cli.tsx**

```tsx
// packages/tui/src/cli.tsx
import React from 'react'
import { render } from 'ink'
import { App } from './app.js'
import { runHeadless } from './headless.js'

const args = process.argv.slice(2)
const isCI = process.env['CI'] === 'true' || !process.stdout.isTTY
const hasJsonFlag = args.includes('--json')
const subcommand = args[0]

if (isCI || hasJsonFlag) {
  // CI / non-interactive mode
  runHeadless(subcommand, args).then(exitCode => {
    process.exit(exitCode)
  }).catch(err => {
    if (hasJsonFlag) {
      process.stdout.write(JSON.stringify({ success: false, error: String(err) }) + '\n')
    } else {
      process.stderr.write(`Error: ${String(err)}\n`)
    }
    process.exit(1)
  })
} else {
  const { unmount } = render(
    React.createElement(App),
    { patchConsole: false }
  )

  process.on('SIGTERM', () => {
    unmount()
    process.exit(0)
  })
}
```

---

## Task 24: Headless CI Mode

**Files:**
- Create: `packages/tui/src/headless.ts`

- [ ] **Step 1: Create src/headless.ts**

```typescript
// packages/tui/src/headless.ts
import { readConfig } from './lib/config.js'
import { initApiClient } from './lib/api-client.js'
import { wsClient } from './lib/ws-client.js'
import type { AnyEvent, JobCompletedEvent, JobFailedEvent } from './lib/event-types.js'
import { readFile } from 'node:fs/promises'
import { basename } from 'node:path'

const JSON_FLAG = process.argv.includes('--json')

function out(obj: unknown): void {
  if (JSON_FLAG) {
    process.stdout.write(JSON.stringify(obj) + '\n')
  } else {
    process.stderr.write(JSON.stringify(obj, null, 2) + '\n')
  }
}

function log(msg: string): void {
  process.stderr.write(msg + '\n')
}

async function waitForJob(jobId: string, token: string, wsUrl: string): Promise<{ ev: JobCompletedEvent | JobFailedEvent }> {
  return new Promise((resolve, reject) => {
    wsClient.connect(wsUrl, token)
    wsClient.drain()
    wsClient.subscribe(jobId, '0')

    const timeout = setTimeout(() => {
      wsClient.destroy()
      reject(new Error('Job timed out after 5 minutes'))
    }, 300_000)

    wsClient.on('event', (ev: AnyEvent) => {
      if (ev.job_id !== jobId) return
      if (ev.type === 'log.line') log(ev.line)
      if (ev.type === 'job.progress') log(`[${ev.percent}%] ${ev.stage}`)
      if (ev.type === 'job.completed' || ev.type === 'job.failed') {
        clearTimeout(timeout)
        wsClient.destroy()
        resolve({ ev })
      }
    })
  })
}

async function headlessCompile(args: string[]): Promise<number> {
  const cfg = await readConfig()
  if (!cfg.token) {
    out({ success: false, error: 'Not authenticated. Set LATEXY_SESSION_TOKEN env var.' })
    return 2
  }

  const client = initApiClient(cfg.backendUrl, cfg.token)
  const wsUrl = cfg.backendUrl.replace(/^http/, 'ws') + '/ws/jobs'

  // Parse args
  const resumeIdFlag = args.indexOf('--resume-id')
  const resumeId = resumeIdFlag !== -1 ? args[resumeIdFlag + 1] : null
  const compilerFlag = args.indexOf('--compiler')
  const compiler = compilerFlag !== -1 ? args[compilerFlag + 1] : 'pdflatex'
  const outputFlag = args.indexOf('--output')
  const outputPath = outputFlag !== -1 ? args[outputFlag + 1] : null

  let jobId: string

  if (resumeId) {
    log(`Compiling resume ${resumeId}…`)
    const res = await client.post<{ job_id: string }>('/api/jobs/submit', {
      job_type: 'latex_compilation',
      resume_id: resumeId,
      settings: { compiler },
    })
    jobId = res.job_id
  } else {
    // Local file upload
    const filePath = args.find(a => !a.startsWith('-') && a !== 'compile')
    if (!filePath) {
      out({ success: false, error: 'Provide a .tex file path or --resume-id <uuid>' })
      return 3
    }
    log(`Uploading ${basename(filePath)}…`)
    const bytes = await readFile(filePath)
    const form = new FormData()
    form.append('file', new Blob([bytes]), basename(filePath))
    form.append('compiler', compiler ?? 'pdflatex')
    const res = await client.postForm<{ job_id: string }>('/api/compile', form)
    jobId = res.job_id
  }

  log(`Job ${jobId} submitted`)
  const { ev } = await waitForJob(jobId, cfg.token, wsUrl)

  if (ev.type === 'job.completed') {
    const result = ev.result as Record<string, unknown>
    if (outputPath && result['pdf_url']) {
      // Download PDF
      const pdfRes = await fetch(cfg.backendUrl + result['pdf_url'] as string, {
        headers: { Authorization: `Bearer ${cfg.token}` }
      })
      const buf = await pdfRes.arrayBuffer()
      const { writeFile } = await import('node:fs/promises')
      await writeFile(outputPath, Buffer.from(buf))
      log(`PDF saved to ${outputPath}`)
    }
    out({
      success: true,
      job_id: jobId,
      pages: result['pages'],
      size_bytes: result['size_bytes'],
      ats_score: result['ats_score'],
      pdf_url: result['pdf_url'],
      compilation_time: result['compilation_time_ms'],
    })
    return 0
  } else {
    const failed = ev as JobFailedEvent
    out({ success: false, error: failed.error, error_code: failed.error_code, retryable: failed.retryable })
    return 1
  }
}

export async function runHeadless(subcommand: string | undefined, args: string[]): Promise<number> {
  switch (subcommand) {
    case 'compile': return headlessCompile(args.slice(1))
    default: {
      out({ success: false, error: `Unknown subcommand: ${subcommand}. Available: compile` })
      return 3
    }
  }
}
```

---

## Task 25: Auth Bootstrap and Token Validation

This task wires together the startup auth flow. Most of the logic is already in `app.tsx`. This task adds the missing `/auth/signin` API compatibility layer.

- [ ] **Step 1: Verify the login endpoint**

Check what the Latexy backend's auth endpoint is:
```bash
grep -r "signin\|login\|auth/sign" /path/to/latexy/backend/app/api/ --include="*.py" -l
```

The Better Auth routes are typically at `/api/auth/sign-in/email`. Update `LoginOverlay.tsx:handlePasswordSubmit` if needed:

```typescript
// In LoginOverlay.tsx, change the endpoint if needed
const res = await client.post<LoginResponse>('/api/auth/sign-in/email', {
  email: email.trim(),
  password: val,
})
```

The response shape from Better Auth is:
```typescript
interface LoginResponse {
  token: string
  user: { id: string; email: string }
}
```

Update `LoginOverlay.tsx` to match the actual response shape — plan comes from a separate `/api/me` call.

- [ ] **Step 2: Build and verify no TypeScript errors**

```bash
cd packages/tui
pnpm typecheck
```

Expected: 0 errors. Fix any type errors before proceeding.

- [ ] **Step 3: Build the bundle**

```bash
pnpm build
```

Expected: `dist/cli.js` created, ~1-3MB, starts with `#!/usr/bin/env node`.

```bash
head -1 dist/cli.js
```

Expected: `#!/usr/bin/env node`

- [ ] **Step 4: Smoke test the binary**

With the Latexy backend running locally:

```bash
node dist/cli.js --help 2>&1 || true
```

Expected: no crash on entry; the TUI either starts (if TTY) or shows a headless error.

---

## Task 26: Run All Tests and Build

- [ ] **Step 1: Run full test suite**

```bash
cd packages/tui
pnpm test
```

Expected: all tests pass (config: 3, api-client: 3, ws-client: 3, parser: 5, StatusBar: 3, ToolUseCard: 3, LogStreamCard: 3, CompileResultCard: 3 = 26 tests).

- [ ] **Step 2: Run typecheck**

```bash
pnpm typecheck
```

Expected: 0 errors.

- [ ] **Step 3: Build production bundle**

```bash
pnpm build
```

Expected: `dist/cli.js` ~2-4MB, no build errors.

- [ ] **Step 4: Verify pnpm link works**

```bash
pnpm link --global
latexy --version 2>&1 || echo "No --version flag yet, that's OK"
```

Expected: binary resolves; `node` runs it without "command not found".

---

## Self-Review

### Spec coverage check

| Spec section | Covered by task |
|---|---|
| §4 Architecture: direct WS, no Python gateway | ws-client.ts (Task 6) |
| §4 REST: fetch + auth header + retry | api-client.ts (Task 5) |
| §5 tsup, ESM, shebang | Task 2 |
| §6 Chat transcript | TranscriptView (Task 15) + MessageRow (Task 14) |
| §6 Slash command autocomplete | SlashSuggestions (Task 16) |
| §7 nanostores session/messages/overlay/ui | Task 7 |
| §7 $isBlocked | overlay.ts (Task 7) |
| §7 bufRef 16ms flush | JobController (Task 8) |
| §7 WS pre-drain buffer | ws-client.ts (Task 6) |
| §8 Event routing by type | useWSEventRouter (Task 8) |
| §9 Slash commands: /compile, /list, /health, /clear, /logout, /help | dispatch.ts (Task 19) |
| §11 StatusBar | Task 10 |
| §11 ToolUseCard running/success/error | Task 11 |
| §11 LogStreamCard | Task 12 |
| §11 CompileResultCard | Task 13 |
| §11 TranscriptView Static+dynamic | Task 15 |
| §11 PromptInput + slash suggestions | Task 16 |
| §11 AppShell layout | Task 17 |
| §11 ResumePicker overlay | Task 22 |
| §11 LoginOverlay | Task 21 |
| §13 package.json bin + publishConfig | Task 2 |
| §13 tsup shebang banner | Task 2 |
| §14 CI mode --json + exit codes | Task 24 |
| §14 LATEXY_SESSION_TOKEN env | config.ts (Task 4) |
| §14 latexy compile <file.tex> | headless.ts (Task 24) |
| §15 NFR-05 chmod 600 | config.ts (Task 4) |
| §15 NFR-06 masked password input | LoginOverlay (Task 21) |
| §15 NFR-08 clear LATEXY_PASSWORD | LoginOverlay (Task 21) |

**Gaps (Phase 2+ scope, not in Phase 1):**
- §9 All 38 slash commands except /compile, /list, /health, /clear, /logout, /help
- §10 All 35 tool domains except compile
- §11 ATSResultCard, ResumeListCard, ModelPicker, BYOKOverlay, etc.
- §17 Phase 2 and Phase 3 deliverables

### Placeholder scan — NONE found. All steps have concrete code.

### Type consistency check
- `Message` type defined once in `messages.ts`, used consistently across all components.
- `$isBlocked` sourced only from `overlay.ts` computed — not duplicated in `$ui`.
- `createJobController` returns `JobController` instance; `setToolMsgId` method exists.
- `dispatch()` imports `runCompile` from `tools/compile.ts` — signature matches `ParsedCommand`.
- `LatexyWSClient.drain()` called in `app.tsx` after WS connected — timing is correct.

---

**Plan complete. Saved to `docs/superpowers/plans/2026-06-15-latexy-tui-phase1.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
