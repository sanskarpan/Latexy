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
    await advance(4999)
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
    scheduler.update(true, false); scheduler.request('A'); await advance(5000)
    scheduler.request('B'); scheduler.request('C'); await advance(1000)
    expect(submit).toHaveBeenCalledTimes(1)
    acknowledge('job-1'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('unrelated'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('job-1'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    await advance(8999)
    expect(submit).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(submit.mock.calls.map((call) => call[0])).toEqual(['A', 'C'])
    scheduler.dispose()
  })

  it('handles completion arriving before the submission response', async () => {
    let acknowledge!: (job: string) => void
    const submit = vi.fn().mockImplementationOnce(() => new Promise<string>((resolve) => { acknowledge = resolve }))
      .mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A', now, true); await advance(0)
    scheduler.request('B', now, true); await advance(0)
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
    scheduler.update(true, false); scheduler.request('C'); await advance(5000)
    expect(submit).toHaveBeenCalledExactlyOnceWith('C', 2000)
    scheduler.dispose()
  })

  it('rebuilds an unchanged draft only after an explicit candidate decision', async () => {
    const submit = vi.fn().mockResolvedValueOnce('job-1').mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(5000)
    scheduler.complete('job-1'); scheduler.request('A'); await advance(500)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.request('A', now, true); await advance(0)
    expect(submit).toHaveBeenCalledTimes(2)
    scheduler.dispose()
  })
  it('does not repeat a failed or ambiguous paid admission for unchanged content', async () => {
    const submit = vi.fn().mockRejectedValue(new Error('acknowledgement lost'))
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(5000)
    scheduler.request('A'); await advance(1000)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.dispose()
  })

  it('does not admit each slow keystroke and waits five seconds after typing stops', async () => {
    const submit = vi.fn(async () => 'job')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false)
    for (let length = 1; length <= 60; length++) {
      scheduler.request('x'.repeat(length))
      await advance(700)
      expect(submit).not.toHaveBeenCalled()
    }
    await advance(4299)
    expect(submit).not.toHaveBeenCalled()
    await advance(1)
    expect(submit).toHaveBeenCalledExactlyOnceWith('x'.repeat(60), 41300)
    scheduler.dispose()
  })

  it('enforces ten seconds between automatic admissions even after a fast render', async () => {
    const submit = vi.fn().mockResolvedValueOnce('job-1').mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(5000)
    scheduler.complete('job-1'); scheduler.request('B'); await advance(5000)
    expect(submit).toHaveBeenCalledTimes(1)
    await advance(4999)
    expect(submit).toHaveBeenCalledTimes(1)
    await advance(1)
    expect(submit.mock.calls.map((call) => call[0])).toEqual(['A', 'B'])
    scheduler.dispose()
  })

  it('renders an explicitly saved field promptly without bypassing the running-job fence', async () => {
    const submit = vi.fn().mockResolvedValueOnce('job-1').mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A', now, true); await advance(0)
    scheduler.request('B', now, true); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('job-1'); await advance(0)
    expect(submit.mock.calls.map((call) => call[0])).toEqual(['A', 'B'])
    scheduler.dispose()
  })

  it('queues an explicit unchanged accepted decision behind an already running preview', async () => {
    const submit = vi.fn().mockResolvedValueOnce('job-1').mockResolvedValueOnce('job-2')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A', now, true); await advance(0)
    scheduler.request('A', now, true); await advance(0)
    expect(submit).toHaveBeenCalledTimes(1)
    scheduler.complete('job-1'); await advance(0)
    expect(submit).toHaveBeenCalledTimes(2)
    scheduler.dispose()
  })

  it('clears a queued old source when the buffer becomes empty', async () => {
    const submit = vi.fn(async () => 'job')
    const scheduler = new PreviewScheduler(submit, () => now)
    scheduler.update(true, false); scheduler.request('A'); await advance(1000)
    scheduler.request(''); await advance(10000)
    expect(submit).not.toHaveBeenCalled()
    scheduler.dispose()
  })
})

