import { readConfig } from './lib/config.js'
import type { LatexyConfig } from './lib/config.js'
import { initApiClient } from './lib/api-client.js'
import type { ApiClient } from './lib/api-client.js'
import { wsClient } from './lib/ws-client.js'
import type { WSServerError, WSSocketError } from './lib/ws-client.js'
import { resolveAtsScore } from './lib/event-types.js'
import type { AnyEvent, JobCancelledEvent, JobCompletedEvent, JobFailedEvent } from './lib/event-types.js'
import { readFile, writeFile } from 'node:fs/promises'
import { basename } from 'node:path'

const useJson = process.argv.includes('--json')

// Server-side rejections that will never resolve on their own — abort instead of waiting out the
// timeout. `rate_limited` is deliberately absent: ws_routes' limiter is a soft per-connection
// throttle that drops the one frame and keeps going, so we retry the subscribe instead of aborting.
const FATAL_WS_ERROR_CODES = new Set(['forbidden', 'invalid_request'])
const UNREACHABLE_ERROR_CODES = new Set(['ECONNREFUSED', 'ENOTFOUND', 'EHOSTUNREACH', 'ENETUNREACH', 'ECONNRESET'])
const RATE_LIMIT_RETRY_MS = 1_000
const MAX_RATE_LIMIT_RETRIES = 5

/** Headless flags that consume the following token as their value. */
const VALUE_FLAGS = new Set([
  '--resume-id', '--compiler', '--output', '--jd', '--level', '--model',
  '--industry', '--page', '--limit',
])
const BOOLEAN_FLAGS = new Set(['--json', '--wait'])

/** Options shared by every machine-readable command. */
const COMMON_HEADLESS_FLAGS = new Set(['--json'])

/**
 * Keep the headless CLI contract explicit. A flag accepted by one command is
 * not silently accepted by another: this catches typos and prevents a value
 * intended for one workflow from changing another workflow's positionals.
 */
const HEADLESS_ALLOWED_FLAGS: Record<string, ReadonlySet<string>> = {
  compile: new Set([...COMMON_HEADLESS_FLAGS, '--resume-id', '--compiler', '--output']),
  optimize: new Set([...COMMON_HEADLESS_FLAGS, '--jd', '--level', '--model']),
  ats: new Set([...COMMON_HEADLESS_FLAGS, '--jd', '--industry']),
  status: new Set([...COMMON_HEADLESS_FLAGS, '--wait']),
  list: new Set([...COMMON_HEADLESS_FLAGS, '--page', '--limit']),
}

const KNOWN_HEADLESS_FLAGS = new Set(
  Object.values(HEADLESS_ALLOWED_FLAGS).flatMap(flags => [...flags]),
)

type AuthenticatedConfig = LatexyConfig & { token: string }
type TerminalJobEvent = JobCompletedEvent | JobFailedEvent | JobCancelledEvent

interface JobResultEnvelope {
  success: boolean
  job_id: string
  result?: Record<string, unknown> | null
  error?: string | null
}

export interface HeadlessArgs {
  flags: Record<string, string>
  positional: string[]
  /** Value-taking flags that were present without a usable following token. */
  missingValueFlags: string[]
  /** Flags that are not part of the headless CLI contract at all. */
  unknownFlags: string[]
  /** Known headless flags that do not apply to the selected command. */
  irrelevantFlags: string[]
  /** Boolean switches incorrectly supplied with an attached value. */
  invalidBooleanFlags: string[]
}

/**
 * Split argv into flags and true positionals.
 *
 * Everything used to be scanned with `args.find(a => !a.startsWith('-'))` to
 * locate the .tex path, which cannot tell a positional from a flag's VALUE. So
 * `latexy compile --compiler xelatex cv.tex` — the documented invocation — tried
 * to compile a file called "xelatex", and `--output out.pdf cv.tex` read out.pdf
 * as the LaTeX source, submitting a binary PDF as a job.
 */
