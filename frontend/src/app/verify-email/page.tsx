'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
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
    <div className="content-shell flex min-h-[80vh] items-center justify-center">
      <div className="w-full max-w-md space-y-8 text-center">
        {status === 'verifying' && (
          <div className="surface-panel edge-highlight p-8">
            <h1 className="text-2xl font-bold text-white">Verifying your email&hellip;</h1>
            <p className="mt-2 text-sm text-zinc-400">This will only take a moment.</p>
          </div>
        )}

        {status === 'success' && (
          <div className="surface-panel edge-highlight p-8">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-300">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <h1 className="mt-4 text-2xl font-bold text-white">Email verified</h1>
            <p className="mt-2 text-sm text-zinc-400">
              Your email is confirmed. You&apos;re all set.
            </p>
            <Link href="/workspace" className="btn-accent mt-6 inline-block px-6 py-2.5 text-sm">
              Go to workspace
            </Link>
          </div>
        )}

        {status === 'error' && (
          <div className="surface-panel edge-highlight p-8">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full border border-rose-500/30 bg-rose-500/10 text-rose-300">
              <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </div>
            <h1 className="mt-4 text-2xl font-bold text-white">Verification failed</h1>
            <p className="mt-2 text-sm text-zinc-400">
              This verification link is invalid or has expired. You can request a new one from the
              banner in the app.
            </p>
            <Link href="/workspace" className="btn-accent mt-6 inline-block px-6 py-2.5 text-sm">
              Back to app
            </Link>
          </div>
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
