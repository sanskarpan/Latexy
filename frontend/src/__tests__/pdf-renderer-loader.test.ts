import { describe, expect, it, vi } from 'vitest'
import { createSharedChunkLoader } from '@/lib/pdf-renderer-loader'

describe('PDF renderer chunk loader', () => {
  it('shares one in-flight chunk request between preloading and rendering', async () => {
    let resolveModule!: (value: { renderer: string }) => void
    const load = vi.fn(() => new Promise<{ renderer: string }>((resolve) => { resolveModule = resolve }))
    const loadShared = createSharedChunkLoader(load)

    const preload = loadShared()
    const render = loadShared()
    expect(preload).toBe(render)
    await Promise.resolve()
    expect(load).toHaveBeenCalledTimes(1)

    resolveModule({ renderer: 'ready' })
    await expect(preload).resolves.toEqual({ renderer: 'ready' })
    await expect(loadShared()).resolves.toEqual({ renderer: 'ready' })
    expect(load).toHaveBeenCalledTimes(1)
  })

  it('retries after a rejected speculative chunk load', async () => {
    const load = vi.fn()
      .mockRejectedValueOnce(new Error('temporary chunk failure'))
      .mockResolvedValueOnce({ renderer: 'ready' })
    const loadShared = createSharedChunkLoader(load)

    await expect(loadShared()).rejects.toThrow('temporary chunk failure')
    await expect(loadShared()).resolves.toEqual({ renderer: 'ready' })
    expect(load).toHaveBeenCalledTimes(2)
  })
})
