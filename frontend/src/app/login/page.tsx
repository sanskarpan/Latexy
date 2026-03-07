'use client'

import Link from 'next/link'
import SignInForm from '@/components/auth/SignInForm'

export default function LoginPage() {
  return (
    <div className="content-shell flex min-h-[80vh] items-center justify-center">
        <div className="w-full max-w-md space-y-8">
          <div className="text-center">
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Welcome back
            </h1>
            <p className="mt-2 text-zinc-400">
              Sign in to your account to access your workspace
            </p>
          </div>

          <div className="surface-panel edge-highlight p-6 sm:p-8">
            <SignInForm />
          </div>

          <p className="text-center text-sm text-zinc-500">
            Don't have an account?{' '}
            <Link href="/signup" className="font-semibold text-orange-200 hover:text-orange-100">
              Sign up
            </Link>
          </p>
        </div>
    </div>
  )
}
