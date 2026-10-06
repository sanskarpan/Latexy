import { afterEach, describe, expect, it, vi } from 'vitest'
import { createAutoCompileScheduler } from '@/lib/auto-compile-scheduler'

afterEach(() => {
  vi.useRealTimers()
})

describe('auto-compile scheduler', () => {
  it('waits for five seconds of quiet and dispatches once', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.notifyContent('alpha')
    vi.advanceTimersByTime(4_999)
    expect(dispatched).toEqual([])
    vi.advanceTimersByTime(1)
    expect(dispatched).toEqual(['alpha'])
    scheduler.notifyContent('alpha')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual(['alpha'])
    scheduler.dispose()
  })

  it('retains the newest content while busy and respects the ten-second cadence', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.notifyContent('first')
    vi.advanceTimersByTime(5_000)
    scheduler.setBusy(true)
    scheduler.notifyContent('second')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual(['first'])
    scheduler.setBusy(false)
    expect(dispatched).toEqual(['first'])
    vi.advanceTimersByTime(5_000)
    expect(dispatched).toEqual(['first', 'second'])
    scheduler.dispose()
  })

  it('does not dispatch a quiet edit before the minimum automatic cadence', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.notifyContent('first')
    vi.advanceTimersByTime(5_000)
    scheduler.notifyContent('second')
    vi.advanceTimersByTime(5_000)
    expect(dispatched).toEqual(['first'])
    vi.advanceTimersByTime(5_000)
    expect(dispatched).toEqual(['first', 'second'])
    scheduler.dispose()
  })

  it('clears matching manual compiles and resets stale document state', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.notifyContent('manual')
    scheduler.markCompiled('manual')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual([])

    scheduler.notifyContent('old-document')
    scheduler.setDocument('resume-b')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual([])
    scheduler.notifyContent('new-document')
    vi.advanceTimersByTime(5_000)
    expect(dispatched).toEqual(['new-document'])
    scheduler.dispose()
  })

  it('stops dispatches when disabled and resumes with the latest edit when enabled', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.setEnabled(false)
    scheduler.notifyContent('queued')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual([])
    scheduler.setEnabled(true)
    vi.advanceTimersByTime(4_999)
    expect(dispatched).toEqual([])
    vi.advanceTimersByTime(1)
    expect(dispatched).toEqual(['queued'])
    scheduler.dispose()
  })

  it('holds the dispatch lock while an async compile is pending and then releases the latest edit', async () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    let finish!: () => void
    const scheduler = createAutoCompileScheduler({
      onDispatch: content => {
        dispatched.push(content)
        return new Promise<void>(resolve => { finish = resolve })
      },
    })

    scheduler.notifyContent('first')
    vi.advanceTimersByTime(5_000)
    scheduler.notifyContent('second')
    vi.advanceTimersByTime(20_000)
    expect(dispatched).toEqual(['first'])

    finish()
    await Promise.resolve()
    await Promise.resolve()
    vi.runOnlyPendingTimers()
    expect(dispatched).toEqual(['first', 'second'])
    scheduler.dispose()
  })

  it('contains rejected or thrown dispatches without an immediate retry loop', async () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    let reject!: (reason?: unknown) => void
    const scheduler = createAutoCompileScheduler({
      onDispatch: content => {
        dispatched.push(content)
        if (content === 'first') return new Promise<void>((_, fail) => { reject = fail })
        throw new Error('synthetic dispatch failure')
      },
    })

    scheduler.notifyContent('first')
    vi.advanceTimersByTime(5_000)
    scheduler.notifyContent('second')
    reject(new Error('synthetic async failure'))
    await Promise.resolve()
    await Promise.resolve()
    expect(dispatched).toEqual(['first'])
    vi.advanceTimersByTime(9_999)
    expect(dispatched).toEqual(['first'])
    vi.advanceTimersByTime(1)
    expect(dispatched).toEqual(['first', 'second'])
    scheduler.dispose()
  })

  it('does not dispatch after disposal, including when an in-flight promise settles', async () => {
    vi.useFakeTimers()
    let finish!: () => void
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({
      onDispatch: content => {
        dispatched.push(content)
        return new Promise<void>(resolve => { finish = resolve })
      },
    })

    scheduler.notifyContent('first')
    vi.advanceTimersByTime(5_000)
    scheduler.notifyContent('second')
    scheduler.dispose()
    finish()
    await Promise.resolve()
    await Promise.resolve()
    vi.runAllTimers()
    expect(dispatched).toEqual(['first'])
  })

  it('invalidates an unsettled dispatch when switching documents', async () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const finishers: Array<() => void> = []
    const scheduler = createAutoCompileScheduler({
      onDispatch: content => {
        dispatched.push(content)
        return new Promise<void>(resolve => { finishers.push(resolve) })
      },
    })

    scheduler.setDocument('document-a')
    scheduler.notifyContent('a-1')
    vi.advanceTimersByTime(5_000)
    scheduler.setDocument('document-b')
    scheduler.notifyContent('b-1')
    vi.advanceTimersByTime(5_000)
    scheduler.setDocument('document-a')
    scheduler.notifyContent('a-2')
    vi.advanceTimersByTime(5_000)
    expect(dispatched).toEqual(['a-1', 'b-1', 'a-2'])

    finishers.forEach(finish => finish())
    await Promise.resolve()
    await Promise.resolve()
    expect(dispatched).toEqual(['a-1', 'b-1', 'a-2'])
    scheduler.dispose()
  })

  it('cancels an emptied buffer and bounds slow or rapid typing', () => {
    vi.useFakeTimers()
    const dispatched: string[] = []
    const scheduler = createAutoCompileScheduler({ onDispatch: content => { dispatched.push(content) } })

    scheduler.notifyContent('temporary')
    scheduler.notifyContent('')
    vi.advanceTimersByTime(30_000)
    expect(dispatched).toEqual([])

    for (let index = 0; index < 60; index += 1) {
      scheduler.notifyContent(`slow-${index}`)
      vi.advanceTimersByTime(1_000)
    }
    vi.advanceTimersByTime(60_000)
    expect(dispatched.length).toBeLessThanOrEqual(6)

    scheduler.setDocument('rapid-document')
    for (let index = 0; index < 60; index += 1) {
      scheduler.notifyContent(`rapid-${index}`)
      vi.advanceTimersByTime(50)
    }
    vi.advanceTimersByTime(5_000)
    expect(dispatched[dispatched.length - 1]).toBe('rapid-59')
    expect(dispatched.filter(content => content.startsWith('rapid-'))).toHaveLength(1)
    scheduler.dispose()
  })
})
