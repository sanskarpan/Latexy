/**
 * Live integration tests: the real dispatch layer against a running backend.
 *
 * The rest of the suite mocks the API client, which proves the UI reacts
 * correctly to invented responses but not that any command actually reaches the
 * backend. These run the real dispatch(), the real ApiClient and real HTTP.
 *
 * Skipped unless LATEXY_LIVE=1 and a backend is reachable, so CI is unaffected:
 *
 *   LATEXY_LIVE=1 LATEXY_API_URL=http://localhost:8030 \
 *   LATEXY_SESSION_TOKEN=<token> npx vitest run src/__tests__/live
 */
import { beforeAll, describe, expect, it } from 'vitest'

import { dispatch } from '../commands/dispatch.js'
import { SLASH_COMMANDS } from '../commands/registry.js'
import { initApiClient } from '../lib/api-client.js'
import { $messages, clearMessages } from '../stores/messages.js'
import { $overlay, closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''

const d = LIVE ? describe : describe.skip

/** Text of every message produced since the last reset. */
function transcript(): string {
  return $messages.get().map(m => `${m.role}: ${m.content ?? ''} ${JSON.stringify(m.toolResult ?? '')}`).join('\n')
}

function errors(): string[] {
  return $messages.get().filter(m => m.role === 'error').map(m => m.content ?? '')
}

async function run(input: string): Promise<void> {
  clearMessages()
  closeOverlay()
  await dispatch(input)
  // Let any floating promise inside a handler settle.
  await new Promise(r => setTimeout(r, 400))
}

d('TUI commands against a live backend', () => {
  beforeAll(async () => {
    expect(TOKEN, 'LATEXY_SESSION_TOKEN must be set for live tests').not.toBe('')
    $session.set({
      ...$session.get(),
      token: TOKEN,
      backendUrl: API,
      wsUrl: API.replace(/^http/, 'ws') + '/ws/jobs',
      isAuthenticated: true,
      plan: 'pro',
    })
    initApiClient(API, TOKEN)

    const health = await fetch(`${API}/health`).then(r => r.json())
    expect(health.status, 'backend must be healthy').toBe('healthy')
  })

  it('backend is actually reachable with this token', async () => {
    const res = await fetch(`${API}/resumes/`, {
      headers: { Authorization: `Bearer ${TOKEN}` },
    })
    expect(res.status, 'token must authenticate').toBe(200)
  })

  // ── local commands: no network, must not throw ───────────────────────────
  for (const name of ['help', 'clear']) {
    it(`/${name} runs without error`, async () => {
      await run(`/${name}`)
      expect(errors(), `/${name} produced an error`).toEqual([])
    })
  }

  it('/help <command> describes a real command', async () => {
    await run('/help compile')
    expect(transcript()).toContain('/compile')
  })

  // ── overlay commands that are actually implemented ───────────────────────
  for (const name of ['list']) {
    it(`/${name} opens an overlay`, async () => {
      await run(`/${name}`)
      expect(errors(), `/${name} errored`).toEqual([])
      expect($overlay.get(), `/${name} opened no overlay`).not.toBeNull()
    })
  }

  // ── unimplemented commands must say so, not claim to be unknown ──────────
  // These are still in the registry (so /help can describe what is planned) but
  // are filtered out of autocomplete. If a user types one anyway, the answer has
  // to be truthful: "not implemented yet", not "unknown command".
  for (const name of ['optimize', 'ats', 'byok', 'model', 'tracker']) {
    it(`/${name} reports that it is not implemented`, async () => {
      await run(`/${name}`)
      const said = transcript().toLowerCase()
      expect(said, `/${name} gave a misleading answer`).toContain('not implemented')
      expect(said, `/${name} still claims to be unknown`).not.toContain('unknown command')
    })
  }

  // ── API commands: must reach the backend without a client-side crash ─────
  const API_COMMANDS: Array<[string, string]> = [
    ['health', '/health'],
    ['analytics', '/analytics'],
    ['history', '/history'],
    ['new', '/new Live Test Resume'],
  ]

  for (const [name, input] of API_COMMANDS) {
    it(`/${name} reaches the backend`, async () => {
      await run(input)
      const errs = errors().join(' ')
      expect(errs, `/${name} failed: ${errs}`).not.toMatch(/ECONNREFUSED|Unexpected token|is not a function|undefined is not/)
    })
  }

  it('no command silently does nothing', async () => {
    // Whatever a command's status, it must produce *some* response — an overlay,
    // a result, or an explicit "not implemented". Silence is the one unacceptable
    // outcome, because the user cannot tell it apart from a hang.
    const silent: string[] = []
    for (const cmd of SLASH_COMMANDS) {
      if (cmd.name === 'logout') continue   // mutates real on-disk state
      // /clear's entire purpose is to empty the transcript, so an empty
      // transcript afterwards is success, not silence.
      if (cmd.name === 'clear') continue
      clearMessages()
      closeOverlay()
      try { await dispatch(`/${cmd.name}`) } catch { /* a throw is still a response */ }
      await new Promise(r => setTimeout(r, 120))
      if ($messages.get().length === 0 && $overlay.get() === null) silent.push(cmd.name)
    }
    expect(silent, `commands that produced no response at all: ${silent.join(', ')}`).toEqual([])
  }, 60_000)

  it('an unknown command is rejected, not silently ignored', async () => {
    await run('/definitelynotacommand')
    expect(transcript().toLowerCase()).toMatch(/unknown|not found|no such/)
  })
})
