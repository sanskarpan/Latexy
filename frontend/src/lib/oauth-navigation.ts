/**
 * Validate an OAuth authorization URL before handing it to the browser.
 *
 * These URLs come from an API response and are navigation sinks. OAuth
 * providers are deliberately allow-listed by exact hostname and path so a
 * malformed or compromised response cannot turn an account-connect click into
 * an arbitrary redirect.
 */
export function safeOAuthAuthorizationUrl(
  value: string,
  expected: { hostname: string; pathname: string },
): string | null {
  try {
    const url = new URL(value)
    if (
      url.protocol !== 'https:' ||
      url.username !== '' ||
      url.password !== '' ||
      url.port !== '' ||
      url.hostname !== expected.hostname ||
      url.pathname !== expected.pathname
    ) {
      return null
    }
    return url.href
  } catch {
    return null
  }
}
