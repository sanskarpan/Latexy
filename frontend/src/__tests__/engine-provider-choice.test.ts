import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EngineProviderOptions } from '../lib/resume-engine-types'
import { engineProviderRequest } from '../hooks/useEngineProviderChoice'

const options: EngineProviderOptions = {
  default: { provider: 'openai', model: 'default-model', source: 'platform', ready: true },
  providers: [
    { provider: 'openai', key_available: false, models: ['exact-openai'] },
    { provider: 'anthropic', key_available: true, models: ['exact-a', 'exact-b'] },
    { provider: 'openrouter', key_available: true, models: [] },
  ],
}
afterEach(() => { vi.resetModules(); vi.doUnmock('react'); vi.doUnmock('@/lib/api-client') })

describe('account-scoped engine provider choice', () => {
  it('admits only ready Automatic or connected, advertised exact models', () => {
    expect(engineProviderRequest(options, { provider: 'automatic', model: '' })).toEqual({})
    expect(engineProviderRequest({ ...options, default: { ...options.default, ready: false } }, { provider: 'automatic', model: '' })).toBeNull()
    expect(engineProviderRequest(options, { provider: 'anthropic', model: 'exact-b' })).toEqual({ provider: 'anthropic', provider_model: 'exact-b' })
    for (const choice of [{ provider: 'openai', model: 'exact-openai' }, { provider: 'openrouter', model: '' }, { provider: 'anthropic', model: '' }, { provider: 'anthropic', model: 'invented-model' }] as const) {
      expect(engineProviderRequest(options, choice)).toBeNull()
    }
  })
  it('hides old options and selection during account render and discards a late previous-account result', async () => {
    const states: unknown[] = []; const refs: Array<{ current: unknown }> = []; const effects: Array<() => (() => void)> = []
    let stateIndex = 0; let refIndex = 0; let token = 'owner-a-token'
    const setters: Array<ReturnType<typeof vi.fn>> = []
    const requests: Array<{ resolve: (value: EngineProviderOptions) => void }> = []
    vi.doMock('react', () => ({
      useCallback: (callback: unknown) => callback,
      useRef: (current: unknown) => refs[refIndex++] ?? (refs[refIndex - 1] = { current }),
      useState: (initial: unknown) => {
        const index = stateIndex++; if (!(index in states)) states[index] = initial
        setters[index] ??= vi.fn((value: unknown) => { states[index] = typeof value === 'function' ? value(states[index]) : value })
        return [states[index], setters[index]]
      },
      useEffect: (effect: () => (() => void)) => effects.push(effect),
    }))
    vi.doMock('@/lib/api-client', () => ({ apiClient: {
      getAuthToken: () => token,
      getEngineProviders: () => new Promise<EngineProviderOptions>((resolve) => requests.push({ resolve })),
    } }))
    const { useEngineProviderChoice } = await import('../hooks/useEngineProviderChoice')
    const Render = (identity: string) => { stateIndex = 0; refIndex = 0; return useEngineProviderChoice(identity) }
    Render('owner-a:resume'); effects.shift()!()
    requests[0].resolve(options); await Promise.resolve(); await Promise.resolve()
    const ownerA = Render('owner-a:resume')
    expect(ownerA.options).toEqual(options)
    ownerA.choose({ provider: 'anthropic', model: 'exact-b' })
    expect(Render('owner-a:resume').request).toEqual({ provider: 'anthropic', provider_model: 'exact-b' })
    token = 'owner-b-token'
    const ownerB = Render('owner-b:resume')
    expect(ownerB.options).toBeNull(); expect(ownerB.choice.provider).toBe('automatic'); expect(ownerB.request).toBeNull()
    expect(ownerA.accountContext?.isCurrent()).toBe(false)
    // Restore account A, start a delayed refresh, then change account before cleanup.
    token = 'owner-a-token'; Render('owner-a:resume'); effects.pop()!()
    const delayed = requests[1]
    token = 'owner-b-token'; Render('owner-b:resume')
    const snapshotWrites = setters[0].mock.calls.length
    delayed.resolve(options); await Promise.resolve(); await Promise.resolve()
    expect(setters[0].mock.calls.length).toBe(snapshotWrites)
    expect(Render('owner-b:resume').options).toBeNull()
  })
})