export function parseHeadlessArgs(argv: string[], command?: string): HeadlessArgs {
  const flags: Record<string, string> = {}
  const positional: string[] = []
  const missingValueFlags: string[] = []
  const unknownFlags: string[] = []
  const irrelevantFlags: string[] = []
  const invalidBooleanFlags: string[] = []
  const allowed = command == null ? null : HEADLESS_ALLOWED_FLAGS[command]

  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i]!
    if (tok.startsWith('-')) {
      const eq = tok.indexOf('=')
      if (eq !== -1) {
        const key = tok.slice(0, eq)
        const value = tok.slice(eq + 1)
        if (!KNOWN_HEADLESS_FLAGS.has(key)) unknownFlags.push(key)
        else if (allowed != null && !allowed.has(key)) irrelevantFlags.push(key)
        if (BOOLEAN_FLAGS.has(key)) invalidBooleanFlags.push(key)
        else if (VALUE_FLAGS.has(key) && value === '') missingValueFlags.push(key)
        else flags[key] = value
        continue
      }
      if (!KNOWN_HEADLESS_FLAGS.has(tok)) unknownFlags.push(tok)
      else if (allowed != null && !allowed.has(tok)) irrelevantFlags.push(tok)
      if (VALUE_FLAGS.has(tok)) {
        const next = argv[i + 1]
        // A value-flag with a missing value must not silently swallow the path.
        if (next !== undefined && !next.startsWith('-')) {
          flags[tok] = next
          i++
        } else missingValueFlags.push(tok)
        continue
      }
      if (BOOLEAN_FLAGS.has(tok)) flags[tok] = 'true'
      continue // bare flag such as --json
    }
    positional.push(tok)
  }
  return { flags, positional, missingValueFlags, unknownFlags, irrelevantFlags, invalidBooleanFlags }
}

function headlessArgumentError(parsed: HeadlessArgs): string | null {
  if (parsed.missingValueFlags.length > 0) {
    return `Missing value for ${parsed.missingValueFlags[0]}`
  }
  if (parsed.unknownFlags.length > 0) {
    return `Unknown option: ${parsed.unknownFlags[0]}`
  }
  if (parsed.irrelevantFlags.length > 0) {
    return `Option ${parsed.irrelevantFlags[0]} is not valid for this command`
  }
  if (parsed.invalidBooleanFlags.length > 0) {
    return `Option ${parsed.invalidBooleanFlags[0]} does not accept a value`
  }
  return null
}

function out(obj: unknown): void {
  if (useJson) process.stdout.write(JSON.stringify(obj) + '\n')
  else process.stdout.write(JSON.stringify(obj, null, 2) + '\n')
}

function log(msg: string): void {
  process.stderr.write(msg + '\n')
}

