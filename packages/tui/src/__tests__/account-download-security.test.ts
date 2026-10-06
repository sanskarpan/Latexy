import { beforeEach, describe, expect, it, vi } from 'vitest'

import { clearMessages, $messages } from '../stores/messages.js'
import { $session } from '../stores/session.js'

const getBinary = vi.fn()

vi.mock('../lib/api-client.js', () => ({
  getApiClient: () => ({ getBinary }),
}))

describe('/pdf download security', () => {
  beforeEach(() => {
    clearMessages()
    getBinary.mockReset()
    $session.set({ ...$session.get(), isAuthenticated: true, token: 'test-token' })
  })

  it('rejects path-like job ids before making a request', async () => {
    const { runPdf } = await import('../tools/account-commands.js')
    await runPdf({ name: 'pdf', args: {}, positional: ['../../settings'], raw: '/pdf ../../settings' })

    expect(getBinary).not.toHaveBeenCalled()
    expect($messages.get().at(-1)?.content).toMatch(/complete UUID/)
  })

  it('refuses to save an authenticated response that is not a PDF', async () => {
    const { runPdf } = await import('../tools/account-commands.js')
    getBinary.mockResolvedValue(Buffer.from('{"detail":"not found"}'))
    await runPdf({
      name: 'pdf',
      args: {},
      positional: ['123e4567-e89b-42d3-a456-426614174000'],
      raw: '/pdf 123e4567-e89b-42d3-a456-426614174000',
    })

    expect($messages.get().at(-1)?.content).toMatch(/not a PDF/)
  })
})
