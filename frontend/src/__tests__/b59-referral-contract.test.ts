import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8')

describe('B59 referral contract', () => {
  it('captures only bounded opaque tokens in a first-party cookie', () => {
    const source = read('../components/ReferralCapture.tsx')
    expect(source).toContain('SameSite=Lax')
    expect(source).toContain('CODE_RE')
    expect(source).toContain('REFERRAL_COOKIE_MAX_AGE')
    expect(source).toContain('7 * 24 * 60 * 60')
  })

  it('claims after the server-authenticated session, including OAuth', () => {
    const source = read('../components/AuthSync.tsx')
    expect(source).toContain("fetch('/api/referral'")
    expect(source).toContain('credentials: \'include\'')
    expect(source).toContain('token && referralClaimedFor.current !== token')
  })

  it('does not promise affiliate cash or a hardcoded reward', () => {
    const source = read('../components/ReferralPanel.tsx')
    expect(source).toContain('not an affiliate or cash-commission programme')
    expect(source).not.toMatch(/\$10|₹\s*\d/)
  })
})
