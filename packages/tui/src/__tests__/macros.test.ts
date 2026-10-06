import { beforeEach, describe, expect, it, vi } from 'vitest'

import { runMacros } from '../tools/account-commands.js'
import { getApiClient } from '../lib/api-client.js'
import { $session } from '../stores/session.js'
import { $messages, clearMessages } from '../stores/messages.js'

const resumeId = '11111111-1111-4111-8111-111111111111'
const macroId = '22222222-2222-4222-8222-222222222222'
const parsed = (apply = false) => ({
  name: 'macros',
  args: { run: macroId, resume: resumeId, ...(apply ? { apply: true } : {}) },
  positional: [],
  raw: '/macros',
})

describe('/macros TUI command', () => {
  beforeEach(() => {
    clearMessages()
    $session.set({ ...$session.get(), isAuthenticated: true, token: 'test-token' })
    vi.restoreAllMocks()
  })

  function mockApi() {
    const client = getApiClient()
    vi.spyOn(client, 'get').mockImplementation(async (path: string) => {
      if (path === '/macros') return [{ id: macroId, name: 'Replace', script: 'replace "a" with "b"', script_version: 1 }]
      return { id: resumeId, title: 'Resume', latex_content: 'a' }
    })
    vi.spyOn(client, 'post').mockResolvedValue({ document: 'b', operation_count: 1, script_version: 1 })
    return client
  }

  it('previews by default and never writes the resume', async () => {
    const client = mockApi()
    const put = vi.spyOn(client, 'put')
    await runMacros(parsed())
    expect(put).not.toHaveBeenCalled()
    expect($messages.get().map((message) => message.content).join('\n')).toMatch(/preview/i)
  })

  it('writes only after explicit --apply', async () => {
    const client = mockApi()
    const put = vi.spyOn(client, 'put').mockResolvedValue(undefined)
    await runMacros(parsed(true))
    expect(put).toHaveBeenCalledWith(`/resumes/${resumeId}`, {
      latex_content: 'b',
      expected_latex_content: 'a',
    })
  })

  it('fails closed for a recorded macro because the execute API is script-only', async () => {
    const client = mockApi()
    vi.spyOn(client, 'get').mockImplementation(async (path: string) => {
      if (path === '/macros') return [{ id: macroId, name: 'Recorded', script: null, actions: [{ type: 'insert', text: 'x' }] }]
      return { id: resumeId, title: 'Resume', latex_content: 'a' }
    })
    vi.spyOn(client, 'post').mockRejectedValue(new Error('This macro has no executable script.'))
    const put = vi.spyOn(client, 'put')

    await runMacros(parsed())

    expect(put).not.toHaveBeenCalled()
    expect($messages.get().map((message) => message.content).join('\n')).toMatch(/Macro failed.*no executable script/i)
  })

  it('does not execute quarantined legacy macros and gives replacement guidance', async () => {
    const client = mockApi()
    vi.spyOn(client, 'get').mockImplementation(async (path: string) => {
      if (path === '/macros') {
        return [{
          id: macroId,
          name: 'Legacy',
          script: null,
          actions: [],
          legacy_actions_available: true,
        }]
      }
      throw new Error('resume should not be loaded')
    })
    const post = vi.spyOn(client, 'post')

    await runMacros(parsed())

    expect(post).not.toHaveBeenCalled()
    expect($messages.get().map((message) => message.content).join('\n')).toMatch(/delete.*record a replacement/i)
  })
})