async function waitForJob(jobId: string, token: string, wsUrl: string): Promise<TerminalJobEvent> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      wsClient.destroy()
      reject(new Error('Job timed out after 5 minutes'))
    }, 300_000)

    let rateLimitRetries = 0
    let connected = false
    const retryTimers: NodeJS.Timeout[] = []
    const cleanup = (): void => {
      clearTimeout(timeout)
      for (const t of retryTimers) clearTimeout(t)
      wsClient.off('server_error', onServerError)
      wsClient.off('socket_error', onSocketError)
      wsClient.off('connected', onConnected)
      wsClient.off('event', onEvent)
    }

    const onConnected = (): void => {
      connected = true
    }

    const onSocketError = (err: WSSocketError): void => {
      // A failure before the first connection can never deliver this job's
      // terminal event. Abort promptly so headless CI reports a useful exit
      // code instead of waiting five minutes while reconnect timers run. Once
      // connected, tolerate socket errors so the WS client's replay/reconnect
      // behavior can recover from a transient drop.
      if (connected) return
      cleanup()
      wsClient.destroy()
      if (err.status === 401 || err.status === 403) {
        const authError = new Error(err.message) as Error & { status: number }
        authError.status = err.status
        reject(authError)
      } else if (
        (err.code != null && UNREACHABLE_ERROR_CODES.has(err.code))
        || /fetch failed|aborted|timed out/i.test(err.message)
      ) {
        reject(new BackendUnreachableError(
          `Cannot reach the Latexy event stream at ${wsUrl}. `
          + 'Set LATEXY_API_URL or fix backendUrl in ~/.config/latexy/config.toml.'
        ))
      } else {
        reject(new Error(err.message))
      }
    }

    const onServerError = (err: WSServerError): void => {
      // Per-job rejections are tagged with job_id — ignore the ones that aren't ours
      if (err.job_id && err.job_id !== jobId) return
      if (err.code === 'rate_limited') {
        // The throttled frame was dropped server-side, so the subscribe never landed — resend it
        if (rateLimitRetries >= MAX_RATE_LIMIT_RETRIES) return
        rateLimitRetries++
        log(`Event stream throttled — retrying subscribe (${rateLimitRetries}/${MAX_RATE_LIMIT_RETRIES})`)
        retryTimers.push(setTimeout(() => wsClient.subscribe(jobId, '0'), RATE_LIMIT_RETRY_MS))
        return
      }
      if (!FATAL_WS_ERROR_CODES.has(err.code)) return
      cleanup()
      wsClient.destroy()
      reject(new Error(`Event stream rejected by server (${err.code}): ${err.message}`))
    }

    const onEvent = (ev: AnyEvent): void => {
      if (ev.job_id !== jobId) return
      if (ev.type === 'log.line') log(ev.line)
      if (ev.type === 'job.progress') log(`[${ev.percent}%] ${ev.message || ev.stage}`)
      if (ev.type === 'job.completed' || ev.type === 'job.failed' || ev.type === 'job.cancelled') {
        cleanup()
        wsClient.destroy()
        resolve(ev)
      }
    }

    wsClient.on('server_error', onServerError)
    wsClient.on('socket_error', onSocketError)
    wsClient.on('connected', onConnected)
    wsClient.on('event', onEvent)

    // Register listeners before opening the socket. `connect()` is currently
    // asynchronous, but this ordering keeps a future synchronous transport
    // implementation from racing the first error/event.
    wsClient.connect(wsUrl, token)
    wsClient.drain()
    wsClient.subscribe(jobId, '0')
  })
}

class BackendUnreachableError extends Error {}

/**
 * fetch() rejects with a bare "TypeError: fetch failed" — say which URL was unreachable.
 * Used around each network phase that can fail before a useful JSON result is
 * emitted, including a requested PDF download after a successful compile.
 */
async function withReachableBackend<T>(backendUrl: string, fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (err) {
    if (!isBackendReachabilityFailure(err)) throw err
    const code = (err as { cause?: { code?: string } }).cause?.code
    throw new BackendUnreachableError(
      `Cannot reach the Latexy backend at ${backendUrl}${code ? ` (${code})` : ''}. `
      + 'Set LATEXY_API_URL or fix backendUrl in ~/.config/latexy/config.toml.'
    )
  }
}

/**
 * Fetch uses several shapes for an AbortSignal.timeout rejection depending on
 * the Node/undici path: DOMException(TimeoutError), DOMException(AbortError),
 * or a TypeError wrapping one of those. Treat those as connectivity failures
 * for the documented exit-code contract, while leaving ordinary application
 * errors untouched.
 */
function isBackendReachabilityFailure(err: unknown): boolean {
  if (err instanceof TypeError) {
    // Undici reports network and abort failures as TypeError in some Node
    // versions. Do not classify every TypeError (for example, a programming
    // error thrown while processing a successful response) as an outage.
    if (/fetch failed|network|aborted|timed out|timeout/i.test(err.message)) return true
    const cause = (err as { cause?: unknown }).cause
    if (cause != null && typeof cause === 'object') {
      const causeName = (cause as { name?: unknown }).name
      const causeCode = (cause as { code?: unknown }).code
      if (causeName === 'TimeoutError' || causeName === 'AbortError') return true
      if (typeof causeCode === 'string' && UNREACHABLE_ERROR_CODES.has(causeCode)) return true
    }
    return false
  }
  if (err == null || typeof err !== 'object') return false

  const error = err as { name?: unknown; cause?: unknown }
  if (error.name === 'TimeoutError' || error.name === 'AbortError') return true

  const cause = error.cause
  if (cause == null || typeof cause !== 'object') return false
  const causeName = (cause as { name?: unknown }).name
  if (causeName === 'TimeoutError' || causeName === 'AbortError') return true
  const causeCode = (cause as { code?: unknown }).code
  return typeof causeCode === 'string' && UNREACHABLE_ERROR_CODES.has(causeCode)
}

