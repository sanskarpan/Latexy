/**
 * Every command must fail readably.
 *
 * The bar: no stack traces, no `[object Object]`, no bare "Error:", no claim of
 * success, and no crash — whether the server rejects the request or is not there
 * at all.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { dispatch } from '../commands/dispatch.js'
import { ApiClient, initApiClient } from '../lib/api-client.js'
import { pickPending, settlePick } from '../lib/pick.js'
import { $messages, clearMessages, $activeJobId } from '../stores/messages.js'
import { closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'
import { releaseJobSlot } from '../tools/shared.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''

/** Output that means the command did not understand its own failure. */
const GARBAGE = /undefined|NaN|\[object Object\]|Invalid Date/
/** A raw thrown object reaching the transcript. */
const RAW_THROW = /\bError: \[|\bTypeError\b|at Object\.|\n\s+at /

function transcript(): string {
  return $messages.get().map(m =>
    `${m.role}: ${m.content ?? ''} ${m.toolResult != null ? JSON.stringify(m.toolResult) : ''}`,
  ).join('\n')
}

async function run(input: string, settleMs = 3000): Promise<string> {
  clearMessages(); closeOverlay(); $activeJobId.set(null); releaseJobSlot()
  const call = dispatch(input).catch(() => { /* a throw is still a response */ })
  await new Promise(r => setTimeout(r, 250))
  if (pickPending()) settlePick(null)
  await Promise.race([call, new Promise(r => setTimeout(r, settleMs))])
  return transcript()
}

function assertReadable(out: string, label: string): void {
  expect(out, `${label}: produced no output`).not.toBe('')
  expect(out, `${label}: unmapped data`).not.toMatch(GARBAGE)
  expect(out, `${label}: leaked a raw throw`).not.toMatch(RAW_THROW)
}

;(LIVE ? describe : describe.skip)('error paths', () => {
  beforeAll(() => {
    $session.set({
      ...$session.get(), token: TOKEN, backendUrl: API,
      wsUrl: API.replace(/^http/, 'ws') + '/ws/jobs',
      isAuthenticated: true, plan: 'pro',
    })
  })

  beforeEach(() => { initApiClient(API, TOKEN) })

  it('422 names the offending field instead of printing [object Object]', async () => {
    // FastAPI returns `detail` as an ARRAY here; it used to be cast to a string.
    const client = new ApiClient({ baseUrl: API })
    client.setToken(TOKEN)
    const err = await client.post('/ats/quick-score', {}).catch((e: Error) => e)
    expect(err).toBeInstanceOf(Error)
    const msg = (err as Error).message
    expect(msg).not.toMatch(GARBAGE)
    expect(msg, `422 message was: ${msg}`).toMatch(/latex_content|Field required|validation/i)
  })

  it('401 surfaces the server wording, not a hardcoded label', async () => {
    const client = new ApiClient({ baseUrl: API })
    client.setToken('definitely-not-a-valid-token')
    const err = await client.get('/me').catch((e: Error) => e)
    expect((err as Error).message).not.toMatch(GARBAGE)
    expect((err as Error).message.length).toBeGreaterThan(3)
  })

  it('404 and 400 reach the user as sentences', async () => {
    const ghost = '00000000-0000-4000-8000-000000000000'
    assertReadable(await run(`/log ${ghost}`), '/log 404')
    assertReadable(await run('/log not-a-uuid'), '/log 400')
    assertReadable(await run(`/pdf ${ghost}`), '/pdf 404')
    assertReadable(await run(`/cancel ${ghost}`), '/cancel 404')
  })

  it('a command given a nonexistent resume explains itself', async () => {
    const ghost = '00000000-0000-4000-8000-000000000000'
    for (const cmd of [`/history ${ghost}`, `/diff ${ghost}`, `/export ${ghost} --format tex`]) {
      const out = await run(cmd)
      assertReadable(out, cmd)
      expect(out, `${cmd} reported success for a resume that does not exist`)
        .not.toMatch(/Exported|Version history \(/)
    }
  })

  it('survives the backend being unreachable, on every command shape', async () => {
    // A genuinely closed loopback port: ECONNREFUSED, not a filtered/black-holed one.
    initApiClient('http://127.0.0.1:65001', TOKEN)
    for (const cmd of ['/health', '/jobs', '/billing', '/analytics', '/settings',
                       '/snippets', '/model', '/byok', '/tracker']) {
      const out = await run(cmd, 4000)
      assertReadable(out, `${cmd} (backend down)`)
      expect(out, `${cmd} claimed success with no backend`).toMatch(/error|could not|failed|unreachable/i)
    }
  })

  it('recovers on the next command once the backend returns', async () => {
    initApiClient('http://127.0.0.1:65001', TOKEN)
    await run('/health', 4000)
    initApiClient(API, TOKEN)
    const out = await run('/health')
    expect(out).toMatch(/healthy/)
  })
})
