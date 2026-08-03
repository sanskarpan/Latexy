/**
 * Shared machinery for slash commands.
 *
 * Every command needs the same few things — a session, a resume to act on, a job
 * submitted and wired to a tool card, or a job description read from a flag.
 * compile.ts grew its own copy of each; factoring them here keeps the ~25
 * commands built on top from repeating it, and means a fix lands once.
 */
import { readFile } from 'node:fs/promises'

import { getApiClient } from '../lib/api-client.js'
import { beginPick } from '../lib/pick.js'
import { wsClient } from '../lib/ws-client.js'
import { createJobController } from '../hooks/useJobStream.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import { openOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'
import type { ParsedCommand } from '../commands/parser.js'

export interface JobSubmitResponse { job_id: string }

export interface Resume {
  id: string
  title: string
  updated_at: string
  type?: string
  is_pinned?: boolean
}

/** Guard used by every authenticated command. Reports plainly and returns false. */
export function requireAuth(): boolean {
  if ($session.get().isAuthenticated) return true
  // The old message pointed at /login, which has never been a registered
  // command — a dead end for anyone who followed it.
  addMessage({
    role: 'error',
    content: 'Not signed in. Restart the TUI to sign in, or set LATEXY_SESSION_TOKEN.',
  })
  return false
}

/**
 * Resolve which resume a command should act on.
 *
 * Order: an explicit id argument, then the saved default, then an interactive
 * picker. Returns null when the user cancels, in which case the caller should
 * quietly stop rather than reporting an error.
 */
export async function resolveResumeId(parsed: ParsedCommand): Promise<string | null> {
  const explicit =
    (parsed.args['resume'] as string | undefined) ??
    parsed.positional.find(p => /^[0-9a-f-]{36}$/i.test(p))
  if (explicit) return explicit

  const client = getApiClient()
  let resumes: Resume[] = []
  try {
    const res = await client.get<{ resumes: Resume[] }>('/resumes/?limit=50')
    resumes = res.resumes ?? []
  } catch (err) {
    addMessage({ role: 'error', content: `Could not list resumes: ${describeError(err)}` })
    return null
  }

  if (resumes.length === 0) {
    addMessage({ role: 'error', content: 'No resumes yet — create one with /new.' })
    return null
  }
  if (resumes.length === 1) return resumes[0]!.id

  const { SelectOverlay } = await import('../components/overlays/SelectOverlay.js')
  const React = await import('react')
  return new Promise<string | null>(resolve => {
    beginPick(resolve)
    openOverlay(
      React.createElement(SelectOverlay, {
        title: `Select a resume for /${parsed.name}`,
        load: async () =>
          resumes.map(r => ({ id: r.id, label: r.title, detail: formatAge(r.updated_at) })),
      }),
    )
  })
}

/** Read a job description from --jd (a URL, a file path, or literal text). */
export async function resolveJobDescription(parsed: ParsedCommand): Promise<string | null> {
  const jd = parsed.args['jd']
  if (typeof jd !== 'string' || !jd) return null

  if (/^https?:\/\//i.test(jd)) {
    try {
      // The backend already knows how to turn a posting URL into structured text
      // (native ATS APIs, then JSON-LD, then HTML), so don't re-implement it here.
      const scraped = await getApiClient().post<{ description?: string; raw_text?: string }>(
        '/scrape-job-description',
        { url: jd },
      )
      return scraped.description ?? scraped.raw_text ?? null
    } catch (err) {
      addMessage({ role: 'error', content: `Could not read the job posting: ${describeError(err)}` })
      return null
    }
  }

  try {
    return await readFile(jd, 'utf-8')
  } catch {
    // Not a readable path — treat it as the description itself.
    return jd
  }
}

/**
 * Submit a job and wire it to a tool card so progress, logs and completion all
 * render. This is the sequence every job-backed command needs.
 */
export async function submitJob(opts: {
  toolName: string
  toolArgs: Record<string, unknown>
  body: Record<string, unknown>
  path?: string
}): Promise<string | null> {
  const toolMsgId = addMessage({
    role: 'tool_use',
    content: '',
    toolName: opts.toolName,
    toolState: 'running',
    toolArgs: opts.toolArgs,
  })

  try {
    const res = await getApiClient().post<JobSubmitResponse>(opts.path ?? '/jobs/submit', opts.body)
    const jobId = res.job_id
    $activeJobId.set(jobId)
    const ctrl = createJobController(jobId)
    ctrl.setToolMsgId(toolMsgId)
    wsClient.subscribe(jobId, '0')
    return jobId
  } catch (err) {
    updateMessage(toolMsgId, {
      toolState: 'error',
      toolResult: { error: describeError(err) },
      durationMs: 0,
    })
    return null
  }
}

/** Refuse to start a second job while one is already streaming. */
export function busyWithAnotherJob(): boolean {
  if ($activeJobId.get() == null) return false
  addMessage({ role: 'error', content: 'A job is already running — /cancel it first.' })
  return true
}

/** ApiError carries a useful message; anything else stringifies poorly. */
export function describeError(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

export function formatAge(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
  if (!Number.isFinite(days)) return ''
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  return `${Math.floor(days / 30)}mo ago`
}

/** Render a plain key/value block as a system message. */
export function report(title: string, rows: Array<[string, unknown]>): void {
  const width = Math.max(...rows.map(([k]) => k.length))
  const body = rows
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `  ${k.padEnd(width)}  ${String(v)}`)
    .join('\n')
  addMessage({ role: 'system', content: `${title}\n${body}` })
}