async function authenticatedCommand(
  command: (cfg: AuthenticatedConfig, client: ApiClient) => Promise<number>,
): Promise<number> {
  const cfg = await readConfig()
  if (!cfg.token) {
    out({ success: false, error: 'Not authenticated. Set LATEXY_SESSION_TOKEN env var.' })
    return 2
  }

  const authenticated = { ...cfg, token: cfg.token }
  const client = initApiClient(cfg.backendUrl, cfg.token)
  try {
    return await command(authenticated, client)
  } catch (err) {
    if (!(err instanceof BackendUnreachableError)) throw err
    out({ success: false, error: err.message })
    return 4
  }
}

async function resolveHeadlessJobDescription(client: ApiClient, value: string): Promise<string> {
  if (/^https?:\/\//i.test(value)) {
    const scraped = await client.post<{ description?: string | null; error?: string | null }>(
      '/scrape-job-description',
      { url: value },
    )
    if (scraped.description) return scraped.description
    throw new Error(`Could not read job posting: ${scraped.error ?? 'no description found'}`)
  }

  try {
    return await readFile(value, 'utf-8')
  } catch {
    // A non-path value is accepted as literal JD text, matching interactive mode.
    return value
  }
}

async function waitForResult(
  cfg: AuthenticatedConfig,
  client: ApiClient,
  jobId: string,
): Promise<number> {
  const ev = await waitForJob(jobId, cfg.token, client.getWsUrl())
  if (ev.type === 'job.failed') {
    out({
      success: false,
      job_id: jobId,
      error: ev.error_message,
      error_code: ev.error_code,
      retryable: ev.retryable,
    })
    return 1
  }
  if (ev.type === 'job.cancelled') {
    out({ success: false, job_id: jobId, error: 'Job was cancelled', error_code: 'cancelled', retryable: false })
    return 1
  }

  const envelope = await withReachableBackend(cfg.backendUrl, () =>
    client.get<JobResultEnvelope>(`/jobs/${jobId}/result`)
  )
  if (!envelope.success) {
    out({ success: false, job_id: jobId, error: envelope.error ?? 'Job failed' })
    return 1
  }

  out({ ...(envelope.result ?? {}), success: true, job_id: jobId })
  return 0
}

async function headlessCompile(args: string[]): Promise<number> {
  const cfg = await readConfig()
  if (!cfg.token) {
    out({ success: false, error: 'Not authenticated. Set LATEXY_SESSION_TOKEN env var.' })
    return 2
  }
  try {
    return await compileJob({ ...cfg, token: cfg.token }, args)
  } catch (err) {
    if (!(err instanceof BackendUnreachableError)) throw err
    out({ success: false, error: err.message })
    return 4
  }
}