describe('manual previews share the scheduler admission fence', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  function harness() {
    const automatic = vi.fn().mockResolvedValue('automatic-job')
    const scheduler = new PreviewScheduler(automatic, () => Date.now())
    scheduler.update(true, false)
    let resolve!: (job: string | null) => void
    let reject!: (error: Error) => void
    const manual = vi.fn(() => new Promise<string | null>((yes, no) => { resolve = yes; reject = no }))
    return { scheduler, automatic, manual, resolve: (job: string | null) => resolve(job), reject: () => reject(new Error('ACK lost')) }
  }

  it('adopts a queued identical source and never submits it again after terminal', async () => {
    const h = harness()
    h.scheduler.request('A')
    const pending = h.scheduler.submitManual('A', h.manual)
    await vi.advanceTimersByTimeAsync(20_000)
    expect(h.manual).toHaveBeenCalledOnce()
    expect(h.automatic).not.toHaveBeenCalled()
    h.resolve('manual-job'); await pending
    h.scheduler.complete('manual-job')
    h.scheduler.request('A')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(h.automatic).not.toHaveBeenCalled()
    h.scheduler.dispose()
  })

  it('preserves only the latest edit made during manual admission and rendering', async () => {
    const h = harness()
    h.scheduler.request('A')
    const pending = h.scheduler.submitManual('A', h.manual)
    h.scheduler.request('B')
    h.resolve('manual-job'); await pending
    h.scheduler.request('C')
    await vi.advanceTimersByTimeAsync(20_000)
    expect(h.automatic).not.toHaveBeenCalled()
    h.scheduler.complete('manual-job')
    await vi.advanceTimersByTimeAsync(0)
    expect(h.automatic).toHaveBeenCalledExactlyOnceWith('C', expect.any(Number))
    h.scheduler.dispose()
  })

  it('discards a pre-manual notification superseded by the latest captured buffer', async () => {
    const h = harness()
    h.scheduler.request('older')
    const pending = h.scheduler.submitManual('newer', h.manual)
    h.resolve('manual-job'); await pending
    h.scheduler.complete('manual-job')
    await vi.advanceTimersByTimeAsync(10_000)
    expect(h.automatic).not.toHaveBeenCalled()
    h.scheduler.dispose()
  })

  it('reserves synchronously against repeated manual clicks and an already due auto timer', async () => {
    const h = harness()
    h.scheduler.request('A', undefined, true)
    const pending = h.scheduler.submitManual('A', h.manual)
    await h.scheduler.submitManual('A', h.manual)
    await vi.advanceTimersByTimeAsync(0)
    expect(h.manual).toHaveBeenCalledOnce()
    expect(h.automatic).not.toHaveBeenCalled()
    h.resolve('manual-job'); await pending
    await h.scheduler.submitManual('A', h.manual)
    expect(h.manual).toHaveBeenCalledOnce()
    h.scheduler.dispose()
  })

  it('does not admit a manual click when the automatic admission wins the race', async () => {
    let resolve!: (job: string) => void
    const automatic = vi.fn(() => new Promise<string>(yes => { resolve = yes }))
    const manual = vi.fn().mockResolvedValue('manual-job')
    const scheduler = new PreviewScheduler(automatic, () => Date.now())
    scheduler.update(true, false); scheduler.request('A', undefined, true)
    await vi.advanceTimersByTimeAsync(0)
    await scheduler.submitManual('A', manual)
    expect(automatic).toHaveBeenCalledOnce()
    expect(manual).not.toHaveBeenCalled()
    resolve('automatic-job'); await vi.advanceTimersByTimeAsync(0)
    await scheduler.submitManual('A', manual)
    expect(manual).not.toHaveBeenCalled()
    scheduler.dispose()
  })

  for (const outcome of ['failure', 'ambiguous'] as const) {
    it(`does not automatically repeat a ${outcome} manual admission, but permits an explicit retry`, async () => {
      const h = harness()
      h.scheduler.request('A', undefined, true)
      const pending = h.scheduler.submitManual('A', h.manual)
      if (outcome === 'failure') h.resolve(null)
      else h.reject()
      await pending
      h.scheduler.request('A')
      await vi.advanceTimersByTimeAsync(20_000)
      expect(h.automatic).not.toHaveBeenCalled()
      const retry = h.scheduler.submitManual('A', h.manual)
      expect(h.manual).toHaveBeenCalledTimes(2)
      h.resolve('retry-job'); await retry
      h.scheduler.dispose()
    })
  }

  it('allows manual previews when automatic previews are disabled', async () => {
    const h = harness()
    h.scheduler.update(false, false)
    const pending = h.scheduler.submitManual('A', h.manual)
    expect(h.manual).toHaveBeenCalledOnce()
    h.resolve('manual-job'); await pending
    h.scheduler.dispose()
  })

  it('respects a busy external job and disposal before any manual side effect', async () => {
    const h = harness()
    h.scheduler.update(true, true)
    await h.scheduler.submitManual('A', h.manual)
    h.scheduler.update(true, false); h.scheduler.dispose()
    await h.scheduler.submitManual('A', h.manual)
    expect(h.manual).not.toHaveBeenCalled()
  })

  for (const beforeAck of [false, true]) {
    it(`releases an acknowledged terminal/cancellation ${beforeAck ? 'before' : 'after'} the manual ACK`, async () => {
      const h = harness()
      const pending = h.scheduler.submitManual('A', h.manual)
      h.scheduler.request('B', undefined, true)
      h.scheduler.complete('unrelated-job')
      await vi.advanceTimersByTimeAsync(0)
      expect(h.automatic).not.toHaveBeenCalled()
      if (beforeAck) h.scheduler.complete('manual-job')
      h.resolve('manual-job'); await pending
      if (!beforeAck) h.scheduler.complete('manual-job')
      await vi.advanceTimersByTimeAsync(0)
      expect(h.automatic).toHaveBeenCalledExactlyOnceWith('B', expect.any(Number))
      h.scheduler.dispose()
    })
  }

  it('preserves explicit accepted-edit behavior for unchanged source after manual admission', async () => {
    const h = harness()
    const pending = h.scheduler.submitManual('A', h.manual)
    h.scheduler.request('A', undefined, true)
    h.resolve('manual-job'); await pending
    h.scheduler.complete('manual-job')
    await vi.advanceTimersByTimeAsync(0)
    expect(h.automatic).toHaveBeenCalledExactlyOnceWith('A', expect.any(Number))
    h.scheduler.dispose()
  })
})
