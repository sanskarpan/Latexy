'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from '@/lib/auth-client'

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
  const { data: session, isPending, error } = useSession()
  const router = useRouter()

  useEffect(() => {
    if (isPending || error) return
    if (!session) {
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
    }
  }, [session, isPending, error, router])

  return { session, isPending, error }
}