async function compileJob(cfg: LatexyConfig & { token: string }, args: string[]): Promise<number> {
  const client = initApiClient(cfg.backendUrl, cfg.token)
  const wsUrl = cfg.backendUrl.replace(/^http/, 'ws') + '/ws/jobs'

  const parsed = parseHeadlessArgs(args, 'compile')
  const argumentError = headlessArgumentError(parsed)
  if (argumentError != null) {
    out({ success: false, error: argumentError })
    return 3
  }
  const { flags, positional } = parsed
  const explicitResumeId = flags['--resume-id'] ?? null
  const requestedCompiler = flags['--compiler']
  const outputPath = flags['--output'] ?? null

  // A local path is an explicit input and takes precedence over the persisted
  // default. When no path or --resume-id is supplied, use the same saved
  // default that interactive commands resolve through /list.
  const filePath = positional.find(a => a !== 'compile')
  const resumeId = explicitResumeId ?? (!filePath ? cfg.defaultResumeId : null)

  let jobId: string

  if (resumeId) {
    log(`Compiling resume ${resumeId}…`)
    const res = await withReachableBackend(cfg.backendUrl, async () => {
      const resume = await client.get<{
        latex_content: string
        metadata?: { compiler?: string } | null
      }>(`/resumes/${resumeId}`)
      const compiler = requestedCompiler ?? resume.metadata?.compiler
      return client.post<{ job_id: string }>('/jobs/submit', {
        job_type: 'latex_compilation',
        latex_content: resume.latex_content,
        ...(compiler ? { compiler } : {}),
      })
    })
    jobId = res.job_id
  } else {
    // Local file path: read content and submit via the job queue (same as --resume-id)
    if (!filePath) {
      out({ success: false, error: 'Provide a .tex file path, --resume-id <uuid>, or configure defaultResumeId' })
      return 3
    }
    log(`Compiling ${basename(filePath)}…`)
    const latex_content = await readFile(filePath, 'utf-8')
    const compiler = requestedCompiler ?? 'pdflatex'
    const res = await withReachableBackend(cfg.backendUrl, () =>
      client.post<{ job_id: string }>('/jobs/submit', {
        job_type: 'latex_compilation',
        latex_content,
        compiler,
      })
    )
    jobId = res.job_id
  }

  log(`Job submitted: ${jobId}`)
  const ev = await waitForJob(jobId, cfg.token, wsUrl)

  if (ev.type === 'job.completed') {
    if (outputPath) {
      const pdfRes = await withReachableBackend(cfg.backendUrl, () => fetch(`${cfg.backendUrl}/download/${jobId}`, {
        headers: { Authorization: `Bearer ${cfg.token}` },
        signal: AbortSignal.timeout(60_000),
      }))
      if (!pdfRes.ok) {
        const detail = (await pdfRes.text().catch(() => '')).slice(0, 200)
        out({
          success: false,
          job_id: jobId,
          error: `PDF download failed: HTTP ${pdfRes.status} ${pdfRes.statusText}${detail ? ` — ${detail}` : ''}`,
        })
        return 1
      }
      const buf = Buffer.from(await pdfRes.arrayBuffer())
      // Never write a non-PDF body to a .pdf path — a stray error envelope would look like success
      if (!buf.subarray(0, 5).equals(Buffer.from('%PDF-'))) {
        out({
          success: false,
          job_id: jobId,
          error: `PDF download returned ${buf.length} bytes that are not a PDF (${pdfRes.headers.get('Content-Type') ?? 'unknown content type'})`,
        })
        return 1
      }
      await writeFile(outputPath, buf)
      log(`PDF saved: ${outputPath}`)
    }
    out({
      success: true,
      job_id: jobId,
      pages: ev.page_count ?? null,
      // null (not the worker's hardcoded 0.0) when no ATS stage ran
      ats_score: resolveAtsScore(ev),
      compilation_time_ms: ev.compilation_time != null
        ? Math.round(ev.compilation_time * 1000)
        : null,
      compiler: ev.compiler ?? null,
    })
    return 0
  } else {
    const failed = ev as JobFailedEvent
    out({ success: false, error: failed.error_message, error_code: failed.error_code, retryable: failed.retryable })
    return 1
  }
}

async function headlessOptimize(args: string[]): Promise<number> {
  return authenticatedCommand(async (cfg, client) => {
    const parsed = parseHeadlessArgs(args, 'optimize')
    const argumentError = headlessArgumentError(parsed)
    if (argumentError != null) {
      out({ success: false, error: argumentError })
      return 3
    }
    const { flags, positional } = parsed
    const resumeId = positional[0] ?? cfg.defaultResumeId
    const jdInput = flags['--jd']
    const level = flags['--level'] ?? 'balanced'

    if (!resumeId || !jdInput) {
      out({ success: false, error: 'Usage: latexy optimize <resume-id> --jd <file|url|text> [--level <level>] [--model <model>]' })
      return 3
    }
    if (!['conservative', 'balanced', 'aggressive'].includes(level)) {
      out({ success: false, error: `Invalid optimization level: ${level}` })
      return 3
    }

    log(`Optimizing resume ${resumeId}…`)
    const submitted = await withReachableBackend(cfg.backendUrl, async () => {
      const resume = await client.get<{ latex_content: string }>(`/resumes/${resumeId}`)
      const jobDescription = await resolveHeadlessJobDescription(client, jdInput)
      return client.post<{ job_id: string }>('/jobs/submit', {
        job_type: 'llm_optimization',
        latex_content: resume.latex_content,
        job_description: jobDescription,
        optimization_level: level,
        model: flags['--model'],
        metadata: { resume_id: resumeId },
      })
    })

    log(`Job submitted: ${submitted.job_id}`)
    return waitForResult(cfg, client, submitted.job_id)
  })
}

