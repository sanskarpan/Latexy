'use client'

import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { signUp, authClient } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'

const GOOGLE_ENABLED = process.env.NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED === 'true'
const GITHUB_ENABLED = process.env.NEXT_PUBLIC_OAUTH_GITHUB_ENABLED === 'true'
const ANY_OAUTH = GOOGLE_ENABLED || GITHUB_ENABLED

const labelClass = 'block font-ui text-xs uppercase tracking-[0.16em] text-fg-3'

/**
 * Coerce an incoming redirect target to a safe same-origin relative path.
 * Rejects absolute and protocol-relative values to prevent open-redirect.
 */
function safeDest(raw: string | undefined): string {
  if (!raw || raw[0] !== '/' || raw[1] === '/' || raw[1] === '\\') return '/workspace'
  return raw
}

/** Lightweight 0–3 password strength heuristic for the sign-up hint. */
function passwordStrength(pw: string): { score: number; label: string } {
  let score = 0
  if (pw.length >= 8) score++
  if (/[a-z]/.test(pw) && /[A-Z]/.test(pw)) score++
  if (/\d/.test(pw) || /[^A-Za-z0-9]/.test(pw)) score++
  const labels = ['Too short', 'Weak', 'Fair', 'Strong']
  return { score, label: labels[Math.min(score, 3)] }
}
const oauthButtonClass =
  'inline-flex min-h-[44px] items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2.5 font-ui text-sm font-medium text-fg transition duration-150 hover:border-accent hover:text-accent-strong disabled:opacity-50 disabled:pointer-events-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none'

export default function SignUpForm({ redirect }: { redirect?: string }) {
  const dest = safeDest(redirect)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [name, setName] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [socialLoading, setSocialLoading] = useState<'google' | 'github' | null>(null)
  const [error, setError] = useState('')

  const strength = passwordStrength(password)
  const confirmMismatch = confirm.length > 0 && confirm !== password

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    // Validate client-side so typos surface inline instead of after a round-trip.
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }

    setIsLoading(true)
    try {
      const result = await signUp.email({ email, password, name })
      if (result.error) {
        setError(result.error.message || 'Sign up failed')
      } else {
        window.location.href = dest
      }
    } catch {
      setError('An unexpected error occurred')
    } finally {
      setIsLoading(false)
    }
  }

  const handleSocial = async (provider: 'google' | 'github') => {
    setSocialLoading(provider)
    setError('')
    try {
      const result = await authClient.signIn.social({ provider, callbackURL: dest })
      // The client resolves with an `error` instead of throwing, and only sends
      // the browser away once it has an authorization URL. Any other outcome
      // has to release the form — otherwise a failed handshake leaves every
      // button disabled with no way back short of a page reload.
      if (result?.error || !result?.data?.url) {
        setError(result?.error?.message || `${provider} sign-in is unavailable right now`)
        setSocialLoading(null)
      }
    } catch {
      setError(`${provider} sign-in failed`)
      setSocialLoading(null)
    }
  }

  return (
    <div className="mx-auto max-w-md space-y-6 rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
      <div className="space-y-1.5 text-center">
        <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Create account</p>
        <h1 className="font-display text-2xl font-semibold tracking-[-0.02em] text-fg sm:text-3xl">
          Set your résumé right.
        </h1>
      </div>

      {/* Social OAuth — buttons render only when the provider is configured */}
      {ANY_OAUTH && (
        <>
          <div className={`grid gap-3 ${GOOGLE_ENABLED && GITHUB_ENABLED ? 'grid-cols-2' : 'grid-cols-1'}`}>
            {GOOGLE_ENABLED && (
              <button
                type="button"
                onClick={() => handleSocial('google')}
                disabled={!!socialLoading || isLoading}
                className={oauthButtonClass}
              >
                <svg className="h-4 w-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09zM12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23zM5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62zM12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
                </svg>
                {socialLoading === 'google' ? 'Redirecting…' : 'Google'}
              </button>
            )}
            {GITHUB_ENABLED && (
              <button
                type="button"
                onClick={() => handleSocial('github')}
                disabled={!!socialLoading || isLoading}
                className={oauthButtonClass}
              >
                <svg className="h-4 w-4 fill-current" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
                </svg>
                {socialLoading === 'github' ? 'Redirecting...' : 'GitHub'}
              </button>
            )}
          </div>

          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-line" />
            <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">or sign up with email</span>
            <div className="h-px flex-1 bg-line" />
          </div>
        </>
      )}

      <form onSubmit={handleSubmit} className="space-y-5">
        <div className="space-y-2">
          <label htmlFor="name" className={labelClass}>
            Full Name
          </label>
          <Input
            type="text"
            id="name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            autoComplete="name"
          />
        </div>

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
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="password" className={labelClass}>
            Password
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
              aria-describedby="password-hint"
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
          <p id="password-hint" className="font-body text-xs text-fg-3">
            At least 8 characters.
          </p>
        </div>

        <div className="space-y-2">
          <label htmlFor="confirm" className={labelClass}>
            Confirm Password
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
              aria-describedby={confirmMismatch ? 'confirm-error' : undefined}
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
            <p id="confirm-error" className="font-body text-xs text-err" role="alert">
              Passwords do not match.
            </p>
          )}
        </div>

        <div aria-live="polite">
          {error && (
            <div className="rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-3 py-2 font-body text-sm text-err">
              {error}
            </div>
          )}
        </div>

        <Button
          type="submit"
          size="lg"
          loading={isLoading}
          disabled={!!socialLoading}
          className="w-full"
        >
          Sign Up
        </Button>
      </form>
    </div>
  )
}
