'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Check, Loader2, X } from 'lucide-react'
import { authClient } from '@/lib/auth-client'

type Status = 'verifying' | 'success' | 'error'

function VerifyEmailInner() {
  const params = useSearchParams()
  const token = params.get('token')
  const urlError = params.get('error') // present if Better Auth redirected here on failure
  // Better Auth's GET /api/auth/verify-email spends the token server-side and
  // then redirects to its callbackURL *without* it — so a missing token is not
  // a failure. lib/auth.ts pins that callbackURL to `?verified=1`, which is the
  // success signal here; failures arrive on the same URL as `&error=CODE`.
  const verified = params.get('verified') === '1'
  const ranRef = useRef(false)

  const [status, setStatus] = useState<Status>(() =>
    urlError ? 'error' : verified ? 'success' : token ? 'verifying' : 'error',
  )

  useEffect(() => {
    if (ranRef.current) return
    ranRef.current = true

    if (urlError) {
      setStatus('error')
      return
    }

    if (verified) {
      setStatus('success')
      return
    }

    if (!token) {
      setStatus('error')
      return
    }

    // The verify-email endpoint is a GET that validates the token server-side.
    authClient
      .verifyEmail({ query: { token } })
      .then((res) => {
        setStatus(res.error ? 'error' : 'success')
      })
      .catch(() => setStatus('error'))
  }, [token, urlError, verified])

  return (
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div
        className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center shadow-[var(--shadow-2)] sm:p-10"
        aria-live="polite"
      >
        {status === 'verifying' && (
          <>
            <div
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-[var(--radius-md)] border border-line-2 bg-surface-2 text-fg-3"
              aria-hidden="true"
            >
              <Loader2 className="h-6 w-6 motion-safe:animate-spin motion-reduce:animate-none" strokeWidth={2} />
            </div>
            <h1 className="mt-6 font-display text-2xl font-semibold text-fg">
              Verifying your email&hellip;
            </h1>
            <p className="mt-3 font-body text-sm text-fg-2">This will only take a moment.</p>
          </>
        )}

        {status === 'success' && (
          <>
            <div
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-[var(--radius-md)] border border-line-2 bg-accent-soft text-accent-strong"
              aria-hidden="true"
            >
              <Check className="h-6 w-6" strokeWidth={2} />
            </div>
            <h1 className="mt-6 font-display text-2xl font-semibold text-fg">Email verified</h1>
            <p className="mt-3 font-body text-sm text-fg-2">
              Your email is confirmed. You&apos;re all set.
            </p>
            <Link
              href="/workspace"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              Go to workspace
            </Link>
          </>
        )}

        {status === 'error' && (
          <>
            <div
              className="mx-auto flex h-12 w-12 items-center justify-center rounded-[var(--radius-md)] border border-line-2 bg-surface-2 text-err"
              aria-hidden="true"
            >
              <X className="h-6 w-6" strokeWidth={2} />
            </div>
            <h1 className="mt-6 font-display text-2xl font-semibold text-fg">Verification failed</h1>
            <p className="mt-3 font-body text-sm text-err">
              This verification link is invalid or has expired. You can request a new one from the
              banner in the app.
            </p>
            <Link
              href="/workspace"
              className="mt-8 inline-flex min-h-[44px] items-center justify-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              Back to app
            </Link>
          </>
        )}
      </div>
    </div>
  )
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailInner />
    </Suspense>
  )
}
