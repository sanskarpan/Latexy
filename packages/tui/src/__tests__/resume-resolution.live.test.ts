/**
 * Which resume a command acts on, and the single-job slot.
 *
 * Two defects from the round-4 audit:
 *  - ResumePicker has always written `defaultResumeId`, but nothing read it back,
 *    so choosing a resume in /list changed nothing and every later command asked
 *    again. resolveResumeId's own doc comment claimed otherwise.
 *  - /compile skipped resolution entirely and compiled whichever resume sorted
 *    first, on the most-used command in the TUI.
 *  - /cancel never cleared $activeJobId, so a job whose terminal event never
 *    arrived locked the user out of starting anything, and the one command the
 *    error message named could not clear it.
 */
import { mkdtempSync } from 'node:fs'
import { join } from 'node:path'
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { dispatch } from '../commands/dispatch.js'
import { initApiClient } from '../lib/api-client.js'
import { pickPending, settlePick } from '../lib/pick.js'
import { $messages, clearMessages, $activeJobId } from '../stores/messages.js'
import { closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'
import { claimJobSlot, releaseJobSlot, resolveResumeId } from '../tools/shared.js'
import { writeConfig } from '../lib/config.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
const R1 = process.env['LATEXY_TEST_RESUME'] ?? ''
const R2 = process.env['LATEXY_TEST_RESUME2'] ?? ''

function transcript(): string {
  return $messages.get().map(m =>
    `${m.role}: ${m.content ?? ''} ${m.toolName ?? ''} ${m.toolState ?? ''} ` +
    `${m.toolArgs != null ? JSON.stringify(m.toolArgs) : ''}`).join('\n')
}

/**
 * Wait for the picker instead of sleeping a fixed interval.
 *
 * These used to sleep 500-600ms, which was enough until resume resolution grew a
 * validation round-trip — then they failed intermittently under parallel load,
 * looking like a resolution bug rather than an impatient test.
 */
async function waitForPicker(timeoutMs = 6000): Promise<boolean> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (pickPending()) return true
    await new Promise(r => setTimeout(r, 50))
  }
  return false
}

;(LIVE ? describe : describe.skip)('resume resolution and the job slot', () => {
  beforeAll(() => {
    // Own config dir: these suites both write defaultResumeId, and sharing one
    // made each see the other's writes. Derived from the sandbox root so the
    // outside-$HOME guard still holds.
    const root = process.env['XDG_CONFIG_HOME']
    if (root != null && root !== '') {
      process.env['XDG_CONFIG_HOME'] = mkdtempSync(join(root, 'resume-resolution-'))
    }

    // This suite writes config. Refuse to run anywhere that could be the
    // developer's real one — /logout lives in the same store and clearing it is
    // unrecoverable.
    const xdg = process.env['XDG_CONFIG_HOME'] ?? ''
    expect(xdg, 'XDG_CONFIG_HOME must be set').not.toBe('')
    expect(xdg.startsWith(process.env['HOME'] ?? ''), 'XDG_CONFIG_HOME must be outside $HOME').toBe(false)
    expect(TOKEN).not.toBe('')
    expect(R1).not.toBe('')
    expect(R2).not.toBe('')

    $session.set({
      ...$session.get(), token: TOKEN, backendUrl: API,
      wsUrl: API.replace(/^http/, 'ws') + '/ws/jobs',
      isAuthenticated: true, plan: 'pro',
    })
    initApiClient(API, TOKEN)
  })

  beforeEach(() => {
    clearMessages(); closeOverlay(); $activeJobId.set(null); releaseJobSlot()
  })

  it('honours the default chosen in /list instead of prompting again', async () => {
    await writeConfig({ defaultResumeId: R2 })
    const chosen = await resolveResumeId({ name: 'edit', args: {}, positional: [], raw: '/edit' })
    expect(pickPending(), 'should not have asked').toBe(false)
    expect(chosen).toBe(R2)
  })

  it('an explicit id still beats the saved default', async () => {
    await writeConfig({ defaultResumeId: R2 })
    const chosen = await resolveResumeId({ name: 'edit', args: {}, positional: [R1], raw: `/edit ${R1}` })
    expect(chosen).toBe(R1)
  })

  it('a stale default pointing at a deleted resume falls back to the picker', async () => {
    await writeConfig({ defaultResumeId: '00000000-0000-0000-0000-000000000000' })
    const pending = resolveResumeId({ name: 'edit', args: {}, positional: [], raw: '/edit' })
    expect(await waitForPicker(), 'a deleted default must not wedge every command behind a 404').toBe(true)
    settlePick(null)
    expect(await pending).toBeNull()
  })

  it('a bare --resume flag is not used as a resume id', async () => {
    await writeConfig({ defaultResumeId: R2 })
    // `--resume` with no value parses to boolean true, which used to be returned
    // as the id and built a request against /resumes/true.
    const chosen = await resolveResumeId({ name: 'edit', args: { resume: true }, positional: [], raw: '/edit --resume' })
    expect(chosen).toBe(R2)
  })

  it('/compile uses the saved default rather than whichever resume sorts first', async () => {
    await writeConfig({ defaultResumeId: R2 })
    await dispatch('/compile').catch(() => {})
    await new Promise(r => setTimeout(r, 2500))
    const card = $messages.get().find(m => m.role === 'tool_use')
    expect(card, `no compile card. Transcript:\n${transcript()}`).toBeDefined()
    expect((card!.toolArgs as { resume_id?: string }).resume_id).toBe(R2)
  })

  it('/cancel releases the slot so the user can start another job', async () => {
    $activeJobId.set('00000000-0000-0000-0000-000000000000')
    expect(claimJobSlot(), 'slot is held').toBe(false)
    releaseJobSlot()

    await dispatch('/cancel 00000000-0000-0000-0000-000000000000').catch(() => {})
    expect($activeJobId.get(), 'an unknown job must not hold the slot hostage').toBeNull()
    expect(claimJobSlot(), 'user is still locked out after /cancel').toBe(true)
  })
})
