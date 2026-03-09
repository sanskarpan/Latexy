/**
 * Better Auth client — use this in Client Components and hooks.
 *
 * Exports:
 *   authClient    — the full client instance (for advanced use)
 *   signIn        — signIn.email({ email, password })
 *   signUp        — signUp.email({ email, password, name })
 *   signOut       — signOut()
 *   useSession    — React hook that returns { data: { session, user }, isPending, error }
 *   getSession    — async function to retrieve the current session
 */

import { createAuthClient } from 'better-auth/react'

export const authClient = createAuthClient({
  baseURL:
    typeof window !== 'undefined'
      ? window.location.origin
      : process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:5180',
})

// Destructure only the stable client-side API
export const { signIn, signOut, signUp, useSession } = authClient

// getSession is available on the client object — expose via wrapper for type safety
export const getSession = () => authClient.getSession()

// Social OAuth helpers
export const signInWithGoogle = () =>
  authClient.signIn.social({ provider: 'google', callbackURL: '/dashboard' })

export const signInWithGithub = () =>
  authClient.signIn.social({ provider: 'github', callbackURL: '/dashboard' })

export default authClient
