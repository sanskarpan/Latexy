import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadBlob, pollJobCompletion } from '../lib/download'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('downloadBlob', () => {
  it('waits before revoking the object URL so the browser can consume it', () => {
    vi.useFakeTimers()
    const click = vi.fn()
    const remove = vi.fn()
    const appendChild = vi.fn()
    const anchor = { href: '', download: '', click, remove }
    const createObjectURL = vi.fn(() => 'blob:download')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    vi.stubGlobal('document', {
      createElement: vi.fn(() => anchor),
      body: { appendChild },
    })

    downloadBlob(new Blob(['content']), 'resume.pdf')

    expect(anchor).toMatchObject({ href: 'blob:download', download: 'resume.pdf' })
    expect(appendChild).toHaveBeenCalledWith(anchor)
    expect(click).toHaveBeenCalledOnce()
    expect(remove).toHaveBeenCalledOnce()
    expect(revokeObjectURL).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1000)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:download')
  })
})

describe('pollJobCompletion', () => {
  const tick = (ms: number) => new Promise<void>((resolve) => { setTimeout(resolve, ms) })

  it('returns completed as soon as the job finishes', async () => {
    const getJobState = vi.fn()
      .mockResolvedValueOnce({ status: 'processing' })
      .mockResolvedValueOnce({ status: 'completed' })
    const result = await pollJobCompletion(getJobState, 'job-1', { intervalMs: 1, wait: tick })
    expect(result).toBe('completed')
    expect(getJobState).toHaveBeenCalledTimes(2)
  })

  it('propagates failed and cancelled terminals without further polling', async () => {
    for (const terminal of ['failed', 'cancelled'] as const) {
      const getJobState = vi.fn().mockResolvedValue({ status: terminal })
      const result = await pollJobCompletion(getJobState, 'job-1', { intervalMs: 1, wait: tick })
      expect(result).toBe(terminal)
      expect(getJobState).toHaveBeenCalledTimes(1)
    }
  })

  it('treats transport errors as retries until the deadline', async () => {
    const getJobState = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ status: 'processing' })
      .mockResolvedValueOnce({ status: 'completed' })
    const result = await pollJobCompletion(getJobState, 'job-1', { intervalMs: 1, maxWaitMs: 50, wait: tick })
    expect(result).toBe('completed')
    expect(getJobState).toHaveBeenCalledTimes(3)
  })

  it('times out instead of polling forever', async () => {
    const getJobState = vi.fn().mockResolvedValue({ status: 'processing' })
    const result = await pollJobCompletion(getJobState, 'job-1', { intervalMs: 1, maxWaitMs: 5, wait: tick })
    expect(result).toBe('timeout')
    expect(getJobState.mock.calls.length).toBeGreaterThan(0)
  })

  it('stops immediately when deactivated', async () => {
    let active = true
    const getJobState = vi.fn().mockResolvedValue({ status: 'processing' })
    const pending = pollJobCompletion(getJobState, 'job-1', { intervalMs: 50, wait: tick, isActive: () => active })
    active = false
    await expect(pending).resolves.toBe('inactive')
  })
})
