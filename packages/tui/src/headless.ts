import { readConfig } from './lib/config.js'
import type { LatexyConfig } from './lib/config.js'
import { initApiClient } from './lib/api-client.js'
import { wsClient } from './lib/ws-client.js'
import type { WSServerError } from './lib/ws-client.js'
import { resolveAtsScore } from './lib/event-types.js'
import type { AnyEvent, JobCompletedEvent, JobFailedEvent } from './lib/event-types.js'
import { readFile, writeFile } from 'node:fs/promises'
import { basename } from 'node:path'

const useJson = process.argv.includes('--json')

// Server-side rejections that will never resolve on their own — abort instead of waiting out the
// timeout. `rate_limited` is deliberately absent: ws_routes' limiter is a soft per-connection
// throttle that drops the one frame and keeps going, so we retry the subscribe instead of aborting.
const FATAL_WS_ERROR_CODES = new Set(['forbidden', 'invalid_request'])
const RATE_LIMIT_RETRY_MS = 1_000
const MAX_RATE_LIMIT_RETRIES = 5

function out(obj: unknown): void {
  if (useJson) process.stdout.write(JSON.stringify(obj) + '\n')
  else process.stdout.write(JSON.stringify(obj, null, 2) + '\n')
}

function log(msg: string): void {
  process.stderr.write(msg + '\n')
}

async function waitForJob(jobId: string, token: string, wsUrl: string): Promise<JobCompletedEvent | JobFailedEvent> {
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
    }

    wsClient.on('server_error', (err: WSServerError) => {
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
    })

    wsClient.on('event', (ev: AnyEvent) => {
      if (ev.job_id !== jobId) return
      if (ev.type === 'log.line') log(ev.line)
      if (ev.type === 'job.progress') log(`[${ev.percent}%] ${ev.stage}`)
      if (ev.type === 'job.completed' || ev.type === 'job.failed') {
        cleanup()
        wsClient.destroy()
        resolve(ev)
      }
    })
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

  const resumeIdIdx = args.indexOf('--resume-id')
  const resumeId = resumeIdIdx !== -1 ? args[resumeIdIdx + 1] : null
  const compilerIdx = args.indexOf('--compiler')
  const compiler = compilerIdx !== -1 ? args[compilerIdx + 1] ?? 'pdflatex' : 'pdflatex'
  const outputIdx = args.indexOf('--output')
  const outputPath = outputIdx !== -1 ? args[outputIdx + 1] ?? null : null

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
    const filePath = args.find(a => !a.startsWith('-') && a !== 'compile')
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

export async function runHeadless(subcommand: string | undefined, args: string[]): Promise<number> {
  try {
    switch (subcommand) {
      case 'compile': return await headlessCompile(args.slice(1))
      default:
        out({ success: false, error: `Unknown subcommand: ${String(subcommand)}. Available: compile` })
        return 3
    }
  } catch (err) {
    out({ success: false, error: String(err) })
    return 1
  }
}
