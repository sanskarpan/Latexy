'use client'

import Link from 'next/link'
import SignInForm from '@/components/auth/SignInForm'

export default function LoginPage() {
  return (
    <div className="bg-bg text-fg">
      <div className="mx-auto flex min-h-[80vh] max-w-6xl items-center justify-center px-5 py-16 sm:px-8">
        <div className="w-full max-w-md space-y-6">
          <SignInForm />

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
