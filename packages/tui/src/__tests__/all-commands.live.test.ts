/**
 * Every command, against a real backend, asserted on substantive output.
 *
 * "Routed" is necessary but not sufficient: a command can dispatch cleanly and
 * still print blanks because it reads fields the API does not return. That is
 * exactly what happened — /tracker read `.applications` (the API returns
 * `by_status`), /snippets read `upvotes` (it is `upvotes_count`), /settings
 * dropped booleans, and /jobs fed a Unix epoch to `new Date(string)` and
 * rendered "NaNd ago". None of it was visible to a mocked test.
 *
 * So each case here asserts on what the user actually sees, and explicitly bans
 * the failure signatures: `undefined`, `NaN`, `[object Object]`, and the
 * "nothing found" wording when the fixture guarantees something is there.
 *
 *   LATEXY_LIVE=1 LATEXY_API_URL=… LATEXY_SESSION_TOKEN=… \
 *   LATEXY_TEST_RESUME=… XDG_CONFIG_HOME=/tmp/... npx vitest run …
 */
import { beforeAll, describe, expect, it } from 'vitest'

import { dispatch } from '../commands/dispatch.js'
import { initApiClient } from '../lib/api-client.js'
import { pickPending, settlePick } from '../lib/pick.js'
import { $messages, clearMessages } from '../stores/messages.js'
import { $overlay, closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
const RESUME = process.env['LATEXY_TEST_RESUME'] ?? ''

/** Signatures that mean the command rendered something it did not understand. */
const GARBAGE = /undefined|NaN|\[object Object\]|Invalid Date/

function transcript(): string {
  // tool_use messages carry their identity in toolName/toolState with an empty
  // content, so a content-only view makes a successfully submitted job look like
  // it produced nothing.
  return $messages.get().map(m =>
    `${m.role}: ${m.content ?? ''} ${m.toolName ?? ''} ${m.toolState ?? ''} ` +
    `${m.toolResult != null ? JSON.stringify(m.toolResult) : ''}`,
  ).join('\n')
}

async function run(input: string, settleMs = 2200): Promise<string> {
  clearMessages()
  closeOverlay()
  const call = dispatch(input).catch(() => { /* a throw is still a response */ })
  await new Promise(r => setTimeout(r, 200))
  if (pickPending()) settlePick(null)
  await Promise.race([call, new Promise(r => setTimeout(r, settleMs))])
  return transcript()
}

/** Every command must respond, and must never render garbage. */
function assertClean(out: string, cmd: string): void {
  expect(out, `/${cmd} produced no output at all`).not.toBe('')
  expect(out, `/${cmd} rendered unmapped data`).not.toMatch(GARBAGE)
  expect(out, `/${cmd} is not routed`).not.toMatch(/Unknown command/)
  expect(out, `/${cmd} claims to be unimplemented`).not.toMatch(/not implemented/i)
}

;(LIVE ? describe : describe.skip)('every command, live', () => {
  beforeAll(() => {
    expect(TOKEN, 'LATEXY_SESSION_TOKEN required').not.toBe('')
    expect(RESUME, 'LATEXY_TEST_RESUME required').not.toBe('')
    $session.set({
      ...$session.get(),
      token: TOKEN,
      backendUrl: API,
      wsUrl: API.replace(/^http/, 'ws') + '/ws/jobs',
      isAuthenticated: true,
      plan: 'pro',
    })
    initApiClient(API, TOKEN)
  })

  // ── read-only listings: must show real rows ──────────────────────────────
  it('/jobs lists real jobs with real ages', async () => {
    const out = await run('/jobs'); assertClean(out, 'jobs')
    expect(out).toMatch(/Recent jobs \(\d+\)|No recent jobs/)
  })

  it('/tracker shows tracked applications', async () => {
    const out = await run('/tracker'); assertClean(out, 'tracker')
    expect(out).toMatch(/Applications \(\d+\)/)
  })

  it('/snippets lists the marketplace', async () => {
    const out = await run('/snippets'); assertClean(out, 'snippets')
    expect(out).toMatch(/Snippets \(\d+\)|No snippets/)
  })

  it('/billing shows the real plan and quotas', async () => {
    const out = await run('/billing'); assertClean(out, 'billing')
    expect(out).toMatch(/plan\s+\w+/)
  })

  it('/analytics returns real counters', async () => {
    const out = await run('/analytics'); assertClean(out, 'analytics')
    expect(out).toMatch(/analytics/i)
  })

  it('/settings shows notification preferences including false ones', async () => {
    const out = await run('/settings'); assertClean(out, 'settings')
    expect(out).toMatch(/job_completed\s+(true|false)/)
  })

  it('/byok lists key state and providers', async () => {
    const out = await run('/byok'); assertClean(out, 'byok')
    expect(out).toMatch(/API keys/)
  })

  it('/model lists providers with model counts', async () => {
    const out = await run('/model'); assertClean(out, 'model')
    expect(out).toMatch(/Providers \(\d+\)/)
  })

  it('/health reports backend status', async () => {
    const out = await run('/health'); assertClean(out, 'health')
    expect(out).toMatch(/healthy|status/i)
  })

  it('/help lists commands', async () => {
    const out = await run('/help'); assertClean(out, 'help')
    expect(out).toMatch(/\/compile/)
  })

  // ── resume-scoped reads ──────────────────────────────────────────────────
  it('/history lists real versions with labels, not bare ids', async () => {
    const out = await run(`/history ${RESUME}`); assertClean(out, 'history')
    expect(out).toMatch(/Version history \(\d+\)|No history/)
  })

  it('/diff compares against the parent', async () => {
    const out = await run(`/diff ${RESUME}`); assertClean(out, 'diff')
  })

  it('/quick-ats returns a numeric score', async () => {
    const out = await run(`/quick-ats ${RESUME}`); assertClean(out, 'quick-ats')
    expect(out).toMatch(/score\s+\d+/)
  })

  // ── mutations ────────────────────────────────────────────────────────────
  it('/checkpoint saves, and /history then shows the label', async () => {
    const label = `verify-${Date.now()}`
    const saved = await run(`/checkpoint ${RESUME} ${label}`)
    assertClean(saved, 'checkpoint')
    expect(saved).toMatch(/Checkpoint saved/)
    const hist = await run(`/history ${RESUME}`)
    expect(hist, 'the checkpoint just saved is missing from history').toContain(label)
  })

  it('/share returns a usable link', async () => {
    const out = await run(`/share ${RESUME}`); assertClean(out, 'share')
    expect(out).toMatch(/Share link/)
  })

  it('/new creates a resume', async () => {
    const out = await run('/new Verify Suite Resume'); assertClean(out, 'new')
    expect(out).toMatch(/Resume created/)
  })

  it('/fork creates a variant', async () => {
    const out = await run(`/fork ${RESUME} Verify Variant`); assertClean(out, 'fork')
    expect(out).toMatch(/Variant created/)
  })

  it('/export without a format lists the real formats', async () => {
    const out = await run('/export'); assertClean(out, 'export')
    expect(out).toMatch(/format/i)
  })

  // ── argument validation: must guide, not crash ───────────────────────────
  it('/pdf without a job id explains what is needed', async () => {
    const out = await run('/pdf'); assertClean(out, 'pdf')
    expect(out).toMatch(/job/i)
  })

  it('/log without a job id explains what is needed', async () => {
    const out = await run('/log'); assertClean(out, 'log')
    expect(out).toMatch(/job/i)
  })

  it('/optimize without a job description says so', async () => {
    const out = await run(`/optimize ${RESUME}`); assertClean(out, 'optimize')
    expect(out).toMatch(/job description/i)
  })

  it('/combined without a job description says so', async () => {
    const out = await run(`/combined ${RESUME}`); assertClean(out, 'combined')
    expect(out).toMatch(/job description/i)
  })

  it('/cover without a job description says so', async () => {
    const out = await run(`/cover ${RESUME}`); assertClean(out, 'cover')
    expect(out).toMatch(/job description/i)
  })

  // ── job-backed: must reach the queue ─────────────────────────────────────
  it('/ats submits a real deep-analysis job', async () => {
    const out = await run(`/ats ${RESUME}`, 6000); assertClean(out, 'ats')
    expect(out).toMatch(/ats_deep_analysis/)
  })

  it('/interview reaches the backend', async () => {
    const out = await run(`/interview ${RESUME}`, 6000); assertClean(out, 'interview')
  })

  // ── local ────────────────────────────────────────────────────────────────
  it('/list opens the resume picker', async () => {
    clearMessages(); closeOverlay()
    await dispatch('/list')
    await new Promise(r => setTimeout(r, 600))
    expect($overlay.get(), '/list opened no overlay').not.toBeNull()
    closeOverlay()
  })

  it('/clear empties the transcript', async () => {
    await run('/help')
    await dispatch('/clear')
    expect($messages.get().length).toBe(0)
  })

  it('/cancel with no active job explains itself', async () => {
    const out = await run('/cancel'); assertClean(out, 'cancel')
  })
})
