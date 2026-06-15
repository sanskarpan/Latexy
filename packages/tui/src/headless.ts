import { readConfig } from './lib/config.js'
import { initApiClient } from './lib/api-client.js'
import { wsClient } from './lib/ws-client.js'
import type { AnyEvent, JobCompletedEvent, JobFailedEvent } from './lib/event-types.js'
import { readFile, writeFile } from 'node:fs/promises'
import { basename } from 'node:path'

const useJson = process.argv.includes('--json')

function out(obj: unknown): void {
  if (useJson) process.stdout.write(JSON.stringify(obj) + '\n')
  else process.stderr.write(JSON.stringify(obj, null, 2) + '\n')
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

    wsClient.on('event', (ev: AnyEvent) => {
      if (ev.job_id !== jobId) return
      if (ev.type === 'log.line') log(ev.line)
      if (ev.type === 'job.progress') log(`[${ev.percent}%] ${ev.stage}`)
      if (ev.type === 'job.completed' || ev.type === 'job.failed') {
        clearTimeout(timeout)
        wsClient.destroy()
        resolve(ev)
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

  const resumeIdIdx = args.indexOf('--resume-id')
  const resumeId = resumeIdIdx !== -1 ? args[resumeIdIdx + 1] : null
  const compilerIdx = args.indexOf('--compiler')
  const compiler = compilerIdx !== -1 ? args[compilerIdx + 1] ?? 'pdflatex' : 'pdflatex'
  const outputIdx = args.indexOf('--output')
  const outputPath = outputIdx !== -1 ? args[outputIdx + 1] ?? null : null

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
    form.append('file', new Blob([bytes], { type: 'application/octet-stream' }), basename(filePath))
    form.append('compiler', compiler)
    const res = await client.postForm<{ job_id: string }>('/api/compile', form)
    jobId = res.job_id
  }

  log(`Job submitted: ${jobId}`)
  const ev = await waitForJob(jobId, cfg.token, wsUrl)

  if (ev.type === 'job.completed') {
    const result = ev.result as Record<string, unknown>
    if (outputPath && result['pdf_url']) {
      const pdfRes = await fetch(cfg.backendUrl + (result['pdf_url'] as string), {
        headers: { Authorization: `Bearer ${cfg.token}` },
      })
      const buf = await pdfRes.arrayBuffer()
      await writeFile(outputPath, Buffer.from(buf))
      log(`PDF saved: ${outputPath}`)
    }
    out({
      success: true,
      job_id: jobId,
      pages: result['pages'] ?? null,
      size_bytes: result['size_bytes'] ?? null,
      ats_score: result['ats_score'] ?? null,
      pdf_url: result['pdf_url'] ?? null,
      compilation_time_ms: result['compilation_time_ms'] ?? null,
    })
    return 0
  } else {
    const failed = ev as JobFailedEvent
    out({ success: false, error: failed.error, error_code: failed.error_code, retryable: failed.retryable })
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
