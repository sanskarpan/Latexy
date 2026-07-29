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

vi.mock('../lib/ws-client.js', () => ({ wsClient: fakeWsClient }))

describe('AppShell WS error routing', () => {
  afterEach(() => {
    fakeWsClient.removeAllListeners()
  })

  it('clears the active job and shows an error when the server rejects the subscribe', async () => {
    const { AppShell } = await import('../components/AppShell.js')
    const { createJobController } = await import('../hooks/useJobStream.js')
    const { $messages, $activeJobId, addMessage, clearMessages } = await import('../stores/messages.js')

    clearMessages()
    const { unmount } = render(<AppShell />)
    // let the router's useEffect subscribe
    await new Promise(r => setTimeout(r, 20))

    const ctrl = createJobController('job-forbidden')
    const toolMsgId = addMessage({ role: 'tool_use', content: '', jobId: 'job-forbidden' })
    ctrl.setToolMsgId(toolMsgId)
    $activeJobId.set('job-forbidden')

    // Exactly what ws_routes sends when _job_ws_access_ok fails — tagged with the job it rejected
    fakeWsClient.emit('server_error', {
      code: 'forbidden',
      message: 'Access denied for this job',
      job_id: 'job-forbidden',
    })
    await new Promise(r => setTimeout(r, 20))

    expect($activeJobId.get()).toBeNull()
    expect($messages.get().find(m => m.id === toolMsgId)?.toolState).toBe('error')
    expect($messages.get().find(m => m.role === 'error')?.content).toContain('forbidden')

    unmount()
  })
})
