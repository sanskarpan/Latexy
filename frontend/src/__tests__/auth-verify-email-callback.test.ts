import { describe, expect, test } from 'vitest'

import { VERIFY_EMAIL_CALLBACK, withVerifyEmailCallback } from '@/lib/auth'

/**
 * GET /api/auth/verify-email spends the token and then redirects to its
 * `callbackURL` *without* it. With the callback pointed at a bare
 * `/verify-email` the landing page saw no token and rendered "Verification
 * failed" for an address that had just been verified — so the callback has to
 * carry an explicit success marker.
 */

const BASE = 'http://localhost:5180/api/auth/verify-email?token=jwt.token.value'

describe('withVerifyEmailCallback', () => {
  test('pins the callback to the verify-email success page', () => {
    const url = new URL(withVerifyEmailCallback(`${BASE}&callbackURL=%2F`))

    expect(url.searchParams.get('callbackURL')).toBe(VERIFY_EMAIL_CALLBACK)
    expect(url.searchParams.get('token')).toBe('jwt.token.value')
  })

  test('adds the callback when Better Auth did not include one', () => {
    const url = new URL(withVerifyEmailCallback(BASE))

    expect(url.searchParams.get('callbackURL')).toBe(VERIFY_EMAIL_CALLBACK)
  })

  test('the success marker survives the error suffix Better Auth appends', () => {
    // Failures redirect to `${callbackURL}&error=CODE` (the callback already
    // has a query string), which the page reads as an error — not a success.
    const landing = new URL(`${VERIFY_EMAIL_CALLBACK}&error=TOKEN_EXPIRED`, 'http://localhost:5180')

    expect(landing.searchParams.get('verified')).toBe('1')
    expect(landing.searchParams.get('error')).toBe('TOKEN_EXPIRED')
  })
})
