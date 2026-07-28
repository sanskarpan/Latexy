import { auth, pool } from "@/lib/auth"
import { enforceAuthRateLimit } from "@/lib/auth-rate-limit"

/**
 * Every auth request passes the shared, atomic per-IP gate before Better
 * Auth sees it. The gate does check-and-increment in one statement, so a
 * concurrent burst cannot slip past the limit the way Better Auth's own
 * read-on-request / write-on-response limiter allows. It fails open on a
 * counter-store outage so a DB blip degrades rate limiting, not sign-in.
 */
async function handle(request: Request): Promise<Response> {
  const limited = await enforceAuthRateLimit(pool, request)
  if (limited) return limited
  return auth.handler(request)
}

export const GET = handle
export const POST = handle
