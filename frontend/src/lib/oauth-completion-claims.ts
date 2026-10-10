type OAuthProvider = 'github' | 'zotero' | 'mendeley' | 'dropbox' | 'google_drive'
type CompletionClaim = 'claimed' | 'duplicate' | 'unavailable' | 'exhausted'

// Both bounds matter: callback query strings are untrusted. Never evict an old
// intent to admit a new one, since Back or a delayed router.replace could then
// replay the evicted ticket under a different account.
const MAX_DOCUMENT_CLAIMS = 128
const MAX_TICKET_LENGTH = 4096
const documentClaims = new WeakMap<Document, Set<string>>()

/**
 * Claim an OAuth callback before dispatch, across every Settings mount in this
 * browser document. Account and token changes must not turn a one-use ticket
 * into a new intent. A fresh ticket can still be claimed by the next account.
 *
 * Only short-lived callback tickets are retained, in bounded document memory;
 * never credentials, account identities, browser storage, cookies, or logs.
 * The browser-only document key prevents cross-request/user state during SSR.
 * A full document navigation drops the ledger; the backend remains responsible
 * for owner binding, expiration, and single-use enforcement across documents.
 */
export function claimOAuthCompletion(provider: OAuthProvider, ticket: string): CompletionClaim {
  if (typeof window === 'undefined' || typeof document === 'undefined') return 'unavailable'
  if (!ticket || ticket.length > MAX_TICKET_LENGTH) return 'unavailable'

  let claims = documentClaims.get(document)
  if (!claims) {
    claims = new Set<string>()
    documentClaims.set(document, claims)
  }

  const key = `${provider}:${ticket}`
  if (claims.has(key)) return 'duplicate'
  if (claims.size >= MAX_DOCUMENT_CLAIMS) return 'exhausted'
  // Synchronous admission is important: another mount can run before the
  // router removes the ticket or before the authenticated API request starts.
  claims.add(key)
  return 'claimed'
}
