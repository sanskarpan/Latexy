/**
 * The single-job slot must never wedge.
 *
 * It is module-level mutable state claimed synchronously before any await, so a
 * path that claims and then returns without submitting would lock the user out
 * of starting any job until they restart the TUI. Every early return has to
 * release it.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { busyWithAnotherJob, claimJobSlot, releaseJobSlot } from '../tools/shared.js'
import { runAts, runCombined, runOptimize } from '../tools/ai-commands.js'
import { initApiClient } from '../lib/api-client.js'
import { $activeJobId, clearMessages } from '../stores/messages.js'
import { pickPending, settlePick } from '../lib/pick.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
const RESUME = process.env['LATEXY_TEST_RESUME'] ?? ''
const GHOST = '00000000-0000-4000-8000-000000000000'

const cmd = (name: string, positional: string[], args: Record<string, string | boolean> = {}) =>
  ({ name, args, positional, raw: `/${name}` })

;(LIVE ? describe : describe.skip)('the job slot never wedges', () => {
  beforeAll(async () => {
    $session.set({ ...$session.get(), token: TOKEN, backendUrl: API, isAuthenticated: true, plan: 'pro' })
    initApiClient(API, TOKEN)

    // The cancelled-picker case only exercises the leak when more than one
    // resume exists, so guarantee that here rather than depending on fixture
    // state a concurrent process might have cleaned up.
    const client = initApiClient(API, TOKEN)
    const list = await client.get<{ resumes: unknown[] }>('/resumes/?limit=5')
    if ((list.resumes ?? []).length < 2) {
      await client.post('/resumes/', {
        title: 'Slot Fixture Second',
        latex_content: '\\documentclass{article}\\begin{document}SECOND\\end{document}',
      })
    }
  })

  beforeEach(() => {
    clearMessages()
    releaseJobSlot()
    $activeJobId.set(null)
  })

  it('releases when no job description was supplied', async () => {
    await runOptimize(cmd('optimize', [RESUME]))
    expect(busyWithAnotherJob(), 'slot stuck after a missing --jd').toBe(false)
  })

  it('releases when the resume does not exist', async () => {
    await runOptimize(cmd('optimize', [GHOST], { jd: 'Some job description text here.' }))
    expect(busyWithAnotherJob(), 'slot stuck after a 404 resume').toBe(false)
  })

  it('releases when the user cancels the resume picker', async () => {
    // Needs >1 resume, otherwise resolveResumeId auto-selects and a job really
    // does start — in which case a held slot is correct, not a leak.
    const call = runCombined(cmd('combined', [], { jd: 'text' }))
    await new Promise(r => setTimeout(r, 500))
    expect(pickPending(), 'picker did not open — fixture needs two resumes').toBe(true)
    settlePick(null)
    await call
    expect(busyWithAnotherJob(), 'slot stuck after cancelling the picker').toBe(false)
    expect($activeJobId.get(), 'a job was started despite cancelling').toBeNull()
  })

  it('releases when the ATS submission fails on a bad resume', async () => {
    await runAts(cmd('ats', [GHOST]))
    expect(busyWithAnotherJob(), 'slot stuck after a failed ATS submit').toBe(false)
  })

  it('a second command is refused while the first genuinely holds the slot', () => {
    expect(claimJobSlot()).toBe(true)
    expect(claimJobSlot(), 'two commands both claimed the slot').toBe(false)
    releaseJobSlot()
    expect(claimJobSlot()).toBe(true)
    releaseJobSlot()
  })

  it('the slot is not claimable while a job is actually tracked', () => {
    $activeJobId.set('some-running-job')
    expect(claimJobSlot(), 'claimed the slot while a job was running').toBe(false)
    $activeJobId.set(null)
  })

  it('three concurrent dispatches submit at most one job', async () => {
    const before = Date.now()
    const results = await Promise.all([
      runOptimize(cmd('optimize', [RESUME], { jd: 'Backend engineer, Go, Kubernetes.' })),
      runCombined(cmd('combined', [RESUME], { jd: 'Backend engineer, Go, Kubernetes.' })),
      runAts(cmd('ats', [RESUME])),
    ])
    expect(results).toHaveLength(3)
    expect(Date.now() - before).toBeLessThan(60_000)
    // Exactly one may hold the slot; the guard runs synchronously so the other
    // two are refused before they can reach the network.
    releaseJobSlot()
    $activeJobId.set(null)
  })
})
