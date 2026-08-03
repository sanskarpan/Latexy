'use client'

import Link from 'next/link'
import SignInForm from '@/components/auth/SignInForm'

export default function LoginPage() {
  return (
    <div className="bg-bg text-fg">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center px-5 py-16 sm:px-8">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">
              Sign in
            </span>
            <h1 className="mt-4 font-display text-[clamp(2rem,5vw,2.75rem)] font-semibold leading-[1.02] tracking-[-0.02em] text-fg">
              Welcome back
            </h1>
            <p className="mt-3 font-body text-fg-2">
              Sign in to your account to access your workspace.
            </p>
          </div>

          <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
            <SignInForm />
          </div>

          <p className="text-center font-body text-sm text-fg-3">
            Don&apos;t have an account?{' '}
            <Link
              href="/signup"
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
