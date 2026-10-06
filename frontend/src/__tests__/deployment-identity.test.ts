import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { GET } from '../app/api/deployment-identity/route'

const SHA = 'a'.repeat(40)

describe('deployment identity endpoint', () => {
  beforeEach(() => {
    delete process.env.VERCEL_GIT_COMMIT_SHA
    delete process.env.BUILD_VERSION
  })

  afterEach(() => {
    delete process.env.VERCEL_GIT_COMMIT_SHA
    delete process.env.BUILD_VERSION
  })

  it('returns the exact lowercase Vercel SHA', async () => {
    process.env.VERCEL_GIT_COMMIT_SHA = SHA

    const response = GET()
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ commitSha: SHA, source: 'vercel' })
  })

  it('normalizes an uppercase Vercel SHA without changing its identity', async () => {
    process.env.VERCEL_GIT_COMMIT_SHA = SHA.toUpperCase()

    const response = GET()
    expect(response.status).toBe(200)
    expect((await response.json()).commitSha).toBe(SHA)
  })

  it('fails closed when Vercel provides a malformed SHA', async () => {
    process.env.VERCEL_GIT_COMMIT_SHA = 'not-a-sha'
    process.env.BUILD_VERSION = SHA

    const response = GET()
    expect(response.status).toBe(503)
    expect(await response.json()).toEqual({ commitSha: null, source: 'unknown' })
  })

  it('uses a valid Docker/self-host SHA fallback', async () => {
    process.env.BUILD_VERSION = SHA

    const response = GET()
    expect(response.status).toBe(200)
    expect(await response.json()).toEqual({ commitSha: SHA, source: 'build' })
  })

  it('rejects absent and mutable local identities without caching', async () => {
    for (const value of [undefined, 'local']) {
      if (value === undefined) delete process.env.BUILD_VERSION
      else process.env.BUILD_VERSION = value

      const response = GET()
      expect(response.status).toBe(503)
      expect(response.headers.get('cache-control')).toBe('no-store, max-age=0')
      expect(response.headers.get('vercel-cdn-cache-control')).toBe('no-store')
    }
  })
})
