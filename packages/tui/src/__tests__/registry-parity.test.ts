/**
 * Guards the drift that produced 25 phantom commands.
 *
 * The registry doubles as autocomplete and /help, so an entry with no handler is
 * advertised to the user and then answered with "Unknown command". The invariant
 * is structural — the advertised set and the routed set must be the same set —
 * so it is checked without executing anything: deterministic, fast, no backend.
 *
 * The live suite (commands.live.test.ts) then actually runs commands against a
 * real backend, because "routed" is necessary but not sufficient.
 */
import { describe, expect, it } from 'vitest'

import { handlerNames } from '../commands/dispatch.js'
import { IMPLEMENTED_COMMANDS, SLASH_COMMANDS } from '../commands/registry.js'

describe('slash command registry <-> dispatch parity', () => {
  it('every advertised command has a handler', () => {
    const routed = handlerNames()
    const phantom = IMPLEMENTED_COMMANDS.map(c => c.name).filter(n => !routed.has(n))
    expect(
      phantom,
      `advertised in autocomplete and /help but not routed: ${phantom.join(', ')}`,
    ).toEqual([])
  })

  it('every handler is advertised — no hidden commands', () => {
    const advertised = new Set(IMPLEMENTED_COMMANDS.map(c => c.name))
    const orphan = [...handlerNames()].filter(n => !advertised.has(n))
    expect(orphan, `routed but invisible to the user: ${orphan.join(', ')}`).toEqual([])
  })

  it('the implemented flag agrees with reality', () => {
    const routed = handlerNames()
    const lying = SLASH_COMMANDS
      .filter(c => c.implemented !== routed.has(c.name))
      .map(c => `${c.name}(flag=${c.implemented}, routed=${routed.has(c.name)})`)
    expect(lying, 'registry flags disagree with dispatch').toEqual([])
  })
})
