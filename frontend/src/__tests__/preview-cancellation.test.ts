import { afterEach, describe, expect, it, vi } from 'vitest'

describe('preview cancellation acknowledgement', () => {
  afterEach(() => { vi.resetModules(); vi.doUnmock('react'); vi.doUnmock('@/lib/preview-scheduler') })

  it('releases only the acknowledged job after its stream has been detached', async () => {
    const effects: Array<() => void> = []
    const complete = vi.fn()
    vi.doMock('react', () => ({
      useRef: (current: unknown) => ({ current }),
      useMemo: (create: () => unknown) => create(),
      useCallback: (callback: unknown) => callback,
      useEffect: (effect: () => void) => effects.push(effect),
    }))
    vi.doMock('@/lib/preview-scheduler', () => ({ PreviewScheduler: class {
      activate() {} dispose() {} update() {} complete = complete
    } }))
    const { usePreviewScheduler } = await import('@/hooks/usePreviewScheduler')
    usePreviewScheduler({ identity: 'owner', enabled: true, blocked: false,
      jobId: null, status: 'idle', cancelledJobId: 'acknowledged-job', submit: async () => null })
    effects.forEach(effect => effect())
    expect(complete).toHaveBeenCalledExactlyOnceWith('acknowledged-job')
  })
})
