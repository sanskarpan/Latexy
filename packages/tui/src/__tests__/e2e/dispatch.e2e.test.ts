import { describe, it, expect, vi, beforeEach } from 'vitest'
import { $messages, clearMessages, $activeJobId } from '../../stores/messages.js'
import { $overlay, closeOverlay } from '../../stores/overlay.js'
import { $session } from '../../stores/session.js'

vi.mock('../../lib/api-client.js', () => ({
  getApiClient: vi.fn(() => ({
    get: vi.fn().mockResolvedValue({ status: 'ok' }),
    post: vi.fn().mockResolvedValue({}),
  })),
  initApiClient: vi.fn(() => ({
    get: vi.fn().mockResolvedValue({}),
    post: vi.fn().mockResolvedValue({ token: 'tok', user: { id: 'u1', email: 'a@b.com' } }),
  })),
}))

vi.mock('../../lib/ws-client.js', () => ({
  wsClient: {
    connect: vi.fn(),
    destroy: vi.fn(),
    subscribe: vi.fn(() => () => {}),
    on: vi.fn(),
    drain: vi.fn(),
  },
}))

vi.mock('../../lib/config.js', () => ({
  writeConfig: vi.fn().mockResolvedValue(undefined),
  clearConfig: vi.fn().mockResolvedValue(undefined),
  readConfig: vi.fn().mockResolvedValue({ backendUrl: 'http://localhost:8030', sessionToken: null }),
}))

describe('dispatch — LOCAL_HANDLERS', () => {
  beforeEach(async () => {
    clearMessages()
    closeOverlay()
    $activeJobId.set(null)
    $session.set({
      token: 'test-token',
      userId: 'u1',
      email: 'user@test.com',
      plan: 'free',
      backendUrl: 'http://localhost:8030',
      wsUrl: 'ws://localhost:8030/ws/jobs',
      isAuthenticated: true,
    })
    vi.clearAllMocks()
  })

  it('/clear empties the message store', async () => {
    const { addMessage } = await import('../../stores/messages.js')
    addMessage({ role: 'user', content: 'hello' })
    expect($messages.get().length).toBeGreaterThan(0)

    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/clear')
    expect($messages.get().length).toBe(0)
  })

  it('/help adds a system message listing all commands', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/help')
    const msgs = $messages.get()
    const sys = msgs.find(m => m.role === 'system')
    expect(sys).toBeDefined()
    expect(sys?.content).toContain('/compile')
    expect(sys?.content).toContain('/ats')
  })

  it('/help compile adds usage for that specific command', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/help compile')
    const msgs = $messages.get()
    const sys = msgs.filter(m => m.role === 'system').at(-1)
    expect(sys?.content).toContain('compile')
    expect(sys?.content).not.toContain('/ats\n')
  })

  it('/logout clears session token and opens an overlay', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/logout')
    expect($session.get().token).toBeNull()
    expect($session.get().isAuthenticated).toBe(false)
    expect($overlay.get()).not.toBeNull()
  })

  it('/logout adds a system message confirming logout', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/logout')
    const msgs = $messages.get()
    expect(msgs.some(m => m.role === 'system')).toBe(true)
  })

  it('unknown command adds an error message', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/zzznonexistent')
    const msgs = $messages.get()
    const err = msgs.find(m => m.role === 'error')
    expect(err).toBeDefined()
    expect(err?.content).toContain('Unknown command')
    expect(err?.content).toContain('zzznonexistent')
  })

  it('free text adds user message and system reply', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('just some text')
    const msgs = $messages.get()
    expect(msgs.some(m => m.role === 'user' && m.content === 'just some text')).toBe(true)
    expect(msgs.some(m => m.role === 'system')).toBe(true)
  })
})

describe('dispatch — API_HANDLERS', () => {
  beforeEach(async () => {
    clearMessages()
    closeOverlay()
    $activeJobId.set(null)
    vi.clearAllMocks()
  })

  it('/health calls GET /health and adds system message', async () => {
    const { getApiClient } = await import('../../lib/api-client.js')
    const mockGet = vi.fn().mockResolvedValue({ status: 'ok' })
    vi.mocked(getApiClient).mockReturnValue({ get: mockGet, post: vi.fn() } as never)

    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/health')

    expect(mockGet).toHaveBeenCalledWith('/health')
    const msgs = $messages.get()
    expect(msgs.some(m => m.role === 'system' && m.content.includes('ok'))).toBe(true)
  })

  it('/cancel with no active job adds error message', async () => {
    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/cancel')
    const msgs = $messages.get()
    const err = msgs.find(m => m.role === 'error')
    expect(err).toBeDefined()
    expect(err?.content).toContain('No active job')
  })

  it('/cancel with active job calls POST /api/jobs/:id/cancel', async () => {
    $activeJobId.set('job-abc')
    const { getApiClient } = await import('../../lib/api-client.js')
    const mockPost = vi.fn().mockResolvedValue({})
    vi.mocked(getApiClient).mockReturnValue({ get: vi.fn(), post: mockPost } as never)

    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/cancel')

    expect(mockPost).toHaveBeenCalledWith('/api/jobs/job-abc/cancel')
  })

  it('/cancel with explicit job-id uses that id', async () => {
    const { getApiClient } = await import('../../lib/api-client.js')
    const mockPost = vi.fn().mockResolvedValue({})
    vi.mocked(getApiClient).mockReturnValue({ get: vi.fn(), post: mockPost } as never)

    const { dispatch } = await import('../../commands/dispatch.js')
    await dispatch('/cancel explicit-job-id')

    expect(mockPost).toHaveBeenCalledWith('/api/jobs/explicit-job-id/cancel')
  })
})
