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
import { useSyncExternalStore } from 'react'

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

// Destructure only the stable client-side API. Better Auth's useSession is a
// useSyncExternalStore wrapper around a module-level mutable atom. A root
// consumer can resolve that atom before a late client segment hydrates, making
// its first client snapshot differ from the server's pending snapshot. Keep
// every consumer on the deterministic server/initial-client pending snapshot;
// useSyncExternalStore flips this gate only after hydration, then exposes the
// unchanged Better Auth result (including refetch, errors, and refresh state).
export const { signIn, signOut, signUp } = authClient

const subscribeHydration = () => () => {}
const getHydrationServerSnapshot = () => false
const getHydrationClientSnapshot = () => true

export function useSession() {
  const hydrated = useSyncExternalStore(
    subscribeHydration,
    getHydrationClientSnapshot,
    getHydrationServerSnapshot,
  )
  const session = authClient.useSession()

  if (!hydrated) {
    return {
      ...session,
      data: null,
      isPending: true,
      error: null,
      isRefetching: false,
    }
  }

  return session
}

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
