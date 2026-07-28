import React from 'react'
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render } from 'ink-testing-library'
import { EventEmitter } from 'node:events'

const fakeWsClient = new EventEmitter() as EventEmitter & Record<string, unknown>
Object.assign(fakeWsClient, {
  connect: vi.fn(),
  drain: vi.fn(),
  subscribe: vi.fn(),
  destroy: vi.fn(),
})

vi.mock('../lib/config.js', () => ({
  readConfig: vi.fn(async () => ({
    token: null, email: null, userId: null,
    backendUrl: 'http://localhost:8030',
    appUrl: 'https://configured.example.com',
    defaultResumeId: null, activeModel: null, activeProvider: null,
  })),
  writeConfig: vi.fn(async () => {}),
}))

vi.mock('../lib/api-client.js', () => ({
  ApiClient: class {},
  initApiClient: vi.fn(() => ({ get: vi.fn(), post: vi.fn() })),
  getApiClient: vi.fn(() => ({ get: vi.fn(), post: vi.fn() })),
}))

vi.mock('../lib/ws-client.js', () => ({ wsClient: fakeWsClient }))

describe('App init', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('pushes readConfig().appUrl into the session store', async () => {
    const { App } = await import('../app.js')
    const { $session } = await import('../stores/session.js')
    const { unmount } = render(<App />)
    // init() is async — let the readConfig microtasks settle
    await new Promise(r => setTimeout(r, 50))
    expect($session.get().appUrl).toBe('https://configured.example.com')
    unmount()
  })
})
