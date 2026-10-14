/** Application/account pages are reachable for users, but are not search content.
 * This is a crawler hint, never an authorization or data-protection boundary.
 * Public Studio, portfolio and share pages deliberately retain their own policy.
 */
export const NON_INDEXABLE_APP_ROOTS = [
  '/workspace',
  '/workspaces',
  '/dashboard',
  '/admin',
  '/billing',
  '/byok',
  '/settings',
  '/tracker',
  '/developer',
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/verify-email',
  '/two-factor',
  '/tenant-invite',
] as const

export const APP_ROBOTS_DIRECTIVE = 'noindex, nofollow, noarchive'

export function isNonIndexableAppPath(pathname: string): boolean {
  return NON_INDEXABLE_APP_ROOTS.some(root => pathname === root || pathname.startsWith(`${root}/`))
}
