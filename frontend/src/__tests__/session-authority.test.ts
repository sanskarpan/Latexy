import { describe, expect, it } from 'vitest'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

describe('authoritative session denial', () => {
  it('recognizes only explicit numeric401 authentication denial', () => {
    expect(isConfirmedSessionUnauthorized({ status: 401, message: 'expired' })).toBe(true)
  })
  it.each([null, undefined, new Error('network'), { status: 403 }, { status: 429 }, { status: 503 },
    { status: '401' }, { statusCode: 401 }, '401', 401])('does not reinterpret %j as confirmed logout', error => {
    expect(isConfirmedSessionUnauthorized(error)).toBe(false)
  })
})
