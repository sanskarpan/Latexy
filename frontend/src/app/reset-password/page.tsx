'use client'

import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { authClient } from '@/lib/auth-client'

function ResetPasswordInner() {
  const router = useRouter()
  const params = useSearchParams()
  const token = params.get('token')
  const tokenError = params.get('error') // e.g. INVALID_TOKEN from Better Auth redirect

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    if (!token) {
      setError('Missing or invalid reset token. Request a new link.')
      return
    }

    setIsLoading(true)
    try {
      const { error: err } = await authClient.resetPassword({ newPassword: password, token })
      if (err) {
        setError(err.message || 'Could not reset your password. The link may have expired.')
      } else {
        setDone(true)
        setTimeout(() => router.push('/login'), 1500)
      }
    } catch {
      setError('An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  const invalidLink = !token || tokenError

  return (
    <div className="content-shell flex min-h-[80vh] items-center justify-center">
      <div className="w-full max-w-md space-y-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">Reset password</h1>
          <p className="mt-2 text-zinc-400">Choose a new password for your account</p>
        </div>

        <div className="surface-panel edge-highlight p-6 sm:p-8">
          {done ? (
            <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-4 py-3 text-center text-sm text-emerald-300">
              Password updated. Redirecting you to sign in&hellip;
            </div>
          ) : invalidLink ? (
            <div className="space-y-4 text-center">
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
                This reset link is invalid or has expired.
              </div>
              <Link
                href="/forgot-password"
                className="inline-block text-sm font-semibold text-orange-200 hover:text-orange-100"
              >
                Request a new link
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="max-w-md mx-auto space-y-4">
              <div>
                <label
                  htmlFor="password"
                  className="block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400"
                >
                  New password
                </label>
                <input
                  type="password"
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="mt-2 block w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2.5 text-sm text-zinc-100 outline-none transition focus:border-orange-300/50"
                />
              </div>

              <div>
                <label
                  htmlFor="confirm"
                  className="block text-xs font-semibold uppercase tracking-[0.14em] text-zinc-400"
                >
                  Confirm password
                </label>
                <input
                  type="password"
                  id="confirm"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  required
                  minLength={8}
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
                {isLoading ? 'Updating...' : 'Update password'}
              </button>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordInner />
    </Suspense>
  )
}
