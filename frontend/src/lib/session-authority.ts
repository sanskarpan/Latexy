/** Better Auth's completed session lookup uses the numeric HTTP status.
 * Only 401 establishes loss of authentication; outages and ambiguous failures
 * must preserve last-known local recovery and credentials.
 */
export function isConfirmedSessionUnauthorized(error: unknown): boolean {
  return typeof error === 'object' && error !== null && 'status' in error && error.status === 401
}
