/**
 * Better Auth server configuration.
 *
 * - Adapter: pg (uses existing DATABASE_URL)
 * - User table: "users" (our existing table, with field mapping for snake_case columns)
 * - Providers: email/password + Google + GitHub (social providers activate only when env vars are set)
 * - Session / account / verification tables: created by the Better Auth migration (see alembic/versions/)
 *
 * This module is server-only — never import it in Client Components.
 */

import { betterAuth } from 'better-auth'
import { Pool } from 'pg'
import { assertEmailTransportConfigured, sendEmail } from './email'

const APP_URL = process.env.BETTER_AUTH_URL || 'http://localhost:5180'

/** Shared connection pool — also used by the auth rate-limit gate. */
export const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
})

/**
 * Resolve the Better Auth signing secret. There is NO hardcoded fallback: a
 * well-known default secret would let anyone forge session cookies/tokens. In
 * production a missing secret is fatal; in development we derive a stable,
 * process-local placeholder and warn loudly.
 */
function getAuthSecret(): string {
  const secret = process.env.BETTER_AUTH_SECRET
  if (secret) return secret
  // `next build` runs with NODE_ENV=production but should not require runtime
  // secrets; only fail at actual runtime (serving), not during the build phase.
  const isBuildPhase = process.env.NEXT_PHASE === 'phase-production-build'
  if (process.env.NODE_ENV === 'production' && !isBuildPhase) {
    throw new Error('BETTER_AUTH_SECRET is required in production and has no default.')
  }
  console.warn('[auth] BETTER_AUTH_SECRET is not set — using an insecure development-only secret.')
  return 'dev-only-insecure-secret-do-not-use-in-production'
}

/**
 * Where the browser lands after Better Auth's GET /api/auth/verify-email has
 * consumed the token.
 *
 * That endpoint redirects to the bare `callbackURL` on success (the token is
 * spent and stripped) and to `callbackURL` + `&error=CODE` on failure — so the
 * landing page cannot tell the two apart from the absence of a token. The
 * explicit `verified=1` marker is that signal; see app/verify-email/page.tsx.
 */
export const VERIFY_EMAIL_CALLBACK = '/verify-email?verified=1'

/**
 * Point a Better Auth verification link at our verify-email result page.
 * Applied centrally so every sender (sign-up auto-send, the in-app resend
 * banner) gets the same landing page. Exported for tests.
 */
export function withVerifyEmailCallback(url: string): string {
  const link = new URL(url)
  link.searchParams.set('callbackURL', VERIFY_EMAIL_CALLBACK)
  return link.toString()
}

// A production deploy with no mail transport can still sign users up, but the
// verification / reset mail it promises them never leaves the box — and the
// per-send throw is swallowed by Better Auth's background-task wrapper, so the
// misconfiguration is otherwise invisible until a customer reports it. Fail at
// boot instead, the same way a missing BETTER_AUTH_SECRET does.
assertEmailTransportConfigured()

