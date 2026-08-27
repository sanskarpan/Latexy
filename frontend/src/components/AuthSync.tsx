'use client'

/**
 * AuthSync - keeps apiClient's auth token in sync with the Better Auth session.
 *
 * Mount once in the root layout (inside a Client Component boundary).
 * Whenever the Better Auth session changes (login, logout, token refresh)
 * apiClient is updated automatically so all subsequent API calls to FastAPI
 * include the correct Authorization: Bearer <session_token> header.
 */

import { useEffect } from 'react'
import { useSession } from '@/lib/auth-client'
import { apiClient } from '@/lib/api-client'
import { wsClient } from '@/lib/ws-client'

export function AuthSync() {
  const { data: session, isPending } = useSession()

  useEffect(() => {
    // While the session request is in flight we know nothing yet — publishing a
    // null token here would open apiClient's auth-ready gate too early and let
    // mount-time fetches go out unauthenticated (401s that are never retried).
    if (isPending) return
    // session?.session?.token is the raw Better Auth session token stored
    // in the `session` table. FastAPI validates it by querying that table.
    const token = session?.session?.token ?? null
    apiClient.setAuthToken(token)
    // AuthSync is the single source of truth for "the session state is known",
    // so it is the only caller of markAuthResolved() — this is what releases
    // apiClient's auth-ready gate for anonymous visitors too.
    apiClient.markAuthResolved()
    // Tell the WS manager only whether it should mint an authenticated one-time
    // ticket. The reusable Better Auth token must never enter a WebSocket URL.
    wsClient.setAuthenticated(Boolean(token))
  }, [session, isPending])

  return null
}
