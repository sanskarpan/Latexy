'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Eye, EyeOff } from 'lucide-react'
import { signIn, authClient } from '@/lib/auth-client'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const GOOGLE_ENABLED = process.env.NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED === 'true'
const GITHUB_ENABLED = process.env.NEXT_PUBLIC_OAUTH_GITHUB_ENABLED === 'true'
const ANY_OAUTH = GOOGLE_ENABLED || GITHUB_ENABLED

// How long a social redirect can sit at "Redirecting..." before we treat the
// handshake as stalled and hand control back to the user.
const SOCIAL_TIMEOUT_MS = 8000

/**
 * Coerce an incoming redirect target to a safe same-origin relative path.
 * Rejects absolute URLs and protocol-relative (`//`, `/\`) values to prevent
 * open-redirect. Falls back to the generic workspace landing.
 */
function safeDest(raw: string | undefined): string {
  if (!raw || raw[0] !== '/' || raw[1] === '/' || raw[1] === '\\') return '/workspace'
  return raw
}

/** Map terse/technical Better Auth error text to friendlier copy. */
function friendlyAuthError(message: string | undefined, fallback: string): string {
  const text = (message || '').toLowerCase()
  if (!text) return fallback
  if (text.includes('invalid') && (text.includes('password') || text.includes('credential'))) {
    return 'Incorrect email or password. Please try again.'
  }
  if (text.includes('not found') || text.includes('no user')) {
    return 'We couldn’t find an account with that email.'
  }
  if (text.includes('too many') || text.includes('rate limit')) {
    return 'Too many attempts. Please wait a moment and try again.'
  }
  if (text.includes('verify') || text.includes('verification')) {
    return 'Please verify your email address before signing in.'
  }
  return message || fallback
}

const labelClass = 'block font-ui text-xs uppercase tracking-[0.16em] text-fg-3'
const oauthBtnClass =
  'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2.5 font-ui text-sm font-medium text-fg transition duration-150 hover:border-accent hover:text-accent-strong disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none'

/** Google mark, rendered in the current text color to stay token-bound. */
function GoogleIcon() {
  return (
    <svg className="h-4 w-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09zM12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23zM5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62zM12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  )
}

/** GitHub mark, rendered in the current text color to stay token-bound. */
function GithubIcon() {
  return (
    <svg className="h-4 w-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
    </svg>
  )
}

export default function SignInForm({ redirect }: { redirect?: string }) {
  const dest = safeDest(redirect)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [socialLoading, setSocialLoading] = useState<'google' | 'github' | null>(null)
  const [error, setError] = useState('')
  const errorRef = useRef<HTMLDivElement>(null)
  const socialTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (error && errorRef.current) {
      errorRef.current.focus()
    }
  }, [error])

  useEffect(() => {
    return () => {
      if (socialTimeoutRef.current) clearTimeout(socialTimeoutRef.current)
    }
  }, [])

  const forgotHref =
    dest === '/workspace'
      ? '/forgot-password'
      : `/forgot-password?redirect=${encodeURIComponent(dest)}`

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')
    try {
      const result = await signIn.email({ email, password })
      if (result.error) {
        setError(friendlyAuthError(result.error.message, 'Sign in failed'))
      } else {
        window.location.href = dest
      }
    } catch {
      setError('An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  const clearSocialTimeout = () => {
    if (socialTimeoutRef.current) {
      clearTimeout(socialTimeoutRef.current)
      socialTimeoutRef.current = null
    }
  }

  const handleSocial = async (provider: 'google' | 'github') => {
    setSocialLoading(provider)
    setError('')
    clearSocialTimeout()
    // Guard against a stalled OAuth handshake: if the browser hasn't been
    // navigated away within SOCIAL_TIMEOUT_MS, release the form instead of
    // leaving a disabled "Redirecting..." button as a dead end.
    socialTimeoutRef.current = setTimeout(() => {
      setSocialLoading(null)
      setError('Taking longer than expected — try again.')
    }, SOCIAL_TIMEOUT_MS)
    try {
      const result = await authClient.signIn.social({ provider, callbackURL: dest })
      // The client resolves with an `error` instead of throwing, and only sends
      // the browser away once it has an authorization URL. Any other outcome
      // has to release the form — otherwise a failed handshake leaves every
      // button disabled with no way back short of a page reload.
      if (result?.error || !result?.data?.url) {
        clearSocialTimeout()
        setError(
          friendlyAuthError(result?.error?.message, `${provider} sign-in is unavailable right now`)
        )
        setSocialLoading(null)
      }
    } catch {
      clearSocialTimeout()
      setError(`${provider} sign-in failed`)
      setSocialLoading(null)
    }
  }

  return (
    <div className="mx-auto w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
      <div className="mb-8 text-center">
        <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Latexy</p>
        <h1 className="mt-3 font-display text-3xl font-semibold tracking-[-0.02em] text-fg">
          Welcome back
        </h1>
        <p className="mt-2 font-body text-sm text-fg-2">Sign in to continue to your workspace.</p>
      </div>

      <div className="space-y-5">
        {/* Social OAuth — buttons render only when the provider is configured */}
        {ANY_OAUTH && (
          <>
            <div className={`grid gap-3 ${GOOGLE_ENABLED && GITHUB_ENABLED ? 'grid-cols-2' : 'grid-cols-1'}`}>
              {GOOGLE_ENABLED && (
                <button
                  type="button"
                  onClick={() => handleSocial('google')}
                  disabled={!!socialLoading || isLoading}
                  className={oauthBtnClass}
                >
                  <GoogleIcon />
                  {socialLoading === 'google' ? 'Redirecting...' : 'Google'}
                </button>
              )}
              {GITHUB_ENABLED && (
                <button
                  type="button"
                  onClick={() => handleSocial('github')}
                  disabled={!!socialLoading || isLoading}
                  className={oauthBtnClass}
                >
                  <GithubIcon />
                  {socialLoading === 'github' ? 'Redirecting...' : 'GitHub'}
                </button>
              )}
            </div>

            <div className="flex items-center gap-3">
              <div className="h-px flex-1 bg-line" />
              <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">
                or continue with email
              </span>
              <div className="h-px flex-1 bg-line" />
            </div>
          </>
        )}

        <form onSubmit={handleSubmit} className="space-y-5" aria-describedby={error ? 'signin-error' : undefined}>
          <div className="space-y-2">
            <label htmlFor="email" className={labelClass}>
              Email
            </label>
            <Input
              type="email"
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              className="min-h-[44px]"
            />
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label htmlFor="password" className={labelClass}>
                Password
              </label>
              <Link
                href={forgotHref}
                className="font-ui text-xs font-medium text-accent-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)]"
              >
                Forgot password?
              </Link>
            </div>
            <div className="relative">
              <Input
                type={showPassword ? 'text' : 'password'}
                id="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                className="min-h-[44px] pr-12"
              />
              <button
                type="button"
                onClick={() => setShowPassword((v) => !v)}
                aria-pressed={showPassword}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
                className="absolute inset-y-0 right-0 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition duration-150 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
              >
                {showPassword ? (
                  <EyeOff className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Eye className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            </div>
          </div>

          <div aria-live="polite">
            {error && (
              <div
                id="signin-error"
                ref={errorRef}
                tabIndex={-1}
                role="alert"
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-2 font-body text-sm text-err focus:outline-none"
              >
                {error}
              </div>
            )}
          </div>

          <Button
            type="submit"
            loading={isLoading}
            disabled={!!socialLoading}
            size="lg"
            className="w-full min-h-[44px]"
          >
            Sign In
          </Button>
        </form>
      </div>
    </div>
  )
}
