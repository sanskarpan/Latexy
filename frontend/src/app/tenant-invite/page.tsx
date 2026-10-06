'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { apiClient } from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import SessionLoadError from '@/components/SessionLoadError'

type ClaimOwner = {
  token: string
  accountKey: string
  generation: number
}

function httpStatus(reason: unknown): number | undefined {
  const message = reason instanceof Error ? reason.message : String(reason)
  const match = message.match(/^HTTP (\d{3}):/)
  return match ? Number(match[1]) : undefined
}

function isRetryableClaimFailure(status: number | undefined): boolean {
  return status === undefined || status === 408 || status === 425 || status === 429 || status >= 500
}

function TenantInviteInner() {
  const params = useSearchParams()
  const token = params.get('token')
  const { session, isPending, error } = useRequireAuth()
  const [state, setState] = useState<'idle' | 'accepting' | 'accepted' | 'error'>('idle')
  const [message, setMessage] = useState('')
  const [retryable, setRetryable] = useState(false)
  const claimAttemptRef = useRef<ClaimOwner | null>(null)
  const claimGenerationRef = useRef(0)
  const accountKey = session?.user && session.session
    ? `${session.user.id}:${session.session.token}`
    : null

  useEffect(() => {
    const generation = ++claimGenerationRef.current
    claimAttemptRef.current = null
    setMessage('')
    setRetryable(false)
    setState('idle')
    return () => {
      // Invalidate pending acceptance on token removal, account changes, and
      // unmount before a late single-use claim can update another owner.
      if (claimGenerationRef.current === generation) {
        claimGenerationRef.current += 1
        claimAttemptRef.current = null
      }
    }
  }, [accountKey, isPending, token])

  const handleAcceptInvitation = () => {
    if (isPending || !session?.user || !token || !accountKey) return
    const generation = claimGenerationRef.current
    const owner: ClaimOwner = { token, accountKey, generation }
    // Lock synchronously before starting the promise so same-turn clicks and
    // Strict Mode replay cannot issue two single-use claims.
    if (claimAttemptRef.current) return
    claimAttemptRef.current = owner
    setMessage('')
    setRetryable(false)
    setState('accepting')
    apiClient.acceptTenantInvitation(token)
      .then(() => {
        if (
          claimGenerationRef.current !== owner.generation ||
          claimAttemptRef.current !== owner ||
          token !== owner.token ||
          accountKey !== owner.accountKey
        ) return
        claimAttemptRef.current = null
        setMessage('You have joined the organization.')
        setState('accepted')
      })
      .catch((reason: unknown) => {
        if (
          claimGenerationRef.current !== owner.generation ||
          claimAttemptRef.current !== owner ||
          token !== owner.token ||
          accountKey !== owner.accountKey
        ) return
        claimAttemptRef.current = null
        setMessage(reason instanceof Error ? reason.message : 'This invitation could not be accepted.')
        setRetryable(isRetryableClaimFailure(httpStatus(reason)))
        setState('error')
      })
  }

  if (isPending) return <InviteCard title="Checking your account…" />
  if (error && !session) return <SessionLoadError area="Tenant invitation" />
  if (!token) return <InviteCard title="Invalid invitation" detail="The invitation link is missing its token." />
  if (!session?.user) {
    const destination = `/tenant-invite?token=${encodeURIComponent(token)}`
    return (
      <InviteCard title="Sign in to accept your invitation" detail="Use the exact email address that was invited.">
        <Link className="rounded bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong" href={`/login?redirect=${encodeURIComponent(destination)}`}>
          Sign in
        </Link>
        <Link className="block text-sm text-accent-strong underline" href={`/signup?redirect=${encodeURIComponent(destination)}`}>
          Create an account
        </Link>
      </InviteCard>
    )
  }
  if (state === 'accepted') {
    return <InviteCard title="Invitation accepted" detail={message}><Link className="text-sm text-accent-strong underline" href="/workspace">Open workspace</Link></InviteCard>
  }
  if (state === 'error') {
    return (
      <InviteCard title="Invitation not accepted" detail={message}>
        {retryable && (
          <button
            type="button"
            onClick={handleAcceptInvitation}
            className="rounded bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong"
          >
            Try again
          </button>
        )}
      </InviteCard>
    )
  }
  return (
    <InviteCard
      title={state === 'accepting' ? 'Accepting invitation…' : 'Review your invitation'}
      detail="This link is single-use and bound to your signed-in email."
    >
      <button
        type="button"
        onClick={handleAcceptInvitation}
        disabled={state === 'accepting'}
        className="rounded bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-60"
      >
        {state === 'accepting' ? 'Accepting…' : 'Accept invitation'}
      </button>
    </InviteCard>
  )
}

function InviteCard({ title, detail, children }: { title: string; detail?: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-lg items-center px-5">
      <section className="w-full space-y-4 rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center">
        <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Organization invitation</p>
        <h1 className="text-xl font-semibold text-fg">{title}</h1>
        {detail && <p className="text-sm text-fg-2">{detail}</p>}
        {children}
      </section>
    </div>
  )
}

export default function TenantInvitePage() {
  return <Suspense fallback={<InviteCard title="Loading invitation…" />}><TenantInviteInner /></Suspense>
}
