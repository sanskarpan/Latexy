import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const CONFIG = readFileSync(new URL('../../next.config.js', import.meta.url), 'utf8')

describe('frontend security header contract', () => {
  it('protects every Next response with a safe baseline', () => {
    expect(CONFIG).toContain('poweredByHeader: false')
    expect(CONFIG).toContain("source: '/:path*'")
    expect(CONFIG).toContain("{ key: 'X-Content-Type-Options', value: 'nosniff' }")
    expect(CONFIG).toContain("{ key: 'X-Frame-Options', value: 'DENY' }")
    expect(CONFIG).toContain("{ key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' }")
    expect(CONFIG).toContain("value: 'camera=(), microphone=(), geolocation=()'")
    expect(CONFIG).toContain("frame-ancestors 'none'; base-uri 'self'; object-src 'none'")
  })
})
