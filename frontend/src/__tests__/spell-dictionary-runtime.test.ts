import { beforeEach, describe, expect, it, vi } from 'vitest'

const { harness } = vi.hoisted(() => {
  type Cell = { value?: unknown; deps?: unknown[]; cleanup?: (() => void) | undefined }
  const cells: Cell[] = []
  const pendingEffects: Array<{ cell: Cell; effect: () => (() => void) | void; deps: unknown[] }> = []
  let cursor = 0
  const sameDeps = (left: unknown[] | undefined, right: unknown[]) =>
    !!left && left.length === right.length && left.every((value, index) => Object.is(value, right[index]))
  return {
    harness: {
      begin() { cursor = 0 },
      clear() { pendingEffects.splice(0); cells.splice(0); cursor = 0 },
      flushEffects() {
        const effects = pendingEffects.splice(0)
        for (const pending of effects) {
          pending.cell.cleanup?.()
          pending.cell.deps = pending.deps
          pending.cell.cleanup = pending.effect() ?? undefined
        }
      },
      unmount() {
        pendingEffects.splice(0)
        for (const cell of cells) cell.cleanup?.()
        cells.splice(0)
        cursor = 0
      },
      useRef<T>(initial: T) {
        const cell = cells[cursor++] ?? { value: { current: initial } }
        cells[cursor - 1] = cell
        return cell.value as { current: T }
      },
      useState<T>(initial: T | (() => T)) {
        const cell = cells[cursor++] ?? { value: typeof initial === 'function' ? (initial as () => T)() : initial }
        cells[cursor - 1] = cell
        return [cell.value as T, (next: T | ((value: T) => T)) => {
          cell.value = typeof next === 'function' ? (next as (value: T) => T)(cell.value as T) : next
        }] as const
      },
      useEffect(effect: () => (() => void) | void, deps: unknown[]) {
        const cell = cells[cursor++] ?? {}
        cells[cursor - 1] = cell
        if (cell.deps && sameDeps(cell.deps, deps)) return
        pendingEffects.push({ cell, effect, deps })
      },
      useCallback<T extends (...args: any[]) => any>(callback: T, deps: unknown[]) {
        const cell = cells[cursor++] ?? {}
        cells[cursor - 1] = cell
        if (cell.deps && sameDeps(cell.deps, deps)) return cell.value as T
        cell.deps = deps
        cell.value = callback
        return callback
      },
      useMemo<T>(factory: () => T, deps: unknown[]) {
        const cell = cells[cursor++] ?? {}
        cells[cursor - 1] = cell
        if (cell.deps && sameDeps(cell.deps, deps)) return cell.value as T
        cell.deps = deps
        cell.value = factory()
        return cell.value as T
      },
    },
  }
})

vi.mock('react', () => ({
  useCallback: harness.useCallback,
  useEffect: harness.useEffect,
  useMemo: harness.useMemo,
  useRef: harness.useRef,
  useState: harness.useState,
}))

const api = vi.hoisted(() => ({
  apiClient: {
    getAuthToken: vi.fn(),
    getMe: vi.fn(),
    updateMePreferences: vi.fn(),
  },
}))
vi.mock('@/lib/api-client', () => api)

import { usePersonalDictionary } from '@/hooks/useSpellCheck'

function installStorage() {
  const values = new Map<string, string>()
  vi.stubGlobal('window', {
    localStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    },
    dispatchEvent: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })
  vi.stubGlobal('localStorage', (window as unknown as { localStorage: Storage }).localStorage)
  vi.stubGlobal('CustomEvent', class { detail: unknown; constructor(_name: string, init: { detail: unknown }) { this.detail = init.detail } })
  return values
}

function useHarnessDictionary(scope: { ownerId: string | null; authToken: string | null; confirmed: boolean }) {
  harness.begin()
  const dictionary = usePersonalDictionary(scope, false)
  harness.flushEffects()
  return dictionary
}

beforeEach(() => {
  harness.clear()
  installStorage()
  vi.clearAllMocks()
  api.apiClient.getAuthToken.mockReturnValue(null)
})

