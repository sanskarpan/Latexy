import type { Pool } from 'pg'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import {
  DEFAULT_RULE,
  authPathFromUrl,
  clientIp,
  enforceAuthRateLimit,
  resolveRule,
} from '@/lib/auth-rate-limit'

/**
 * Regression cover for the two ways the previous Postgres-backed rate-limit
 * store was broken:
 *
 * 1. It read the counter, added one in JS, and wrote back an absolute value —
 *    so concurrent writers overwrote each other and 60 concurrent password
 *    resets left the counter at 1. The gate must instead let Postgres do the
 *    increment, in one statement, and decide on the value it returns.
 * 2. Storage errors propagated out of `auth.handler`, 500-ing every auth route
 *    (get-session and sign-out included) on a DB blip. The gate must fail open.
 */

/** Minimal Pool stand-in whose counter behaves like the real atomic upsert. */
function countingPool(): Pool & { calls: number } {
  let count = 0
  const pool = {
    calls: 0,
    async query(sql: string, params: unknown[]) {
      // The periodic pruning sweep also runs through the pool; only the
      // counter upsert is interesting here.
      if (!sql.includes('INSERT')) return { rows: [] }
      pool.calls += 1
      count += 1
      return { rows: [{ count, last_request: String(params[1]) }] }
    },
  }
  return pool as unknown as Pool & { calls: number }
}

/** Requests as the trusted ingress presents them: X-Real-IP from $remote_addr. */
function post(path: string, ip = '203.0.113.7'): Request {
  return new Request(`http://localhost:5180/api/auth${path}`, {
    method: 'POST',
    headers: { 'x-real-ip': ip },
  })
}

// The gate only believes forwarding headers behind a trusted proxy, which is
// how every manifest ships it; exercise that configuration by default.
beforeEach(() => {
  process.env.TRUST_PROXY_HEADERS = 'true'
})

afterEach(() => {
  delete process.env.TRUST_PROXY_HEADERS
})

describe('rule resolution', () => {
  test('mail-sending endpoints get the tight five-per-hour budget', () => {
    for (const path of [
      '/request-password-reset',
      '/forget-password',
      '/send-verification-email',
    ]) {
      expect(resolveRule(path)).toEqual({ window: 3600, max: 5 })
    }
  })

  test('credential endpoints keep Better Auth’s stricter 3-per-10s rule', () => {
    expect(resolveRule('/sign-in/email')).toEqual({ window: 10, max: 3 })
    expect(resolveRule('/sign-up/email')).toEqual({ window: 10, max: 3 })
  })

  test('everything else falls back to the default rule', () => {
    expect(resolveRule('/get-session')).toEqual(DEFAULT_RULE)
  })

  test('a longer path is not matched by an unrelated prefix', () => {
    expect(resolveRule('/sign-in-with-magic')).toEqual(DEFAULT_RULE)
  })
})

describe('request keying', () => {
  test('strips the Better Auth base path', () => {
    expect(authPathFromUrl('http://x/api/auth/sign-in/email?a=1')).toBe('/sign-in/email')
    expect(authPathFromUrl('http://x/api/auth')).toBe('/')
  })

  test('prefers x-real-ip, which nginx overwrites with $remote_addr', () => {
    expect(clientIp(new Headers({ 'x-real-ip': '5.6.7.8', 'x-forwarded-for': '1.2.3.4' }))).toBe(
      '5.6.7.8',
    )
    expect(clientIp(new Headers())).toBe('unknown')
  })

  test('takes the LAST x-forwarded-for hop — the one the proxy appended', () => {
    // $proxy_add_x_forwarded_for appends the real peer to whatever the client
    // sent, so the leading hops are attacker-controlled.
    expect(clientIp(new Headers({ 'x-forwarded-for': '1.2.3.4, 203.0.113.9' }))).toBe('203.0.113.9')
  })

  test('a rotated x-forwarded-for cannot mint a fresh bucket without a trusted proxy', () => {
    delete process.env.TRUST_PROXY_HEADERS
    const keys = ['198.51.100.31', '198.51.100.32', '198.51.100.33'].map((ip) =>
      clientIp(new Headers({ 'x-forwarded-for': ip })),
    )
    expect(new Set(keys).size).toBe(1)
  })

  test('a rotated leading hop shares the trusted proxy’s bucket', () => {
    const keys = ['198.51.100.31', '198.51.100.32', '198.51.100.33'].map((ip) =>
      clientIp(new Headers({ 'x-forwarded-for': `${ip}, 203.0.113.9` })),
    )
    expect(new Set(keys)).toEqual(new Set(['203.0.113.9']))
  })
})

describe('enforceAuthRateLimit', () => {
  test('blocks past the limit and never trusts a client-side count', async () => {
    const pool = countingPool()
    const statuses: (number | null)[] = []
    // Fire them all at once: the gate must not depend on a read that finished
    // before the burst started.
    await Promise.all(
      Array.from({ length: 60 }, async () => {
        const res = await enforceAuthRateLimit(pool, post('/request-password-reset'))
        statuses.push(res ? res.status : null)
      }),
    )

    expect(statuses.filter((s) => s === null)).toHaveLength(5)
    expect(statuses.filter((s) => s === 429)).toHaveLength(55)
    // One statement per request — no separate read-then-write.
    expect(pool.calls).toBe(60)
  })

  test('the 429 carries a retry hint', async () => {
    const pool = countingPool()
    let last: Response | null = null
    for (let i = 0; i < 6; i += 1) {
      last = await enforceAuthRateLimit(pool, post('/request-password-reset'))
    }
    expect(last?.status).toBe(429)
    expect(Number(last?.headers.get('X-Retry-After'))).toBeGreaterThan(0)
    expect(Number(last?.headers.get('Retry-After'))).toBeGreaterThan(0)
  })

  test('increments a single row via one upsert, not a read-modify-write', async () => {
    const pool = countingPool()
    const spy = vi.spyOn(pool, 'query')
    await enforceAuthRateLimit(pool, post('/sign-in/email'))

    const sql = String(spy.mock.calls[0][0])
    expect(sql).toContain('ON CONFLICT (key) DO UPDATE')
    expect(sql).toContain('auth_rate_limit.count + 1')
    expect(sql).toContain('RETURNING')
    expect(spy.mock.calls[0][1]).toEqual(['203.0.113.7|/sign-in/email', expect.any(Number), 10_000])
  })

  test('separate IPs and paths get separate budgets', async () => {
    const pool = countingPool()
    const spy = vi.spyOn(pool, 'query')
    await enforceAuthRateLimit(pool, post('/sign-in/email', '1.1.1.1'))
    await enforceAuthRateLimit(pool, post('/get-session', '2.2.2.2'))

    expect(spy.mock.calls[0][1]?.[0]).toBe('1.1.1.1|/sign-in/email')
    expect(spy.mock.calls[1][1]?.[0]).toBe('2.2.2.2|/get-session')
  })

  test('fails open when the counter store is down instead of 500-ing auth', async () => {
    const pool = {
      query: vi.fn().mockRejectedValue(new Error('simulated DB outage')),
    } as unknown as Pool
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})

    await expect(enforceAuthRateLimit(pool, post('/get-session'))).resolves.toBeNull()
    expect(err).toHaveBeenCalled()
    err.mockRestore()
  })
})
