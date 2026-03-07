'use client'

import Link from 'next/link'
import SignUpForm from '@/components/auth/SignUpForm'

export default function SignUpPage() {
  return (
    <div className="content-shell flex min-h-[80vh] items-center justify-center">
        <div className="w-full max-w-lg space-y-8">
          <div className="text-center">
            <h1 className="text-3xl font-bold tracking-tight text-white sm:text-4xl">
              Create an account
            </h1>
            <p className="mt-2 text-zinc-400">
              Join Latexy and start building your career-winning resume
            </p>
          </div>

          <div className="surface-panel edge-highlight p-6 sm:p-8">
            <SignUpForm />
          </div>

          <p className="text-center text-sm text-zinc-500">
            Already have an account?{' '}
            <Link href="/login" className="font-semibold text-orange-200 hover:text-orange-100">
              Sign in
            </Link>
          </p>
        </div>
    </div>
  )
}
