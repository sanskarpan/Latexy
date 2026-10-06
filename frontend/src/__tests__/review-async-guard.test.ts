import { describe, expect, it } from 'vitest'
import { reviewRequestIsCurrent } from '@/lib/review-async-guard'

describe('review async identity guard', () => {
  it('ignores an old request that resolves after the panel switches identity', async () => {
    let resolveOld!: (value: string) => void
    const oldRequest = new Promise<string>((resolve) => { resolveOld = resolve })
    let currentGeneration = 1
    const applied: string[] = []
    const oldCompletion = oldRequest.then((value) => {
      if (reviewRequestIsCurrent(1, currentGeneration)) applied.push(value)
    })

    currentGeneration = 2
    resolveOld('old capability error')
    await oldCompletion
    expect(applied).toEqual([])

    const newRequest = Promise.resolve('new capability result')
    await newRequest.then((value) => {
      if (reviewRequestIsCurrent(2, currentGeneration)) applied.push(value)
    })
    expect(applied).toEqual(['new capability result'])
  })
})
