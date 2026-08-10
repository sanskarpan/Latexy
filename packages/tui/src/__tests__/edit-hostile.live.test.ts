/**
 * TEMPORARY PROBE — hostile-editor cases the existing edit-safety suite does not cover.
 * A user's resume must survive every one of these.
 */
import { beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { runEdit } from '../tools/resume-commands.js'
import { getApiClient, initApiClient } from '../lib/api-client.js'
import { $messages, clearMessages } from '../stores/messages.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
// Its own resume, not LATEXY_TEST_RESUME. This suite and edit-safety.live both
// rewrite their target's content, and vitest runs files in parallel — sharing one
// resume made each suite see the other's writes and fail as if /edit were broken.
const RESUME = process.env['LATEXY_TEST_EDIT_RESUME'] ?? ''
const FIX = process.env['LATEXY_FIXTURES'] ?? ''
const ORIGINAL = '\\documentclass{article}\\begin{document}KEEP THIS\\end{document}'

async function content(): Promise<string> {
  return (await getApiClient().get<{ latex_content: string }>(`/resumes/${RESUME}`)).latex_content
}

async function edit(editor: string): Promise<string> {
  process.env['EDITOR'] = editor
  clearMessages()
  await runEdit({ name: 'edit', args: {}, positional: [RESUME], raw: '/edit' })
  return $messages.get().map(m => `${m.role}: ${m.content ?? ''}`).join('\n')
}

;(LIVE ? describe : describe.skip)('PROBE /edit hostile editors', () => {
  beforeAll(() => {
    expect(RESUME, 'LATEXY_TEST_EDIT_RESUME required — a resume this suite owns exclusively').not.toBe('')
    expect(FIX, 'LATEXY_FIXTURES required — without it this suite spawns /ed_*.sh and fails misleadingly').not.toBe('')
    $session.set({ ...$session.get(), token: TOKEN, backendUrl: API, isAuthenticated: true, plan: 'pro' })
    initApiClient(API, TOKEN)
  })

  beforeEach(async () => {
    await getApiClient().put(`/resumes/${RESUME}`, { latex_content: ORIGINAL })
  })

  it('an editor killed by SIGKILL after truncating does not save', async () => {
    const out = await edit(`${FIX}/ed_kill.sh`)
    expect(out, 'must name the signal').toMatch(/killed \(SIGKILL\)/)
    expect(await content(), 'resume was destroyed by a killed editor').toBe(ORIGINAL)
  })

  it('an editor writing latin-1 does not silently corrupt characters', async () => {
    const out = await edit(`${FIX}/ed_latin1.sh`)
    expect(out, 'must refuse rather than save mojibake').toMatch(/not valid UTF-8/)
    expect(await content()).toBe(ORIGINAL)
    expect(await content(), 'replacement chars reached the server').not.toMatch(/�/)
  })

  it('an editor that deletes the temp file does not save', async () => {
    const out = await edit(`${FIX}/ed_delete.sh`)
    expect(await content(), 'resume was destroyed when the temp file vanished').toBe(ORIGINAL)
    expect(out, 'must not claim it saved').not.toMatch(/Saved/)
  })

  it('$EDITOR with arguments is spawned correctly, not treated as one binary name', async () => {
    // "code --wait" is the documented VS Code value.
    const out = await edit(`/bin/sh -c`)
    expect(out, 'must not report ENOENT naming a binary the user never set').not.toMatch(/ENOENT/)
  })
})
