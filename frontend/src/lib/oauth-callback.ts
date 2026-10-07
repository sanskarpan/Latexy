/**
 * Convert Better Auth's OAuth error code into deliberately generic UI copy.
 * Never surface `error_description`: it is provider-controlled and may contain
 * sensitive or misleading text.
 */
export function mapOAuthCallbackError(errorCode: string | null | undefined): string {
  const code = errorCode?.trim().toUpperCase().replace(/[-\s]+/g, '_')
  if (!code) return ''

  if (['ACCESS_DENIED', 'CANCELLED', 'CANCELED', 'POPUP_CLOSED', 'USER_CANCELLED', 'USER_CANCELED'].includes(code)) {
    return 'Sign-in was canceled. Try again or use email and password.'
  }
  if (['EXPIRED', 'INVALID_CODE', 'INVALID_STATE', 'STATE_INVALID', 'STATE_MISMATCH', 'STATE_NOT_FOUND', 'OAUTH_STATE_EXPIRED', 'SESSION_EXPIRED'].includes(code)) {
    return 'That sign-in attempt expired. Start again.'
  }
  if (['ACCOUNT_ALREADY_LINKED', 'ACCOUNT_ALREADY_LINKED_TO_DIFFERENT_USER', 'ACCOUNT_NOT_LINKED', 'EMAIL_NOT_FOUND', 'OAUTH_LINK_ERROR', 'UNABLE_TO_LINK_ACCOUNT'].includes(code)) {
    return 'This account cannot be linked here. Sign in with the original method, verify that email if prompted, or use another account.'
  }
  if (['OAUTH_PROVIDER_NOT_FOUND', 'PROVIDER_NOT_FOUND', 'INVALID_CALLBACK_URL', 'INVALID_ERROR_CALLBACK_URL'].includes(code)) {
    return 'This sign-in method is temporarily unavailable. Use email and password instead.'
  }

  return 'Sign-in could not be completed. Try again or use email and password.'
}

/** Keep redirects same-origin and reject browser-normalized control escapes. */
export function safeOAuthDestination(destination: string | undefined): string {
  if (!destination || destination[0] !== '/' || destination.startsWith('//') || destination.includes('\\')) {
    return '/workspace'
  }
  for (const character of destination) {
    const code = character.charCodeAt(0)
    if (code <= 0x1f || code === 0x7f) return '/workspace'
  }
  return destination
}

/** Build a same-origin relative callback that preserves the validated target. */
export function oauthErrorCallbackURL(path: '/login' | '/signup', destination: string): string {
  return `${path}?${new URLSearchParams({ redirect: safeOAuthDestination(destination) }).toString()}`
}
