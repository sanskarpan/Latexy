/**
 * Provider-agnostic transactional email sender (server-only).
 *
 * Used by Better Auth (see `src/lib/auth.ts`) for password-reset and
 * email-verification messages. Two modes:
 *
 *   1. Resend  — when `RESEND_API_KEY` is set, deliver via the Resend REST API
 *      (`https://api.resend.com/emails`) using plain `fetch` (no extra npm dep).
 *   2. Dev preview — ONLY outside production. The latest action link is held
 *      briefly in process memory and is available through the protected,
 *      same-origin `/api/dev/email-preview` endpoint; no token is written to
 *      stdout and no message is sent.
 *
 * The dev fallback is deliberately unreachable in production: a missing
 * `RESEND_API_KEY` there is a deploy-time misconfiguration. Production still
 * reports the missing provider loudly, but never falls back to a token-bearing
 * log line (or reports a send as successful).
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
  /** The single action link contained in the message. */
  link?: string
}

export interface DevEmailPreview {
  to: string
  subject: string
  link: string
}

const DEV_PREVIEW_TTL_MS = 10 * 60 * 1000
let devEmailPreview: (DevEmailPreview & { expiresAt: number }) | null = null

/**
 * True when this process is actually serving production traffic. `next build`
 * also runs with NODE_ENV=production but must not require runtime secrets, so
 * the build phase is excluded (mirrors `getAuthSecret` in lib/auth.ts).
 */
function isProductionRuntime(): boolean {
  return process.env.NODE_ENV === 'production' && process.env.NEXT_PHASE !== 'phase-production-build'
}

/** The in-memory preview is only a local developer feature, never staging. */
export function isDevPreviewRuntime(): boolean {
  return process.env.NODE_ENV === 'development' && process.env.NEXT_PHASE !== 'phase-production-build'
}

const MISSING_KEY_MESSAGE =
  'RESEND_API_KEY is not set — transactional email (verification, password reset) ' +
  'cannot be delivered. Configure a provider before relying on email.'

/**
 * Boot-time preflight: warn (loudly) when production has no mail transport.
 *
 * This is called from `lib/auth.ts` at module load. It must NEVER throw:
 * email verification is soft (a product decision), so a missing mail provider
 * degrades email delivery only — it must not crash the auth module and 500
 * every sign-in / sign-up / get-session. Surface the misconfiguration in logs
 * without including any action token.
 */
export function assertEmailTransportConfigured(): void {
  if (!process.env.RESEND_API_KEY && isProductionRuntime()) {
    console.error(`[email] ${MISSING_KEY_MESSAGE}`)
  }
}

/**
 * Consume the one latest dev-only email preview. The token remains in server
 * memory for at most ten minutes and is removed as soon as it is read.
 */
export function consumeDevEmailPreview(): DevEmailPreview | null {
  if (!isDevPreviewRuntime() || !devEmailPreview) return null
  const preview = devEmailPreview
  devEmailPreview = null
  if (preview.expiresAt <= Date.now()) return null
  return { to: preview.to, subject: preview.subject, link: preview.link }
}

/** Test-only cleanup hook; harmless outside tests and never persists data. */
export function clearDevEmailPreview(): void {
  devEmailPreview = null
}

export async function sendEmail({ to, subject, html, text, link }: SendEmailOptions): Promise<void> {
  const apiKey = process.env.RESEND_API_KEY
  const from = process.env.EMAIL_FROM || DEFAULT_FROM

  // ── Dev preview mode (never reached in production) ────────────────────────
  if (!apiKey) {
    assertEmailTransportConfigured()
    if (isProductionRuntime()) {
      // Better Auth intentionally runs most mail callbacks in a background
      // task and therefore swallows callback exceptions. Throw here so direct
      // callers can report a failed delivery, while the boot preflight still
      // makes the deploy-time misconfiguration visible to operators.
      throw new Error('Email delivery is unavailable. Configure RESEND_API_KEY and try again.')
    }
    if (isDevPreviewRuntime() && link) {
      devEmailPreview = { to, subject, link, expiresAt: Date.now() + DEV_PREVIEW_TTL_MS }
    }
    console.info(
      [
        '',
        '📧 [email:dev] RESEND_API_KEY not set — preview available at /api/dev/email-preview; not sent.',
        // Do not log recipient PII, sender configuration, or action links.
        // The one-time local preview endpoint is the only place where the
        // action link is intentionally exposed.
        `   subject: ${subject}`,
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
