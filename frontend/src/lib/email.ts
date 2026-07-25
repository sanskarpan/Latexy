/**
 * Provider-agnostic transactional email sender (server-only).
 *
 * Used by Better Auth (see `src/lib/auth.ts`) for password-reset and
 * email-verification messages. Two modes:
 *
 *   1. Resend  — when `RESEND_API_KEY` is set, deliver via the Resend REST API
 *      (`https://api.resend.com/emails`) using plain `fetch` (no extra npm dep).
 *   2. Dev/no-op — when no key is configured, log the full email (including any
 *      action link) to the server console and resolve. This keeps auth flows
 *      working locally without an email provider.
 *
 * This function NEVER throws in a way that breaks auth: transport errors are
 * caught and logged, and the promise still resolves. Better Auth treats a
 * resolved `sendResetPassword`/`sendVerificationEmail` as success, so a mail
 * outage will not surface a 500 to the user mid-flow.
 */

const RESEND_ENDPOINT = 'https://api.resend.com/emails'

/** Default from-address; override with the `EMAIL_FROM` env var. */
const DEFAULT_FROM = 'Latexy <no-reply@latexy.app>'

export interface SendEmailOptions {
  to: string
  subject: string
  html: string
  /** Optional plain-text fallback. Recommended for deliverability. */
  text?: string
}

export async function sendEmail({ to, subject, html, text }: SendEmailOptions): Promise<void> {
  const apiKey = process.env.RESEND_API_KEY
  const from = process.env.EMAIL_FROM || DEFAULT_FROM

  // ── Dev / no-op mode ──────────────────────────────────────────────────────
  if (!apiKey) {
    console.info(
      [
        '',
        '📧 [email:dev] RESEND_API_KEY not set — email logged, not sent.',
        `   from:    ${from}`,
        `   to:      ${to}`,
        `   subject: ${subject}`,
        text ? `   text:    ${text}` : `   html:    ${html.replace(/\s+/g, ' ').slice(0, 500)}`,
        '',
      ].join('\n'),
    )
    return
  }

  // ── Resend mode ───────────────────────────────────────────────────────────
  try {
    const res = await fetch(RESEND_ENDPOINT, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        from,
        to,
        subject,
        html,
        ...(text ? { text } : {}),
      }),
    })

    if (!res.ok) {
      const body = await res.text().catch(() => '')
      console.error(`[email] Resend responded ${res.status}: ${body}`)
      // Do not throw — auth flow should not 500 because mail delivery failed.
      return
    }
  } catch (err) {
    console.error('[email] Failed to send via Resend:', err)
    // Swallow — never break the auth flow on a mail transport error.
  }
}
