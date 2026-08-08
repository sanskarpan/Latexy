'use client'

import { useState } from 'react'
import Link from 'next/link'
import { CheckCircle2 } from 'lucide-react'
import { authClient } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [sent, setSent] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    setError('')
    try {
      const { error: err } = await authClient.requestPasswordReset({
        email,
        redirectTo: '/reset-password',
      })
      if (err) {
        setError(err.message || 'Could not send the reset email. Please try again.')
      } else {
        setSent(true)
      }
    } catch {
      setError('An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
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
              <Link
                href="/login"
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
            href="/login"
            className="font-semibold text-accent-strong transition duration-150 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
