'use client'

import { Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import SignUpForm from '@/components/auth/SignUpForm'
import { useI18n } from '@/components/I18nProvider'

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

function SignUpInner() {
  const { t } = useI18n()
  const searchParams = useSearchParams()
  const redirect = readRedirect(searchParams)
  const oauthError = searchParams.get('error') ?? undefined
  const loginHref = redirect ? `/login?redirect=${encodeURIComponent(redirect)}` : '/login'

  return (
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div className="w-full max-w-md space-y-6">
        <SignUpForm redirect={redirect ?? undefined} oauthError={oauthError} />

        <p className="text-center font-body text-sm text-fg-3">
            {t('auth.alreadyAccount')}{' '}
          <Link
            href={loginHref}
            className="font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)]"
          >
            {t('auth.signIn')}
          </Link>
        </p>
      </div>
    </div>
  )
}

export default function SignUpPage() {
  return (
    <Suspense fallback={null}>
      <SignUpInner />
    </Suspense>
  )
}
