/**
 * /edit must never destroy a resume — exercised with a real child process.
 *
 * The exit code used to be discarded, so a crashed or killed $EDITOR still had
 * whatever bytes were on disk written back: a truncated file silently replaced
 * the resume while the TUI reported "Saved". /restore predates the edit, so
 * there was no recovery.
 */
import { beforeAll, describe, expect, it } from 'vitest'

import { runEdit } from '../tools/resume-commands.js'
import { getApiClient, initApiClient } from '../lib/api-client.js'
import { $messages, clearMessages } from '../stores/messages.js'
import { $session } from '../stores/session.js'

const LIVE = process.env['LATEXY_LIVE'] === '1'
const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
const RESUME = process.env['LATEXY_TEST_RESUME'] ?? ''
const SANDBOX = process.env['LATEXY_FIXTURES'] ?? ''
const ORIGINAL = '\\documentclass{article}\\begin{document}KEEP THIS\\end{document}'

async function content(): Promise<string> {
  const r = await getApiClient().get<{ latex_content: string }>(`/resumes/${RESUME}`)
  return r.latex_content
}

async function edit(editor: string): Promise<string> {
  process.env['EDITOR'] = editor
  clearMessages()
  await runEdit({ name: 'edit', args: {}, positional: [RESUME], raw: '/edit' })
  return $messages.get().map(m => `${m.role}: ${m.content ?? ''}`).join('\n')
}

;(LIVE ? describe : describe.skip)('/edit never destroys a resume', () => {
  beforeAll(() => {
    $session.set({ ...$session.get(), token: TOKEN, backendUrl: API, isAuthenticated: true, plan: 'pro' })
    initApiClient(API, TOKEN)
  })

  it('an editor that truncates then exits nonzero does not save', async () => {
    await getApiClient().put(`/resumes/${RESUME}`, { latex_content: ORIGINAL })
    const out = await edit(`${SANDBOX}/ed_fail.sh`)
    expect(out, 'no error reported').toMatch(/exited with code 3/)
    expect(await content(), 'resume was destroyed').toBe(ORIGINAL)
  })

  it('an editor that empties the file then exits cleanly does not save', async () => {
    await getApiClient().put(`/resumes/${RESUME}`, { latex_content: ORIGINAL })
    const out = await edit(`${SANDBOX}/ed_empty.sh`)
    expect(out).toMatch(/empty/i)
    expect(await content(), 'resume was emptied').toBe(ORIGINAL)
  })

  it('a real edit after a clean exit does save', async () => {
    await getApiClient().put(`/resumes/${RESUME}`, { latex_content: ORIGINAL })
    const out = await edit(`${SANDBOX}/ed_good.sh`)
    expect(out).toMatch(/Saved/)
    expect(await content()).toContain('EDITED')
  })
})
