/**
 * Provider-agnostic transactional email sender (server-only).
 *
 * Used by Better Auth (see `src/lib/auth.ts`) for password-reset and
 * email-verification messages. Two modes:
 *
 *   1. Resend  — when `RESEND_API_KEY` is set, deliver via the Resend REST API
 *      (`https://api.resend.com/emails`) using plain `fetch` (no extra npm dep).
 *   2. Dev console — ONLY outside production. The email is summarised to the
 *      server console (including the action link, so local reset/verification
 *      flows stay testable without a provider) and not sent.
 *
 * The dev fallback is deliberately unreachable in production: a missing
 * `RESEND_API_KEY` there is a deploy-time misconfiguration. The previous
 * behaviour — falling back to console logging — wrote live password-reset
 * tokens to production stdout while the UI told the user the link was "on its
 * way". `assertEmailTransportConfigured()` below turns that into a boot-time
 * failure (see `lib/auth.ts`), so the container never starts serving traffic
 * it cannot send mail for, rather than discovering it on the first reset.
 *
 * Delivery failures throw, but NOTE what that does and does not buy: every
 * sender is invoked through Better Auth's `ctx.runInBackgroundOrAwait`, which
 * try/catches and only logs ("Failed to run background task"). The endpoint
 * still answers 200 and the UI still says the link is on its way. The throw is
 * therefore an abort-and-log signal for operators — it stops the send being
 * silently counted as success and keeps the failure out of the happy path — not
 * a user-visible error. Do not build UX on top of it.
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
  /**
   * The single action link contained in the message. Printed verbatim by the
   * dev console fallback so local flows can be completed; the rendered bodies
   * are never logged.
   */
  link?: string
}

/**
 * True when this process is actually serving production traffic. `next build`
 * also runs with NODE_ENV=production but must not require runtime secrets, so
 * the build phase is excluded (mirrors `getAuthSecret` in lib/auth.ts).
 */
function isProductionRuntime(): boolean {
  return process.env.NODE_ENV === 'production' && process.env.NEXT_PHASE !== 'phase-production-build'
}

const MISSING_KEY_MESSAGE =
  'RESEND_API_KEY is not set — refusing to fall back to console logging in production. ' +
  'Configure a transactional email provider before serving traffic.'

/**
 * Boot-time preflight: fail the process when production has no mail transport.
 *
 * Throwing from `sendEmail` alone is not enough — Better Auth runs every sender
 * inside `runInBackgroundOrAwait`, which swallows the error — so a container
 * missing `RESEND_API_KEY` would otherwise happily serve sign-ups whose
 * verification mail can never be delivered. Called from `lib/auth.ts` at module
 * load, alongside the `BETTER_AUTH_SECRET` check.
 */
export function assertEmailTransportConfigured(): void {
  if (!process.env.RESEND_API_KEY && isProductionRuntime()) {
    throw new Error(MISSING_KEY_MESSAGE)
  }
}

export async function sendEmail({ to, subject, html, text, link }: SendEmailOptions): Promise<void> {
  const apiKey = process.env.RESEND_API_KEY
  const from = process.env.EMAIL_FROM || DEFAULT_FROM

  // ── Dev console mode (never reached in production) ────────────────────────
  if (!apiKey) {
    assertEmailTransportConfigured()
    console.info(
      [
        '',
        '📧 [email:dev] RESEND_API_KEY not set — email logged, not sent.',
        `   from:    ${from}`,
        `   to:      ${to}`,
        `   subject: ${subject}`,
        ...(link ? [`   link:    ${link}`] : []),
        '',
      ].join('\n'),
    )
    return
  }

  // ── Resend mode ───────────────────────────────────────────────────────────
  let res: Response
  try {
    res = await fetch(RESEND_ENDPOINT, {
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
  } catch (err) {
    console.error('[email] Failed to reach Resend:', err)
    throw new Error('Email delivery failed. Please try again shortly.')
  }

  if (!res.ok) {
    // The response body echoes the recipient — log the status only.
    console.error(`[email] Resend responded ${res.status} for subject "${subject}"`)
    throw new Error('Email delivery failed. Please try again shortly.')
  }
}
