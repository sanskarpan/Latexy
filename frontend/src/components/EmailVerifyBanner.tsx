'use client'

/**
 * Dismissible "verify your email" banner.
 *
 * Shown app-wide (mounted in the root layout) to logged-in users whose email
 * is not yet verified. Renders nothing for anonymous users, verified users, or
 * after the user dismisses it (dismissal persisted in localStorage).
 *
 * Verification is soft (non-blocking) — this is a nudge, not a gate.
 */

import { useEffect, useState } from 'react'
import { authClient, useSession } from '@/lib/auth-client'

const DISMISS_KEY = 'latexy_verify_banner_dismissed'

export default function EmailVerifyBanner() {
  const { data: session, isPending } = useSession()
  const [dismissed, setDismissed] = useState(true) // default hidden to avoid SSR flash
  const [resending, setResending] = useState(false)
  const [resent, setResent] = useState(false)
  const [error, setError] = useState('')

  // Read dismissal state on mount (client-only).
  useEffect(() => {
    try {
      setDismissed(localStorage.getItem(DISMISS_KEY) === '1')
    } catch {
      setDismissed(false)
    }
  }, [])

  const user = session?.user
  const shouldShow = !isPending && !!user && user.emailVerified === false && !dismissed

  if (!shouldShow) return null

  const handleDismiss = () => {
    try {
      localStorage.setItem(DISMISS_KEY, '1')
    } catch {
      /* ignore storage errors */
    }
    setDismissed(true)
  }

  const handleResend = async () => {
    if (!user?.email) return
    setResending(true)
    setError('')
    try {
      const { error: err } = await authClient.sendVerificationEmail({
        email: user.email,
        callbackURL: '/verify-email',
      })
      if (err) {
        setError(err.message || 'Could not resend. Try again shortly.')
      } else {
        setResent(true)
      }
    } catch {
      setError('Could not resend. Try again shortly.')
    } finally {
      setResending(false)
    }
  }

  return (
    <div className="border-b border-amber-400/20 bg-amber-500/10">
      <div className="content-shell flex flex-wrap items-center justify-between gap-3 py-2.5 text-sm">
        <div className="flex items-center gap-2 text-amber-200">
          <svg className="h-4 w-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86l-8.18 14.14A1 1 0 003 19.5h18a1 1 0 00.87-1.5L13.7 3.86a1 1 0 00-1.72 0z" />
          </svg>
          <span>
            {resent
              ? 'Verification email sent — check your inbox.'
              : error
                ? error
                : 'Please verify your email address to secure your account.'}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {!resent && (
            <button
              type="button"
              onClick={handleResend}
              disabled={resending}
              className="font-semibold text-amber-100 underline-offset-2 hover:underline disabled:opacity-50"
            >
              {resending ? 'Sending...' : 'Resend verification'}
            </button>
          )}
          <button
            type="button"
            onClick={handleDismiss}
            aria-label="Dismiss"
            className="rounded-md p-1 text-amber-200/70 transition hover:bg-amber-500/10 hover:text-amber-100"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
