import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { assertEmailTransportConfigured, sendEmail } from '@/lib/email'

/**
 * The transactional email sender must never quietly swallow a production
 * misconfiguration: without RESEND_API_KEY the old code logged the full
 * password-reset link to stdout and reported success, so a deploy that forgot
 * the key leaked live reset tokens while users received nothing.
 */

const RESET_EMAIL = {
  to: 'user@example.com',
  subject: 'Reset your Latexy password',
  text: 'Reset your password using this link: https://app.example.com/reset?token=secret-token',
  html: '<html><body><a href="https://app.example.com/reset?token=secret-token">Reset</a></body></html>',
  link: 'https://app.example.com/reset?token=secret-token',
}

describe('sendEmail without RESEND_API_KEY', () => {
  let info: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.stubEnv('RESEND_API_KEY', '')
    info = vi.spyOn(console, 'info').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  test('logs the action link in development instead of sending', async () => {
    vi.stubEnv('NODE_ENV', 'development')

    await sendEmail(RESET_EMAIL)

    const logged = info.mock.calls[0][0] as string
    expect(logged).toContain('RESEND_API_KEY not set')
    expect(logged).toContain(RESET_EMAIL.link)
    // The rendered bodies are never dumped — only the single action link.
    expect(logged).not.toContain('<html>')
  })

  test('throws in production instead of falling back to the console', async () => {
    vi.stubEnv('NODE_ENV', 'production')

    await expect(sendEmail(RESET_EMAIL)).rejects.toThrow(/RESEND_API_KEY is not set/)
    expect(info).not.toHaveBeenCalled()
  })

  /**
   * Better Auth invokes every sender inside `runInBackgroundOrAwait`, which
   * try/catches and only logs — so the per-send throw above never reaches the
   * user. The boot preflight is what actually stops a keyless production
   * deploy, by refusing to construct `auth` at all (see lib/auth.ts).
   */
  test('the boot preflight fails a keyless production process', () => {
    vi.stubEnv('NODE_ENV', 'production')

    expect(() => assertEmailTransportConfigured()).toThrow(/RESEND_API_KEY is not set/)
  })

  test('the boot preflight stays quiet in development and during `next build`', () => {
    vi.stubEnv('NODE_ENV', 'development')
    expect(() => assertEmailTransportConfigured()).not.toThrow()

    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PHASE', 'phase-production-build')
    expect(() => assertEmailTransportConfigured()).not.toThrow()
  })

  test('stays quiet during `next build`, which also runs as production', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    vi.stubEnv('NEXT_PHASE', 'phase-production-build')

    await expect(sendEmail(RESET_EMAIL)).resolves.toBeUndefined()
    expect(info).toHaveBeenCalled()
  })
})

describe('sendEmail with RESEND_API_KEY', () => {
  beforeEach(() => {
    vi.stubEnv('RESEND_API_KEY', 're_test_key')
    vi.stubEnv('EMAIL_FROM', 'Latexy <no-reply@example.com>')
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  test('posts the message to Resend', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 })
    vi.stubGlobal('fetch', fetchMock)

    await sendEmail(RESET_EMAIL)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('https://api.resend.com/emails')
    expect(init.headers.Authorization).toBe('Bearer re_test_key')
    expect(JSON.parse(init.body)).toMatchObject({
      from: 'Latexy <no-reply@example.com>',
      to: RESET_EMAIL.to,
      subject: RESET_EMAIL.subject,
    })
  })

  test('throws when Resend rejects the message', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422 }))

    await expect(sendEmail(RESET_EMAIL)).rejects.toThrow(/Email delivery failed/)
  })

  test('throws when Resend is unreachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')))

    await expect(sendEmail(RESET_EMAIL)).rejects.toThrow(/Email delivery failed/)
  })
})
