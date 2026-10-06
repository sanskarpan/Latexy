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
import { genericOAuthClient, twoFactorClient } from 'better-auth/client/plugins'
import { passkeyClient } from '@better-auth/passkey/client'

export const authClient = createAuthClient({
  baseURL:
    typeof window !== 'undefined'
      ? window.location.origin
      : process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:5180',
  plugins: [
    genericOAuthClient(),
    twoFactorClient({ twoFactorPage: '/two-factor' }),
    passkeyClient(),
  ],
})

// Destructure only the stable client-side API
export const { signIn, signOut, signUp, useSession } = authClient

// getSession is available on the client object — expose via wrapper for type safety
export const getSession = () => authClient.getSession()

// Social OAuth helpers
export const signInWithGoogle = () =>
  authClient.signIn.social({ provider: 'google', callbackURL: '/workspace' })

export const signInWithGithub = () =>
  authClient.signIn.social({ provider: 'github', callbackURL: '/workspace' })

/**
 * Start passkey sign-in without asking for an email first. The server resolves
 * the account from the credential, so this flow does not expose an account
 * enumeration oracle.
 */
export const signInWithPasskey = () => authClient.signIn.passkey()

export default authClient
