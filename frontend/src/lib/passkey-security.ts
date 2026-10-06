/**
 * Validate names before they reach the WebAuthn adapter.
 *
 * Better Auth validates the shape of the request, but the passkey endpoint is
 * also exposed through our outer auth route. Keeping this check in a small
 * pure module makes the boundary testable without importing the server auth
 * singleton (and keeps hostile strings out of logs and error payloads).
 */
export type PasskeyNameValidation =
  | { name: string; error?: never }
  | { name?: never; error: string }

export function validatePasskeyName(value: unknown): PasskeyNameValidation {
  if (typeof value !== 'string') return { error: 'Passkey name is required.' }

  const name = value.trim()
  // 80 UTF-16 code units is deliberately conservative and matches the UI;
  // also bound encoded size so unusual Unicode cannot exceed DB/API limits.
  if (name.length < 1 || name.length > 80) return { error: 'Passkey name must be 1–80 characters.' }
  if (new TextEncoder().encode(name).length > 320) return { error: 'Passkey name is too large.' }
  // Reject controls (including C1 controls) and lone UTF-16 surrogates. The
  // latter can otherwise be serialized inconsistently between runtimes.
  if (/[\u0000-\u001F\u007F-\u009F]/u.test(name)) return { error: 'Passkey name contains unsupported characters.' }
  for (const character of name) {
    const codePoint = character.codePointAt(0)
    if (codePoint !== undefined && codePoint >= 0xD800 && codePoint <= 0xDFFF) {
      return { error: 'Passkey name contains unsupported characters.' }
    }
  }
  return { name }
}

/** Whether this browser can perform WebAuthn ceremonies from the current origin. */
export function supportsPasskeys(): boolean {
  return typeof window !== 'undefined' &&
    window.isSecureContext === true &&
    typeof window.PublicKeyCredential === 'function' &&
    typeof navigator.credentials?.create === 'function' &&
    typeof navigator.credentials?.get === 'function'
}
