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

/**
 * Set when resolveJobDescription has already explained its own failure, so the
 * caller does not follow it with "a job description is required" — which told
 * the user to supply the flag they had just supplied.
 */
let jdFailureReported = false

export function jdFailureAlreadyReported(): boolean {
  const was = jdFailureReported
  jdFailureReported = false
  return was
}

/** Read a job description from --jd (a URL, a file path, or literal text). */
export async function resolveJobDescription(parsed: ParsedCommand): Promise<string | null> {
  jdFailureReported = false
  const jd = parsed.args['jd']
  if (typeof jd !== 'string' || !jd) return null

  if (/^https?:\/\//i.test(jd)) {
    try {
      // The backend already knows how to turn a posting URL into structured text
      // (native ATS APIs, then JSON-LD, then HTML), so don't re-implement it here.
      // The scraper answers 200 with description:null and an `error` string when
      // it cannot read a posting, so the catch below never fires. Returning null
      // made the caller report "a job description is required", hiding the real
      // reason (blocked page, 404, login wall).
      const scraped = await getApiClient().post<{
        description?: string | null
        error?: string | null
      }>('/scrape-job-description', { url: jd })

      if (scraped.description != null && scraped.description !== '') return scraped.description
      jdFailureReported = true
      addMessage({
        role: 'error',
        content: `Could not read that job posting: ${scraped.error ?? 'no description found'}. ` +
          'Paste the text or pass a file path instead.',
      })
      return null
    } catch (err) {
      // Set the flag here too, or a genuine exception (5xx, network, timeout)
      // still draws the follow-up "a job description is required".
      jdFailureReported = true
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
    jobSlotClaimed = false          // $activeJobId is now the authority
    $activeJobId.set(jobId)
    const ctrl = createJobController(jobId)
    ctrl.setToolMsgId(toolMsgId)
    wsClient.subscribe(jobId, '0')
    return jobId
  } catch (err) {
    // Submission failed, so nothing is running — hand the slot back or the user
    // is locked out of starting anything until they restart.
    jobSlotClaimed = false
    updateMessage(toolMsgId, {
      toolState: 'error',
      toolResult: { error: describeError(err) },
      durationMs: 0,
    })
    return null
  }
}

/**
 * Claim the single-job slot, or report that it is taken.
 *
 * This used to only *read* $activeJobId, which submitJob sets after its POST
 * resolves — a check-then-act window wide enough that /optimize, /combined and
 * /ats dispatched together all passed the guard and all three were queued and
 * charged. Only one could be tracked, so the other two cards could never be
 * cancelled. The slot is claimed synchronously now, before any await.
 */
let jobSlotClaimed = false

export function claimJobSlot(): boolean {
  if (jobSlotClaimed || $activeJobId.get() != null) {
    addMessage({ role: 'error', content: 'A job is already running — /cancel it first.' })
    return false
  }
  jobSlotClaimed = true
  return true
}

/** Release the slot when submission failed, so the user is not locked out. */
export function releaseJobSlot(): void {
  jobSlotClaimed = false
}

/**
 * Run a job-starting command while holding the single-job slot.
 *
 * Releasing per-branch is fragile: every early return, every throw, and every
 * cancelled picker has to remember, and one that forgets locks the user out of
 * starting any job until they restart. This releases in a finally unless the
 * body actually submitted (submitJob hands ownership to $activeJobId), so a
 * missed branch cannot wedge the slot.
 */
export async function withJobSlot(body: () => Promise<void>): Promise<void> {
  if (!claimJobSlot()) return
  try {
    await body()
  } finally {
    // submitJob clears the flag once $activeJobId owns the job; if it is still
    // set here, nothing was submitted and the slot is ours to give back.
    if (jobSlotClaimed) jobSlotClaimed = false
  }
}

/** Kept for callers that only need to ask, without claiming. */
export function busyWithAnotherJob(): boolean {
  return jobSlotClaimed || $activeJobId.get() != null
}

/** ApiError carries a useful message; anything else stringifies poorly. */
export function describeError(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

/**
 * Ages a timestamp that may be an ISO string OR a Unix epoch.
 *
 * /jobs returns `created_at` as a float epoch while /resumes and /checkpoints
 * return ISO strings. Feeding the epoch to `new Date(string)` yields Invalid
 * Date, which printed "NaNd ago" in the job list.
 */
export function formatAge(value: string | number): string {
  const ms = typeof value === 'number' || /^\d+(\.\d+)?$/.test(String(value))
    ? Number(value) * (Number(value) < 1e11 ? 1000 : 1)   // seconds vs milliseconds
    : new Date(value).getTime()
  const days = Math.floor((Date.now() - ms) / 86_400_000)
  if (!Number.isFinite(days)) return ''
  if (days <= 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  return `${Math.floor(days / 30)}mo ago`
}

/** Render a plain key/value block as a system message. */
export function report(title: string, rows: Array<[string, unknown]>): void {
  if (rows.length === 0) {
    addMessage({ role: 'system', content: `${title}\n  (nothing to show)` })
    return
  }
  const width = Math.max(...rows.map(([k]) => k.length))
  const body = rows
    // `false` and `0` are real values worth printing — dropping them made the
    // notification settings render as an empty block.
    .filter(([, v]) => v !== undefined && v !== null && v !== '')
    .map(([k, v]) => `  ${k.padEnd(width)}  ${String(v)}`)
    .join('\n')
  addMessage({ role: 'system', content: `${title}\n${body}` })
}
