import type { APIRequestContext } from '@playwright/test'

/** Honor only the existing local signup gate, with one bounded retry. */
export async function postSignupWithRateLimitRetry(
  request: Pick<APIRequestContext, 'post'>,
  url: string,
  options: Parameters<APIRequestContext['post']>[1],
) {
  let response = await request.post(url, options)
  if (response.status() === 429) {
    const retryAfter = response.headers()['retry-after'] ?? '10'
    const delay = /^\d+$/.test(retryAfter) ? Number(retryAfter) : Number.NaN
    if (!Number.isFinite(delay) || delay < 0 || delay > 10) {
      throw new Error('Signup Retry-After must be between 0 and 10 seconds')
    }
    await new Promise(resolve => setTimeout(resolve, (delay + 1) * 1000))
    response = await request.post(url, options)
  }
  // The caller still asserts success, including a second 429 or any other error.
  return response
}
