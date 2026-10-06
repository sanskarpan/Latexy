import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { assertEmailTransportConfigured, clearDevEmailPreview, consumeDevEmailPreview, sendEmail } from '@/lib/email'
import { GET as getEmailPreview } from '@/app/api/dev/email-preview/route'

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
    clearDevEmailPreview()
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  test('keeps the action link out of logs and exposes a one-time dev preview', async () => {
    vi.stubEnv('NODE_ENV', 'development')

    await sendEmail(RESET_EMAIL)

    const logged = info.mock.calls[0][0] as string
    expect(logged).toContain('RESEND_API_KEY not set')
    expect(logged).not.toContain(RESET_EMAIL.link)
    expect(logged).not.toContain('<html>')
    expect(consumeDevEmailPreview()).toEqual({
      to: RESET_EMAIL.to,
      subject: RESET_EMAIL.subject,
      link: RESET_EMAIL.link,
    })
    expect(consumeDevEmailPreview()).toBeNull()
  })

  test('warns loudly and rejects a production send without a provider', async () => {
    vi.stubEnv('NODE_ENV', 'production')
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})

    // A missing provider is a delivery failure, not a successful send. Better
    // Auth may swallow this from background callbacks, but direct callers and
    // observability hooks must still receive a rejection.
    await expect(sendEmail(RESET_EMAIL)).rejects.toThrow(/Email delivery is unavailable/)
    expect(err).toHaveBeenCalledWith(expect.stringContaining('RESEND_API_KEY is not set'))
    expect(info).not.toHaveBeenCalled()
    expect(consumeDevEmailPreview()).toBeNull()
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

  test('serves the preview only to same-origin development requests', async () => {
    vi.stubEnv('NODE_ENV', 'development')
    await sendEmail(RESET_EMAIL)

    const crossOrigin = getEmailPreview(new Request('http://localhost:5180/api/dev/email-preview', {
      headers: { Origin: 'https://attacker.example' },
    }))
    expect(crossOrigin.status).toBe(403)

    const sameOrigin = getEmailPreview(new Request('http://localhost:5180/api/dev/email-preview', {
      headers: { Origin: 'http://localhost:5180' },
    }))
    expect(sameOrigin.status).toBe(200)
    await expect(sameOrigin.json()).resolves.toMatchObject({ link: RESET_EMAIL.link })
  })

  test('does not serve previews from public or rebinding hostnames', async () => {
    vi.stubEnv('NODE_ENV', 'development')
    await sendEmail(RESET_EMAIL)

    const publicHost = getEmailPreview(new Request('https://preview.example.com/api/dev/email-preview', {
      headers: { Origin: 'https://preview.example.com' },
    }))
    expect(publicHost.status).toBe(404)

    const rebindingHost = getEmailPreview(new Request('http://127.0.0.1.nip.io:5180/api/dev/email-preview', {
      headers: { Origin: 'http://127.0.0.1.nip.io:5180' },
    }))
    expect(rebindingHost.status).toBe(404)
  })

  test('does not log recipient PII or sender configuration in dev', async () => {
    vi.stubEnv('NODE_ENV', 'development')
    vi.stubEnv('EMAIL_FROM', 'Latexy <private@example.com>')
    await sendEmail(RESET_EMAIL)
    const logged = info.mock.calls[0][0] as string
    expect(logged).not.toContain(RESET_EMAIL.to)
    expect(logged).not.toContain('private@example.com')
    expect(logged).not.toContain(RESET_EMAIL.link)
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
