'use client'

import { Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import SignInForm from '@/components/auth/SignInForm'

// Accept whichever intended-destination param an auth guard may have appended.
const REDIRECT_KEYS = ['redirect', 'callbackURL', 'next', 'returnTo'] as const

/** Return a safe same-origin relative path, or null. Blocks open-redirects. */
function readRedirect(params: URLSearchParams): string | null {
  for (const key of REDIRECT_KEYS) {
    const raw = params.get(key)
    if (raw && raw[0] === '/' && raw[1] !== '/' && raw[1] !== '\\') return raw
  }
  return null
}

function LoginInner() {
  const redirect = readRedirect(useSearchParams())
  const signupHref = redirect ? `/signup?redirect=${encodeURIComponent(redirect)}` : '/signup'

  return (
    <div className="bg-bg text-fg">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center px-5 py-16 sm:px-8">
        <div className="w-full max-w-md space-y-6">
          <SignInForm redirect={redirect ?? undefined} />

          <p className="text-center font-body text-sm text-fg-3">
            Don&apos;t have an account?{' '}
            <Link
              href={signupHref}
              className="font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)]"
            >
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  )
}
