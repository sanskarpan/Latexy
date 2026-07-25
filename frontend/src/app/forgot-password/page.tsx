'use client'

import { useState } from 'react'
import Link from 'next/link'
import { authClient } from '@/lib/auth-client'

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
    <div className="content-shell flex min-h-[80vh] items-center justify-center">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Forgot password</h1>
          <p className="mt-2 text-zinc-400">Enter your email and we&apos;ll send you a reset link</p>
        </div>

        <div className="surface-panel edge-highlight p-6 sm:p-8">
          {sent ? (
            <div className="space-y-4 text-center">
              <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-300">
                If an account exists for <span className="font-semibold">{email}</span>, a password reset
                link is on its way. Check your inbox.
              </div>
              <Link
                href="/login"
                className="inline-block text-sm font-semibold text-orange-200 hover:text-orange-100"
              >
                Back to sign in
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="max-w-md mx-auto space-y-4">
              <div>
                <label
                  htmlFor="email"
                  className="block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400"
                >
                  Email
                </label>
                <input
                  type="email"
                  id="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  className="mt-2 block w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-orange-300/50"
                />
              </div>

              {error && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
                  {error}
                </div>
              )}

              <button
                type="submit"
                disabled={isLoading}
                className="btn-accent w-full py-2.5 text-sm disabled:opacity-50"
              >
                {isLoading ? 'Sending...' : 'Send reset link'}
              </button>
            </form>
          )}
        </div>

        <p className="text-center text-sm text-zinc-500">
          Remembered it?{' '}
          <Link href="/login" className="font-semibold text-orange-200 hover:text-orange-100">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
