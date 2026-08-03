'use client'

import Link from 'next/link'
import SignUpForm from '@/components/auth/SignUpForm'

export default function SignUpPage() {
  return (
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div className="w-full max-w-lg space-y-8">
        <div className="text-center">
          <span className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">
            Get started
          </span>
          <h1 className="mt-3 font-display text-[clamp(2rem,5vw,2.75rem)] font-semibold tracking-[-0.02em] text-fg">
            Create an account
          </h1>
          <p className="mt-3 font-body text-fg-2">
            Join Latexy and start building your career-winning resume.
          </p>
        </div>

        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8">
          <SignUpForm />
        </div>

        <p className="text-center font-body text-sm text-fg-3">
          Already have an account?{' '}
          <Link
            href="/login"
            className="font-medium text-accent-strong underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg rounded-[var(--radius-sm)]"
          >
            Sign in
          </Link>
        </p>
      </div>
    </div>
  )
}
