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

  test('warns loudly but still completes in production without a provider', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})

    // Email must not throw here: Better Auth awaits some senders (sign-up
    // verification), and a throw would 500 the auth request. Degrade to a
    // console log + a loud warning instead.
    await expect(sendEmail(RESET_EMAIL)).resolves.toBeUndefined()
    expect(err).toHaveBeenCalledWith(expect.stringContaining('RESEND_API_KEY is not set'))
    expect(info).toHaveBeenCalled()
  })

  /**
   * Email verification is a soft, product-level decision, so a missing mail
   * provider must degrade email delivery only — it must NEVER take the auth
   * module down. The boot preflight therefore warns instead of throwing.
   */
  test('the boot preflight warns, never throws, on a keyless production process', () => {
    vi.stubEnv('NODE_ENV', 'production')
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})

    expect(() => assertEmailTransportConfigured()).not.toThrow()
    expect(err).toHaveBeenCalledWith(expect.stringContaining('RESEND_API_KEY is not set'))
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