describe('personal dictionary async ownership guards', () => {
  it('reads the legacy key only for anonymous scope, never for an account', () => {
    const values = installStorage()
    values.set('latexy_spell_dictionary', JSON.stringify(['legacy-word']))
    expect((window as unknown as { localStorage: Storage }).localStorage.getItem('latexy_spell_dictionary'))
      .toBe(JSON.stringify(['legacy-word']))
    const anonymous = useHarnessDictionary({ ownerId: null, authToken: null, confirmed: true })
    expect(anonymous.getWords()).toContain('legacy-word')
    harness.unmount()
    const account = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    expect(account.getWords()).not.toContain('legacy-word')
  })

  it('does not let an unmounted request write after a same-owner remount', async () => {
    let finish!: (value: { id: string; preferences: { spell_dictionary: string[] } }) => void
    api.apiClient.getMe.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const scope = { ownerId: 'user-a', authToken: 'token-a', confirmed: true }
    const first = useHarnessDictionary(scope)
    const pending = first.sync()
    harness.unmount()
    const second = useHarnessDictionary(scope)
    finish({ id: 'user-a', preferences: { spell_dictionary: ['stale-a'] } })
    await pending
    expect(second.getWords()).not.toContain('stale-a')
    expect(api.apiClient.updateMePreferences).not.toHaveBeenCalled()
  })

  it('rejects an old A completion across an A to B to A ABA transition', async () => {
    let finish!: (value: { id: string; preferences: { spell_dictionary: string[] } }) => void
    api.apiClient.getMe.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const first = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    const pending = first.sync()
    useHarnessDictionary({ ownerId: 'user-b', authToken: 'token-b', confirmed: true })
    const final = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    finish({ id: 'user-a', preferences: { spell_dictionary: ['stale-a'] } })
    await pending
    expect(final.getWords()).not.toContain('stale-a')
    expect(api.apiClient.updateMePreferences).not.toHaveBeenCalled()
  })

  it('queues the latest same-owner edit instead of sending a stale GET snapshot', async () => {
    let finish!: (value: { id: string; preferences: { spell_dictionary: string[] } }) => void
    api.apiClient.getMe.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    const pending = dictionary.sync()
    dictionary.addWord('latest')
    finish({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
    await pending
    expect(api.apiClient.updateMePreferences).toHaveBeenCalledWith(
      { spell_dictionary: ['remote', 'latest'] },
      expect.any(Object),
    )
  })

  it('keeps a removal tombstone when the GET returns the removed word', async () => {
    let finish!: (value: { id: string; preferences: { spell_dictionary: string[] } }) => void
    api.apiClient.getMe.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    const pending = dictionary.sync()
    dictionary.removeWord('remote')
    finish({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
    await pending
    expect(api.apiClient.updateMePreferences).toHaveBeenCalledWith(
      { spell_dictionary: [] },
      expect.any(Object),
    )
  })

  it('retains local words and exposes a generic error when GET fails', async () => {
    window.localStorage.setItem('latexy_spell_dictionary:account:user-a', JSON.stringify(['offline']))
    api.apiClient.getMe.mockRejectedValueOnce(new Error('network detail must stay private'))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    await dictionary.sync()
    const updated = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    expect(updated.getWords()).toContain('offline')
    expect(updated.error).toBe('Your saved dictionary could not be synchronized. Local changes remain on this device.')
  })

  it('retains local words and exposes a generic error when PATCH fails', async () => {
    window.localStorage.setItem('latexy_spell_dictionary:account:user-a', JSON.stringify(['local']))
    api.apiClient.getMe.mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
    api.apiClient.updateMePreferences.mockRejectedValueOnce(new Error('network detail must stay private'))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    await dictionary.sync()
    const updated = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    expect(updated.getWords()).toEqual(new Set(['remote', 'local']))
    expect(updated.error).toBe('Your saved dictionary could not be synchronized. Local changes remain on this device.')
  })

  it('reconciles an edit that lands while PATCH is in flight', async () => {
    let finishPatch!: (value?: unknown) => void
    api.apiClient.getMe
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
    api.apiClient.updateMePreferences
      .mockImplementationOnce(() => new Promise((resolve) => { finishPatch = resolve }))
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['latest'] } })
    window.localStorage.setItem('latexy_spell_dictionary:account:user-a', JSON.stringify(['local']))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    const pending = dictionary.sync()
    await Promise.resolve()
    await vi.waitFor(() => expect(api.apiClient.updateMePreferences).toHaveBeenCalledTimes(1))
    dictionary.addWord('latest')
    finishPatch()
    await pending
    expect(api.apiClient.updateMePreferences).toHaveBeenNthCalledWith(
      2,
      { spell_dictionary: ['remote', 'local', 'latest'] },
      expect.any(Object),
    )
  })

  it('retries when a PATCH dispatch context rejects after a local edit', async () => {
    api.apiClient.getMe
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote'] } })
    api.apiClient.updateMePreferences
      .mockImplementationOnce(async (_body, context) => {
        dictionary.addWord('latest')
        expect(context.isCurrent()).toBe(false)
        throw new Error('stale dispatch')
      })
      .mockResolvedValueOnce({ id: 'user-a', preferences: { spell_dictionary: ['remote', 'local', 'latest'] } })
    window.localStorage.setItem('latexy_spell_dictionary:account:user-a', JSON.stringify(['local']))
    const dictionary = useHarnessDictionary({ ownerId: 'user-a', authToken: 'token-a', confirmed: true })
    await dictionary.sync()
    expect(api.apiClient.updateMePreferences).toHaveBeenNthCalledWith(
      2,
      { spell_dictionary: ['remote', 'local', 'latest'] },
      expect.any(Object),
    )
  })
})
