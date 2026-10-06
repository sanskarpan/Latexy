import { describe, expect, it } from 'vitest'
import { runLatestRequest } from '@/lib/latest-request'

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

describe('builder import preview async ownership', () => {
  it('ignores stale success after a newer file request becomes current', async () => {
    let currentRequest = 1
    const first = deferred<string>()
    const second = deferred<string>()
    const successes: string[] = []
    const settled: string[] = []

    void runLatestRequest(
      () => first.promise,
      () => currentRequest === 1,
      (result) => successes.push(result),
      () => { throw new Error('stale request reported an error') },
      () => settled.push('first'),
    )
    currentRequest = 2
    void runLatestRequest(
      () => second.promise,
      () => currentRequest === 2,
      (result) => successes.push(result),
      () => { throw new Error('latest request reported an error') },
      () => settled.push('second'),
    )

    first.resolve('old preview')
    await Promise.resolve()
    expect(successes).toEqual([])
    expect(settled).toEqual([])

    second.resolve('new preview')
    await Promise.resolve()
    await Promise.resolve()
    expect(successes).toEqual(['new preview'])
    expect(settled).toEqual(['second'])
  })

  it('ignores stale errors after the user navigates away from preview', async () => {
    let currentRequest = 1
    const pending = deferred<string>()
    const errors: unknown[] = []
    const settled: string[] = []

    void runLatestRequest(
      () => pending.promise,
      () => currentRequest === 1,
      () => { throw new Error('stale request reported success') },
      (error) => errors.push(error),
      () => settled.push('pending'),
    )
    currentRequest = 2
    pending.reject(new Error('old request failed'))
    await Promise.resolve()
    await Promise.resolve()

    expect(errors).toEqual([])
    expect(settled).toEqual([])
  })

  it('invalidates parsing when Back, reset, or unmount is handled', async () => {
    const source = await import('node:fs').then(({ readFileSync }) =>
      readFileSync(new URL('../components/ImportFromBuilderWizard.tsx', import.meta.url), 'utf8'))
    expect(source).toContain('const invalidatePreviewRequest = useCallback')
    expect(source).toContain('previewRequestRef.current += 1')
    expect(source).toContain('onClick={() => { invalidatePreviewRequest(); setStep(2) }}')
    expect(source).toContain('useEffect(() => () => {')
  })
})