export const auth = betterAuth({
  database: pool,

  // Map to our existing "users" table with snake_case columns
  // NOTE: Better Auth 1.x uses "modelName" (not "tableName")
  user: {
    modelName: 'users',
    fields: {
      emailVerified: 'email_verified',
      image: 'avatar_url',
      createdAt: 'created_at',
      updatedAt: 'updated_at',
    },
  },

  // Our users.id column is type UUID — generate proper UUIDs
  advanced: {
    database: {
      generateId: () => crypto.randomUUID(),
    },
  },

  // Email + password sign-in
  emailAndPassword: {
    enabled: true,
    minPasswordLength: 8,
    // Soft verification: never block sign-in on an unverified email.
    requireEmailVerification: false,
    // Password reset — provider-agnostic. `url` already carries the token and
    // the caller's `redirectTo` (our /reset-password page). Degrades to a
    // console-logged dev link when RESEND_API_KEY is unset (see lib/email.ts).
    sendResetPassword: async ({ user, url }) => {
      await sendEmail({
        to: user.email,
        subject: 'Reset your Latexy password',
        text: `Reset your password using this link: ${url}`,
        html: resetPasswordEmail(url),
        link: url,
      })
    },
    // A password reset is the standard remediation after a credential leak, so
    // it has to invalidate every session an attacker may already hold —
    // otherwise a stolen better-auth.session_token stays usable for its full
    // 7-day lifetime after the victim "secures" the account.
    revokeSessionsOnPasswordReset: true,
  },

  // Soft email verification — built, not blocking. Sent automatically on
  // sign-up; users can also re-request via the in-app banner.
  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    sendVerificationEmail: async ({ user, url }) => {
      const link = withVerifyEmailCallback(url)
      await sendEmail({
        to: user.email,
        subject: 'Verify your Latexy email',
        text: `Verify your email using this link: ${link}`,
        html: verifyEmailTemplate(link),
        link,
      })
    },
  },

  // Second, per-process layer of rate limiting on the Next-server auth
  // endpoints (the FastAPI limiter does not cover these). The authoritative,
  // cross-instance limit is the atomic Postgres gate that runs in front of
  // `auth.handler` — see lib/auth-rate-limit.ts and app/api/auth/[...all].
  //
  // Better Auth's limiter is deliberately left on its default in-memory
  // storage: its interface reads the counter on request and writes it on
  // response, so no storage backend can make it correct under concurrency,
  // and a DB-backed `customStorage` additionally lets a DB blip 500 every
  // auth route (errors propagate straight out of `auth.handler`).
  rateLimit: {
    enabled: true,
    window: 60, // seconds
    max: 20, // requests per window per IP (Better Auth applies stricter rules to sensitive paths internally)
  },

  // Social OAuth providers — only active when both client ID + secret are provided
  socialProviders: {
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? {
          google: {
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          },
        }
      : {}),
    ...(process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET
      ? {
          github: {
            clientId: process.env.GITHUB_CLIENT_ID,
            clientSecret: process.env.GITHUB_CLIENT_SECRET,
          },
        }
      : {}),
  },

  secret: getAuthSecret(),
  baseURL: process.env.BETTER_AUTH_URL || 'http://localhost:5180',

  // Trust requests from both the frontend and the FastAPI backend
  trustedOrigins: [
    process.env.BETTER_AUTH_URL || 'http://localhost:5180',
    process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030',
  ],

  // Session configuration
  session: {
    expiresIn: 60 * 60 * 24 * 7, // 7 days
    updateAge: 60 * 60 * 24,     // refresh if used within 1 day of expiry
  },
})

// ─── Email templates ─────────────────────────────────────────────────────────

function emailShell(heading: string, body: string, cta: { href: string; label: string }): string {
  return `<!doctype html><html><body style="margin:0;background:#09090b;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#09090b;padding:32px 0;">
    <tr><td align="center">
      <table role="presentation" width="480" cellpadding="0" cellspacing="0" style="background:#111113;border:1px solid rgba(255,255,255,0.08);border-radius:16px;overflow:hidden;">
        <tr><td style="padding:32px 32px 8px;">
          <div style="font-size:13px;letter-spacing:0.16em;text-transform:uppercase;color:#fb923c;font-weight:600;">Latexy</div>
          <h1 style="margin:16px 0 8px;font-size:22px;line-height:1.3;color:#fafafa;">${heading}</h1>
          <p style="margin:0 0 24px;font-size:14px;line-height:1.6;color:#a1a1aa;">${body}</p>
          <a href="${cta.href}" style="display:inline-block;background:linear-gradient(135deg,#fb923c,#f97316);color:#0a0a0a;font-weight:600;font-size:14px;text-decoration:none;padding:12px 24px;border-radius:10px;">${cta.label}</a>
          <p style="margin:24px 0 0;font-size:12px;line-height:1.6;color:#71717a;">If the button doesn't work, copy and paste this link into your browser:<br><span style="color:#a1a1aa;word-break:break-all;">${cta.href}</span></p>
        </td></tr>
        <tr><td style="padding:20px 32px;border-top:1px solid rgba(255,255,255,0.06);">
          <p style="margin:0;font-size:12px;color:#52525b;">If you didn't request this, you can safely ignore this email.</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>`
}

function resetPasswordEmail(url: string): string {
  return emailShell(
    'Reset your password',
    'We received a request to reset your Latexy password. Click the button below to choose a new one. This link expires in 1 hour.',
    { href: url, label: 'Reset password' },
  )
}

function verifyEmailTemplate(url: string): string {
  return emailShell(
    'Verify your email',
    'Confirm your email address to secure your Latexy account and unlock the full experience.',
    { href: url, label: 'Verify email' },
  )
}
