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

export function AuthSync() {
  const { data: session } = useSession()

  useEffect(() => {
    // session?.session?.token is the raw Better Auth session token stored
    // in the `session` table. FastAPI validates it by querying that table.
    const token = session?.session?.token ?? null
    apiClient.setAuthToken(token)
  }, [session])

  return null
}
