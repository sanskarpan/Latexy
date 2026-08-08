'use client'

import Link from 'next/link'
import SignUpForm from '@/components/auth/SignUpForm'

export default function SignUpPage() {
  return (
    <div className="flex min-h-[80vh] items-center justify-center bg-bg px-5 py-16 sm:px-8">
      <div className="w-full max-w-md space-y-6">
        <SignUpForm />

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
