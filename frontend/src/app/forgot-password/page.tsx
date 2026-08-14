'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { CheckCircle2 } from 'lucide-react'
import { authClient } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

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

const RESEND_COOLDOWN_SECONDS = 30

function ForgotPasswordInner() {
  const redirect = readRedirect(useSearchParams())
  const loginHref = redirect ? `/login?redirect=${encodeURIComponent(redirect)}` : '/login'
  const [email, setEmail] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)
  const [resendCooldown, setResendCooldown] = useState(0)
  const [resendStatus, setResendStatus] = useState('')
  const cooldownTimer = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    return () => {
      if (cooldownTimer.current) clearInterval(cooldownTimer.current)
    }
  }, [])

  const startCooldown = () => {
    setResendCooldown(RESEND_COOLDOWN_SECONDS)
    if (cooldownTimer.current) clearInterval(cooldownTimer.current)
    cooldownTimer.current = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          if (cooldownTimer.current) clearInterval(cooldownTimer.current)
          return 0
        }
        return prev - 1
      })
    }, 1000)
  }

  const requestReset = async () => {
    const { error: err } = await authClient.requestPasswordReset({
      email,
      redirectTo: '/reset-password',
    })
    if (err) {
      throw new Error(err.message || 'Could not send the reset email. Please try again.')
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')
    try {
      await requestReset()
      setSent(true)
      startCooldown()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  const handleResend = async () => {
    if (resendCooldown > 0 || isLoading) return
    setIsLoading(true)
    setError('')
    setResendStatus('')
    try {
      await requestReset()
      setResendStatus('Link resent — check your inbox.')
      startCooldown()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  const handleUseDifferentEmail = () => {
    if (cooldownTimer.current) clearInterval(cooldownTimer.current)
    setSent(false)
    setResendCooldown(0)
    setResendStatus('')
    setError('')
  }

  return (
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">
            Account recovery
          </span>
          <h1 className="mt-4 font-display text-[clamp(2rem,5vw,2.6rem)] font-semibold tracking-[-0.02em] text-fg">
            Forgot password
          </h1>
          <p className="mt-3 font-body text-fg-2">
            Enter your email and we&apos;ll send you a reset link.
          </p>
        </div>

        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
          {sent ? (
            <div className="space-y-6 text-center">
              <div
                className="flex items-start gap-3 rounded-[var(--radius-md)] border border-line-2 bg-accent-soft px-4 py-3 text-left font-body text-sm text-fg-2"
                role="status"
                aria-live="polite"
              >
                <CheckCircle2
                  className="mt-0.5 h-5 w-5 flex-shrink-0 text-ok"
                  aria-hidden="true"
                />
                <span>
                  If an account exists for{' '}
                  <span className="font-semibold text-fg">{email}</span>, a password reset link
                  is on its way. Check your inbox.
                </span>
              </div>

              {resendStatus && (
                <div
                  role="status"
                  aria-live="polite"
                  className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-2 text-left font-body text-sm text-ok"
                >
                  {resendStatus}
                </div>
              )}

              {error && (
                <div
                  role="alert"
                  aria-live="assertive"
                  className="rounded-[var(--radius-md)] border border-err/40 bg-surface-2 px-3 py-2 text-left font-body text-sm text-err"
                >
                  {error}
                </div>
              )}

              <div className="flex flex-col gap-3 sm:flex-row sm:justify-center">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={handleResend}
                  disabled={isLoading || resendCooldown > 0}
                  loading={isLoading}
                  className="sm:w-auto"
                >
                  {resendCooldown > 0 ? `Resend link (${resendCooldown}s)` : 'Resend link'}
                </Button>
                <button
                  type="button"
                  onClick={handleUseDifferentEmail}
                  className="font-ui text-sm font-medium text-fg-3 underline-offset-2 transition duration-150 hover:text-fg hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)] motion-reduce:transition-none"
                >
                  Use a different email
                </button>
              </div>

              <Link
                href={loginHref}
                className="inline-flex items-center rounded-[var(--radius-sm)] font-ui text-sm font-semibold text-accent-strong transition duration-150 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div>
                <label
                  htmlFor="email"
                  className="block font-ui text-xs font-medium uppercase tracking-[0.16em] text-fg-3"
                >
                  Email
                </label>
                <Input
                  type="email"
                  id="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  className="mt-2 h-11"
                />
              </div>

              {error && (
                <div
                  className="rounded-[var(--radius-md)] border border-err/40 bg-surface-2 px-3 py-2 font-body text-sm text-err"
                  role="alert"
                  aria-live="assertive"
                >
                  {error}
                </div>
              )}

              <Button
                type="submit"
                size="lg"
                loading={isLoading}
                className="w-full uppercase tracking-[0.06em]"
              >
                Send reset link
              </Button>
            </form>
          )}
        </div>

        <p className="text-center font-body text-sm text-fg-3">
          Remembered it?{' '}
          <Link
            href={loginHref}
            className="font-semibold text-accent-strong transition duration-150 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ForgotPasswordInner />
    </Suspense>
  )
}
