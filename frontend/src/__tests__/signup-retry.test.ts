import { afterEach, describe, expect, it, vi } from 'vitest'
import type { APIRequestContext } from '@playwright/test'
import { postSignupWithRateLimitRetry } from '../../e2e/helpers/signup-retry'

const response = (status: number, retryAfter?: string) => ({
  status: () => status,
  headers: () => retryAfter === undefined ? {} : { 'retry-after': retryAfter },
}) as Awaited<ReturnType<APIRequestContext['post']>>
afterEach(() => vi.useRealTimers())

describe('bounded signup gate retry', () => {
  it('returns all non-429 statuses without retry or suppression', async () => {
    for (const status of [200, 400, 403, 500]) {
      const result = response(status)
      const post = vi.fn().mockResolvedValue(result)
      expect(await postSignupWithRateLimitRetry({ post }, '/signup', { data: {} })).toBe(result)
      expect(post).toHaveBeenCalledTimes(1)
    }
  })

  it('honors Retry-After and retries the same request exactly once', async () => {
    vi.useFakeTimers()
    const result = response(200)
    const post = vi.fn().mockResolvedValueOnce(response(429, '2')).mockResolvedValueOnce(result)
    const options = { data: { name: 'Synthetic' }, timeout: 120_000 }
    const pending = postSignupWithRateLimitRetry({ post }, '/signup', options)
    await vi.advanceTimersByTimeAsync(2999)
    expect(post).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(await pending).toBe(result)
    expect(post.mock.calls).toEqual([['/signup', options], ['/signup', options]])
  })

  it('returns a second 429 for the caller to reject, without a third attempt', async () => {
    vi.useFakeTimers()
    const denied = response(429, '0')
    const post = vi.fn().mockResolvedValue(denied)
    const pending = postSignupWithRateLimitRetry({ post }, '/signup', {})
    await vi.advanceTimersByTimeAsync(1000)
    expect(await pending).toBe(denied)
    expect(post).toHaveBeenCalledTimes(2)
  })

  it('retains the existing missing-header cap of ten seconds plus one', async () => {
    vi.useFakeTimers()
    const post = vi.fn().mockResolvedValueOnce(response(429)).mockResolvedValueOnce(response(200))
    const pending = postSignupWithRateLimitRetry({ post }, '/signup', {})
    await vi.advanceTimersByTimeAsync(10999)
    expect(post).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    await pending
    expect(post).toHaveBeenCalledTimes(2)
  })

  it.each(['NaN', '-1', '11', '', ' ', '0xA'])('rejects invalid or out-of-cap Retry-After %s', async delay => {
    const post = vi.fn().mockResolvedValue(response(429, delay))
    await expect(postSignupWithRateLimitRetry({ post }, '/signup', {})).rejects.toThrow('between 0 and 10')
    expect(post).toHaveBeenCalledTimes(1)
  })

  it('propagates transport failures without retry', async () => {
    const post = vi.fn().mockRejectedValue(new Error('network failure'))
    await expect(postSignupWithRateLimitRetry({ post }, '/signup', {})).rejects.toThrow('network failure')
    expect(post).toHaveBeenCalledTimes(1)
  })
})