async function headlessAts(args: string[]): Promise<number> {
  return authenticatedCommand(async (cfg, client) => {
    const parsed = parseHeadlessArgs(args, 'ats')
    const argumentError = headlessArgumentError(parsed)
    if (argumentError != null) {
      out({ success: false, error: argumentError })
      return 3
    }
    const { flags, positional } = parsed
    const action = positional[0]
    const resumeId = positional[1] ?? cfg.defaultResumeId
    if (action !== 'score' || !resumeId) {
      out({ success: false, error: 'Usage: latexy ats score <resume-id> [--jd <file|url|text>] [--industry <name>]' })
      return 3
    }

    log(`Scoring resume ${resumeId}…`)
    const submitted = await withReachableBackend(cfg.backendUrl, async () => {
      const resume = await client.get<{ latex_content: string }>(`/resumes/${resumeId}`)
      const jdInput = flags['--jd']
      const jobDescription = jdInput
        ? await resolveHeadlessJobDescription(client, jdInput)
        : undefined
      return client.post<{ job_id: string }>('/jobs/submit', {
        job_type: 'ats_scoring',
        latex_content: resume.latex_content,
        job_description: jobDescription,
        industry: flags['--industry'],
        metadata: { resume_id: resumeId },
      })
    })

    log(`Job submitted: ${submitted.job_id}`)
    return waitForResult(cfg, client, submitted.job_id)
  })
}

async function headlessStatus(args: string[]): Promise<number> {
  return authenticatedCommand(async (cfg, client) => {
    const parsed = parseHeadlessArgs(args, 'status')
    const argumentError = headlessArgumentError(parsed)
    if (argumentError != null) {
      out({ success: false, error: argumentError })
      return 3
    }
    const { flags, positional } = parsed
    const jobId = positional[0]
    if (!jobId) {
      out({ success: false, error: 'Usage: latexy status <job-id> [--wait]' })
      return 3
    }

    if (flags['--wait'] === 'true') return waitForResult(cfg, client, jobId)

    const state = await withReachableBackend(cfg.backendUrl, () =>
      client.get<Record<string, unknown>>(`/jobs/${jobId}/state`)
    )
    out({ ...state, success: true, job_id: jobId })
    return 0
  })
}

async function headlessList(args: string[]): Promise<number> {
  return authenticatedCommand(async (cfg, client) => {
    const parsed = parseHeadlessArgs(args, 'list')
    const argumentError = headlessArgumentError(parsed)
    if (argumentError != null) {
      out({ success: false, error: argumentError })
      return 3
    }
    const { flags } = parsed
    const page = Number(flags['--page'] ?? '1')
    const limit = Number(flags['--limit'] ?? '100')
    if (!Number.isInteger(page) || page < 1 || !Number.isInteger(limit) || limit < 1 || limit > 100) {
      out({ success: false, error: '--page must be >= 1 and --limit must be between 1 and 100' })
      return 3
    }

    const response = await withReachableBackend(cfg.backendUrl, () =>
      client.get<Record<string, unknown>>(`/resumes/?page=${page}&limit=${limit}`)
    )
    out({ ...response, success: true })
    return 0
  })
}

export async function runHeadless(subcommand: string | undefined, args: string[]): Promise<number> {
  try {
    switch (subcommand) {
      case 'compile': return await headlessCompile(args.slice(1))
      case 'optimize': return await headlessOptimize(args.slice(1))
      case 'ats': return await headlessAts(args.slice(1))
      case 'status': return await headlessStatus(args.slice(1))
      case 'list': return await headlessList(args.slice(1))
      default:
        out({
          success: false,
          // String(undefined) printed the literal text "undefined" at the user.
          error: subcommand === undefined
            ? 'No subcommand given. Available: compile, optimize, ats, status, list'
            : `Unknown subcommand: ${subcommand}. Available: compile, optimize, ats, status, list`,
        })
        return 3
    }
  } catch (err) {
    out({ success: false, error: String(err) })
    if (err != null && typeof err === 'object' && (err as { status?: unknown }).status === 401) return 2
    if (err instanceof BackendUnreachableError) return 4
    return 1
  }
}
