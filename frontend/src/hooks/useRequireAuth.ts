'use client'

import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

/**
 * Auth guard for pages that require a signed-in user. Redirects to
 * /login?redirect=<path> — but ONLY on a confirmed "no session" response.
 *
 * Bug this fixes: every page previously redirected whenever
 * `!isPending && !session`, which is also true while `useSession()` has
 * merely failed to fetch (e.g. a transient 429 from the shared-IP rate
 * limiter). That evicted already-authenticated users mid-session with a
 * perfectly valid cookie still in the browser — confirmed live in production
 * across 9+ pages. A fetch error is not the same claim as "you are logged
 * out" and must not be treated as one.
 */
export function useRequireAuth() {
  const { data: session, isPending, isRefetching = false, error } = useSession()
  const router = useRouter()
  const lastKnownSessionRef = useRef<typeof session>(null)
  const unauthorized = isConfirmedSessionUnauthorized(error)

  if (unauthorized) {
    // A completed 401 is authoritative, even if stale session data remains.
    lastKnownSessionRef.current = null
  } else if (session) {
    lastKnownSessionRef.current = session
  } else if (!isPending && !isRefetching && !error) {
    // Only an authoritative empty response clears the previous identity.
    lastKnownSessionRef.current = null
  }
  const effectiveSession = unauthorized ? null : session ?? ((isPending || isRefetching || error) ? lastKnownSessionRef.current : null)

  useEffect(() => {
    if (!unauthorized && (isPending || isRefetching || error)) return
    if (!effectiveSession) {
      // An offline session lookup cannot prove that the user's authenticated
      // cookie is invalid. Keep protected pages mounted so they can restore
      // local drafts instead of redirecting to a login page that cannot load.
      if (!unauthorized && typeof navigator !== 'undefined' && !navigator.onLine) return
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
    }
  }, [effectiveSession, isPending, isRefetching, error, unauthorized, router])

  // Better Auth keeps isPending=false and the same data reference throughout
  // an authenticated refresh. Preserve cold-load semantics and expose the
  // independent refetch flag so action guards can fail closed during it.
  return { session: effectiveSession, isPending, isRefetching, error }
}
