/**
 * Audit every registered slash command against a live backend.
 *
 * Reports, per command, whether dispatch() actually routes it — a command that
 * appears in autocomplete and /help but falls through to "Unknown command" is
 * dead UI.
 *
 *   LATEXY_LIVE=1 LATEXY_API_URL=http://localhost:8030 \
 *   LATEXY_SESSION_TOKEN=<token> npx vitest run src/__tests__/audit.live.test.ts
 */
import { describe, expect, it } from 'vitest'

import { dispatch } from '../commands/dispatch.js'
import { SLASH_COMMANDS } from '../commands/registry.js'
import { initApiClient } from '../lib/api-client.js'
import { $messages, clearMessages } from '../stores/messages.js'
import { $overlay, closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''

// NEVER dispatch these in a test: they mutate real on-disk state. /logout calls
// clearConfig(), which wipes the developer's stored session token from
// ~/.config/latexy/config.toml unless XDG_CONFIG_HOME is redirected — which is
// exactly what happened the first time this file was run.
const DESTRUCTIVE = new Set(['logout'])

;(LIVE ? describe : describe.skip)('slash command audit', () => {
  it('refuses to run against the real user config', () => {
    // Belt and braces: even with DESTRUCTIVE guarded, a future command could
    // write to disk. The suite must only ever run against a throwaway config dir.
    const xdg = process.env['XDG_CONFIG_HOME'] ?? ''
    expect(
      xdg && !xdg.startsWith(process.env['HOME'] ?? '~'),
      'XDG_CONFIG_HOME must point outside $HOME before running live tests',
    ).toBe(true)
  })

  it('every registered command is routed by dispatch', async () => {
    $session.set({
      ...$session.get(),
      token: TOKEN,
      backendUrl: API,
      wsUrl: API.replace(/^http/, 'ws') + '/ws/jobs',
      isAuthenticated: true,
      plan: 'pro',
    })
    initApiClient(API, TOKEN)

    const dead: string[] = []
    const routed: string[] = []

    for (const cmd of SLASH_COMMANDS) {
      if (DESTRUCTIVE.has(cmd.name)) continue
      if (!cmd.implemented) continue   // advertised nowhere; see the invariant test below
      clearMessages()
      closeOverlay()
      try {
        await dispatch(`/${cmd.name}`)
      } catch {
        /* a throw still means it was routed */
      }
      await new Promise(r => setTimeout(r, 150))
      const unknown = $messages
        .get()
        .some(m => (m.content ?? '').includes(`Unknown command: /${cmd.name}`))
      ;(unknown ? dead : routed).push(cmd.name)
    }

    // eslint-disable-next-line no-console
    console.log(
      `\n  ROUTED (${routed.length}/${SLASH_COMMANDS.length}): ${routed.join(' ')}\n` +
        `\n  DEAD   (${dead.length}/${SLASH_COMMANDS.length}): ${dead.join(' ')}\n`,
    )

    expect(
      dead,
      `these commands are flagged implemented but dispatch does not route them: ${dead.join(', ')}`,
    ).toEqual([])
  }, 60_000)

  it('nothing unimplemented is ever advertised to the user', async () => {
    // The registry doubles as autocomplete and /help. An entry with no handler
    // that still appears there is what made 25 commands answer "Unknown command"
    // after the user picked them out of the menu.
    const { IMPLEMENTED_COMMANDS } = await import('../commands/registry.js')
    const lying = IMPLEMENTED_COMMANDS.filter(c => !c.implemented)
    expect(lying.map(c => c.name)).toEqual([])

    for (const cmd of IMPLEMENTED_COMMANDS) {
      clearMessages()
      closeOverlay()
      if (DESTRUCTIVE.has(cmd.name)) continue
      try { await dispatch(`/${cmd.name}`) } catch { /* routed */ }
      await new Promise(r => setTimeout(r, 120))
      const unknown = $messages.get().some(m => (m.content ?? '').includes('Unknown command'))
      expect(unknown, `/${cmd.name} is advertised but not routed`).toBe(false)
    }
  }, 60_000)
})
