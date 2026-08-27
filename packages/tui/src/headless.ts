import { readConfig } from './lib/config.js'
import type { LatexyConfig } from './lib/config.js'
import { initApiClient } from './lib/api-client.js'
import type { ApiClient } from './lib/api-client.js'
import { wsClient } from './lib/ws-client.js'
import type { WSServerError } from './lib/ws-client.js'
import { resolveAtsScore } from './lib/event-types.js'
import type { AnyEvent, JobCancelledEvent, JobCompletedEvent, JobFailedEvent } from './lib/event-types.js'
import { readFile, writeFile } from 'node:fs/promises'
import { basename } from 'node:path'

const useJson = process.argv.includes('--json')

// Server-side rejections that will never resolve on their own — abort instead of waiting out the
// timeout. `rate_limited` is deliberately absent: ws_routes' limiter is a soft per-connection
// throttle that drops the one frame and keeps going, so we retry the subscribe instead of aborting.
const FATAL_WS_ERROR_CODES = new Set(['forbidden', 'invalid_request'])
const RATE_LIMIT_RETRY_MS = 1_000
const MAX_RATE_LIMIT_RETRIES = 5

/** Headless flags that consume the following token as their value. */
const VALUE_FLAGS = new Set([
  '--resume-id', '--compiler', '--output', '--jd', '--level', '--model',
  '--industry', '--page', '--limit',
])

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
export function parseHeadlessArgs(argv: string[]): HeadlessArgs {
  const flags: Record<string, string> = {}
  const positional: string[] = []

  for (let i = 0; i < argv.length; i++) {
    const tok = argv[i]!
    if (tok.startsWith('-')) {
      const eq = tok.indexOf('=')
      if (eq !== -1) {
        flags[tok.slice(0, eq)] = tok.slice(eq + 1)
        continue
      }
      if (VALUE_FLAGS.has(tok)) {
        const next = argv[i + 1]
        // A value-flag with a missing value must not silently swallow the path.
        if (next !== undefined && !next.startsWith('-')) {
          flags[tok] = next
          i++
        }
        continue
      }
      continue // bare flag such as --json
    }
    positional.push(tok)
  }
  return { flags, positional }
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
    wsClient.connect(wsUrl, token)
    wsClient.drain()
    wsClient.subscribe(jobId, '0')

    const timeout = setTimeout(() => {
      wsClient.destroy()
      reject(new Error('Job timed out after 5 minutes'))
    }, 300_000)

    let rateLimitRetries = 0
    const retryTimers: NodeJS.Timeout[] = []
    const cleanup = (): void => {
      clearTimeout(timeout)
      for (const t of retryTimers) clearTimeout(t)
      wsClient.off('server_error', onServerError)
      wsClient.off('event', onEvent)
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
    wsClient.on('event', onEvent)
  })
}

class BackendUnreachableError extends Error {}

/**
 * fetch() rejects with a bare "TypeError: fetch failed" — say which URL was unreachable.
 * Scoped to the initial submit calls only: a later /download failure must not claim the whole
 * backend is down when the compile already succeeded.
 */
async function withReachableBackend<T>(backendUrl: string, fn: () => Promise<T>): Promise<T> {
  try {
    return await fn()
  } catch (err) {
    if (!(err instanceof TypeError)) throw err
    const code = (err as { cause?: { code?: string } }).cause?.code
    throw new BackendUnreachableError(
      `Cannot reach the Latexy backend at ${backendUrl}${code ? ` (${code})` : ''}. `
      + 'Set LATEXY_API_URL or fix backendUrl in ~/.config/latexy/config.toml.'
    )
  }
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

  const { flags, positional } = parseHeadlessArgs(args)
  const resumeId = flags['--resume-id'] ?? null
  const compiler = flags['--compiler'] ?? 'pdflatex'
  const outputPath = flags['--output'] ?? null

  let jobId: string

  if (resumeId) {
    log(`Compiling resume ${resumeId}…`)
    const res = await withReachableBackend(cfg.backendUrl, async () => {
      const resume = await client.get<{ latex_content: string }>(`/resumes/${resumeId}`)
      return client.post<{ job_id: string }>('/jobs/submit', {
        job_type: 'latex_compilation',
        latex_content: resume.latex_content,
        compiler,
      })
    })
    jobId = res.job_id
  } else {
    // Local file path: read content and submit via the job queue (same as --resume-id)
    const filePath = positional.find(a => a !== 'compile')
    if (!filePath) {
      out({ success: false, error: 'Provide a .tex file path or --resume-id <uuid>' })
      return 3
    }
    log(`Compiling ${basename(filePath)}…`)
    const latex_content = await readFile(filePath, 'utf-8')
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
      const pdfRes = await fetch(`${cfg.backendUrl}/download/${jobId}`, {
        headers: { Authorization: `Bearer ${cfg.token}` },
      })
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
    const { flags, positional } = parseHeadlessArgs(args)
    const resumeId = positional[0]
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
    const { flags, positional } = parseHeadlessArgs(args)
    const action = positional[0]
    const resumeId = positional[1]
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
    const { positional } = parseHeadlessArgs(args)
    const jobId = positional[0]
    if (!jobId) {
      out({ success: false, error: 'Usage: latexy status <job-id> [--wait]' })
      return 3
    }

    if (args.includes('--wait')) return waitForResult(cfg, client, jobId)

    const state = await withReachableBackend(cfg.backendUrl, () =>
      client.get<Record<string, unknown>>(`/jobs/${jobId}/state`)
    )
    out({ ...state, success: true, job_id: jobId })
    return 0
  })
}

async function headlessList(args: string[]): Promise<number> {
  return authenticatedCommand(async (cfg, client) => {
    const { flags } = parseHeadlessArgs(args)
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
