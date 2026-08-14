'use client'

import { Suspense, useState } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Eye, EyeOff } from 'lucide-react'
import { authClient } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

/** Lightweight 0–3 password strength heuristic, mirrors SignUpForm's hint. */
function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0
  if (pw.length >= 8) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw) || /[^A-Za-z0-9]/.test(pw)) score++
  const labels = ['Too short', 'Weak', 'Fair', 'Strong']
  return { score, label: labels[Math.min(score, 3)] }
}

function ResetPasswordInner() {
  const router = useRouter()
  const params = useSearchParams()
  const token = params.get('token')
  const tokenError = params.get('error') // e.g. INVALID_TOKEN from Better Auth redirect

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  const strength = passwordStrength(password)
  const tooShort = password.length > 0 && password.length < 8
  const confirmMismatch = confirm.length > 0 && confirm !== password
  const canSubmit = password.length >= 8 && confirm.length > 0 && confirm === password

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
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div className="w-full max-w-md">
        <div className="text-center">
          <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Account recovery</span>
          <h1 className="mt-4 font-display text-4xl font-semibold tracking-[-0.02em] text-fg sm:text-5xl">
            Reset password
          </h1>
          <p className="mt-3 font-body text-fg-2">Choose a new password for your account.</p>
        </div>

        <div className="mt-8 rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
          {done ? (
            <div
              role="status"
              aria-live="polite"
              className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-3 text-center font-body text-sm text-ok"
            >
              Password updated. Redirecting you to sign in&hellip;
            </div>
          ) : invalidLink ? (
            <div className="space-y-4 text-center">
              <div
                role="alert"
                aria-live="assertive"
                className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-4 py-3 font-body text-sm text-err"
              >
                This reset link is invalid or has expired.
              </div>
              <Link
                href="/forgot-password"
                className="inline-block rounded-[var(--radius-sm)] font-ui text-sm font-semibold text-accent-strong hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
              >
                Request a new link
              </Link>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <label
                  htmlFor="password"
                  className="block font-ui text-xs uppercase tracking-[0.16em] text-fg-3"
                >
                  New password
                </label>
                <div className="relative">
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    id="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    aria-describedby="new-password-hint"
                    className="pr-12"
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
                {password.length > 0 && (
                  <div className="flex items-center gap-2" aria-hidden="true">
                    <div className="flex flex-1 gap-1">
                      {[0, 1, 2].map((i) => (
                        <span
                          key={i}
                          className={`h-1 flex-1 rounded-[var(--radius-pill)] transition-colors duration-150 ${
                            i < strength.score
                              ? strength.score >= 3
                                ? 'bg-ok'
                                : strength.score === 2
                                  ? 'bg-warn'
                                  : 'bg-err'
                              : 'bg-line-2'
                          }`}
                        />
                      ))}
                    </div>
                    <span className="font-ui text-xs text-fg-3">{strength.label}</span>
                  </div>
                )}
                <p
                  id="new-password-hint"
                  className={`font-body text-xs ${tooShort ? 'text-err' : 'text-fg-3'}`}
                >
                  {tooShort ? 'Must be at least 8 characters.' : 'At least 8 characters.'}
                </p>
              </div>

              <div className="space-y-2">
                <label
                  htmlFor="confirm"
                  className="block font-ui text-xs uppercase tracking-[0.16em] text-fg-3"
                >
                  Confirm password
                </label>
                <div className="relative">
                  <Input
                    type={showConfirm ? 'text' : 'password'}
                    id="confirm"
                    value={confirm}
                    onChange={(e) => setConfirm(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                    aria-invalid={confirmMismatch}
                    aria-describedby={confirmMismatch ? 'confirm-hint' : undefined}
                    className="pr-12"
                  />
                  <button
                    type="button"
                    onClick={() => setShowConfirm((v) => !v)}
                    aria-pressed={showConfirm}
                    aria-label={showConfirm ? 'Hide password' : 'Show password'}
                    className="absolute inset-y-0 right-0 flex min-h-[44px] min-w-[44px] items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition duration-150 hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
                  >
                    {showConfirm ? (
                      <EyeOff className="h-4 w-4" aria-hidden="true" />
                    ) : (
                      <Eye className="h-4 w-4" aria-hidden="true" />
                    )}
                  </button>
                </div>
                {confirmMismatch && (
                  <p id="confirm-hint" className="font-body text-xs text-err" role="alert">
                    Passwords don&apos;t match.
                  </p>
                )}
              </div>

              {error && (
                <div
                  role="alert"
                  aria-live="assertive"
                  className="rounded-[var(--radius-md)] border border-line-2 bg-surface-2 px-3 py-2 font-body text-sm text-err"
                >
                  {error}
                </div>
              )}

              <Button
                type="submit"
                disabled={isLoading || !canSubmit}
                loading={isLoading}
                className="h-11 w-full"
              >
                Update password
              </Button>
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
