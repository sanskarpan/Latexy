import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PreviewScheduler } from '@/lib/preview-scheduler'

describe('revision preview scheduling', () => {
  let now: number
  const advance = async (ms: number) => { now += ms; await vi.advanceTimersByTimeAsync(ms) }
  beforeEach(() => { now = 0; vi.useFakeTimers() })
  afterEach(() => vi.useRealTimers())

  it('debounces rapid typing and admits only the latest revision', async () => {
    const submit = vi.fn(async () => 'job-1')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false)
    scheduler.request('revision A')
    await advance(100)
    scheduler.request('revision B')
    await advance(199)
    expect(submit).not.toHaveBeenCalled()
    await advance(1)
    expect(submit).toHaveBeenCalledExactlyOnceWith('revision B', 100)
    scheduler.dispose()
  })

  it('holds one render across admission ACK and replaces pending edits', async () => {
    let acknowledge!: (job: string) => void
    const submit = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { acknowledge = resolve }))
      .mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(200)
    scheduler.request('B'); scheduler.request('C'); await advance(1000)
    expect(submit).toHaveBeenCalledTimes(1)
    acknowledge('job-1'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('unrelated'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('job-1'); await advance(0)
    expect(submit.mock.calls.map((call) => call[0])).toEqual(['A', 'C'])
    scheduler.dispose()
  })

  it('handles completion arriving before the submission response', async () => {
    let acknowledge!: (job: string) => void
    const submit = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { acknowledge = resolve }))
      .mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(200)
    scheduler.request('B'); await advance(200)
    scheduler.complete('job-1'); acknowledge('job-1'); await advance(0)
    expect(submit.mock.calls.map((call) => call[0])).toEqual(['A', 'B'])
    scheduler.dispose()
  })

  it('retains newest edits while another durable job runs and clears disabled previews', async () => {
    const submit = vi.fn(async () => 'job')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, true); scheduler.request('A'); scheduler.request('B'); await advance(1000)
    expect(submit).not.toHaveBeenCalled()
    scheduler.update(false, false); await advance(1000)
    expect(submit).not.toHaveBeenCalled()
    scheduler.update(true, false); scheduler.request('C'); await advance(200)
    expect(submit).toHaveBeenCalledExactlyOnceWith('C', 2000)
    scheduler.dispose()
  })

  it('rebuilds an unchanged draft only after an explicit candidate decision', async () => {
    const submit = vi.fn().mockResolvedValueOnce('job-1').mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(200)
    scheduler.complete('job-1'); scheduler.request('A'); await advance(500)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.request('A', now, true); await advance(250)
    expect(submit).toHaveBeenCalledTimes(2)
    scheduler.dispose()
  })
  it('does not repeat a failed or ambiguous paid admission for unchanged content', async () => {
    const submit = vi.fn().mockRejectedValue(new Error('acknowledgement lost'))
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(200)
    scheduler.request('A'); await advance(1000)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.dispose()
  })
})
