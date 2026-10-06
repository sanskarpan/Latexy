import { auth, pool } from "@/lib/auth"
import { enforceAuthRateLimit } from "@/lib/auth-rate-limit"
import { validatePasskeyName } from "@/lib/passkey-security"

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

  // @better-auth/passkey 1.6.25 protects registration with a fresh session,
  // but its delete/update endpoints only require an ordinary session. Enforce
  // freshness at this outer boundary before Better Auth consumes the body.
  const path = new URL(request.url).pathname
  // Bound passkey labels before they enter Better Auth's challenge record or
  // database. The package only checks that these values are strings, so an
  // untrusted caller could otherwise submit arbitrarily large/control-filled
  // labels even though our UI limits them.
  if (path.endsWith('/passkey/generate-register-options') && request.method === 'GET') {
    const url = new URL(request.url)
    const rawName = url.searchParams.get('name')
    if (rawName !== null) {
      const name = validatePasskeyName(rawName)
      if (!name.name) return Response.json({ message: name.error, code: 'VALIDATION_ERROR' }, { status: 400 })
      url.searchParams.set('name', name.name)
      const headers = new Headers(request.headers)
      request = new Request(url.toString(), { method: 'GET', headers })
    }
  }

  // Better Auth deliberately executes sign-up/reset mail callbacks as
  // background work and turns callback failures into a successful auth
  // response. A production process with no provider must therefore fail these
  // delivery-dependent requests at the boundary, otherwise the UI promises a
  // message that can never arrive. This is intentionally a provider-level
  // response (not an account-existence response) and is safe for both known
  // and unknown email addresses.
  const isMailRequest = request.method === 'POST' && (
    path.endsWith('/request-password-reset') ||
    path.endsWith('/send-verification-email')
  )
  if (isMailRequest && process.env.NODE_ENV === 'production' && process.env.NEXT_PHASE !== 'phase-production-build' && !process.env.RESEND_API_KEY) {
    return Response.json({ message: 'Transactional email is temporarily unavailable. Please try again later.', code: 'EMAIL_DELIVERY_UNAVAILABLE' }, { status: 503 })
  }

  // Better Auth's two-factor enable / disable / backup-code regeneration
  // endpoints accept an ordinary authenticated session for passwordless
  // accounts. Require a fresh sign-in for these credential changes as well;
  // password revalidation inside Better Auth remains an additional check for
  // accounts that have a password credential.
  const isTwoFactorManagement = request.method === 'POST' && [
    '/two-factor/enable',
    '/two-factor/disable',
    '/two-factor/generate-backup-codes',
  ].some((endpoint) => path.endsWith(endpoint))
  if (isTwoFactorManagement) {
    const session = await auth.api.getSession({ headers: request.headers })
    if (!session) return Response.json({ message: 'Unauthorized', code: 'UNAUTHORIZED' }, { status: 401 })
    try {
      await auth.api.listSessions({ headers: request.headers })
    } catch {
      return Response.json({ message: 'A recent sign-in is required for two-factor management.', code: 'SESSION_NOT_FRESH' }, { status: 403 })
    }
  }

  if (path.endsWith('/passkey/verify-registration') && request.method === 'POST') {
    const body = await request.clone().json().catch(() => null) as { name?: unknown; response?: unknown } | null
    if (body && body.name !== undefined) {
      const name = validatePasskeyName(body.name)
      if (!name.name) return Response.json({ message: name.error, code: 'VALIDATION_ERROR' }, { status: 400 })
      const headers = new Headers(request.headers)
      headers.delete('content-length')
      request = new Request(request.url, {
        method: request.method,
        headers,
        body: JSON.stringify({ ...body, name: name.name }),
      })
    }
  }

  if (request.method === 'POST' && (path.endsWith('/passkey/delete-passkey') || path.endsWith('/passkey/update-passkey'))) {
    const session = await auth.api.getSession({ headers: request.headers })
    if (!session) return Response.json({ message: 'Unauthorized', code: 'UNAUTHORIZED' }, { status: 401 })
    try {
      await auth.api.listSessions({ headers: request.headers })
    } catch {
      return Response.json({ message: 'A recent sign-in is required for passkey management.', code: 'SESSION_NOT_FRESH' }, { status: 403 })
    }

    const body = await request.clone().json().catch(() => null) as { id?: unknown; name?: unknown } | null
    if (typeof body?.id !== 'string' || body.id.length === 0) return Response.json({ message: 'Passkey id is required.', code: 'VALIDATION_ERROR' }, { status: 400 })
    if (path.endsWith('/passkey/update-passkey')) {
      const name = validatePasskeyName(body.name)
      if (!name.name) return Response.json({ message: name.error, code: 'VALIDATION_ERROR' }, { status: 400 })
      // Delegate only the normalized, bounded payload. This prevents the
      // adapter from seeing a second representation of the user-controlled
      // name after the outer boundary has accepted it.
      const headers = new Headers(request.headers)
      // The original content length describes the untrusted body and must not
      // be carried onto this normalized request.
      headers.delete('content-length')
      request = new Request(request.url, {
        method: request.method,
        headers,
        body: JSON.stringify({ id: body.id, name: name.name }),
      })
    }
    if (path.endsWith('/passkey/delete-passkey')) {
      // Keep the count check and deletion in one transaction. Without the
      // advisory lock, two concurrent deletes could both observe two passkeys
      // and remove the final login method together.
      const client = await pool.connect()
      try {
        await client.query('BEGIN')
        await client.query('SELECT pg_advisory_xact_lock(hashtextextended($1, 0))', [session.user.id])
        const passkey = await client.query<{ user_id: string }>('SELECT "userId" AS user_id FROM "passkey" WHERE id = $1 FOR UPDATE', [body.id])
        if (passkey.rowCount !== 1 || passkey.rows[0]?.user_id !== session.user.id) {
          await client.query('ROLLBACK')
          return Response.json({ message: 'Passkey not found.', code: 'PASSKEY_NOT_FOUND' }, { status: 401 })
        }
        const { rows: passkeys } = await client.query('SELECT 1 FROM "passkey" WHERE "userId" = $1 LIMIT 2', [session.user.id])
        const { rows: accounts } = await client.query('SELECT 1 FROM account WHERE "userId" = $1 LIMIT 1', [session.user.id])
        if (passkeys.length <= 1 && accounts.length === 0) {
          await client.query('ROLLBACK')
          return Response.json({ message: 'Add another login method before removing your last passkey.', code: 'CANNOT_REMOVE_LAST_LOGIN_METHOD' }, { status: 400 })
        }
        await client.query('DELETE FROM "passkey" WHERE id = $1 AND "userId" = $2', [body.id, session.user.id])
        await client.query('COMMIT')
        return Response.json({ status: true })
      } catch {
        await client.query('ROLLBACK').catch(() => undefined)
        return Response.json({ message: 'Could not remove passkey.', code: 'PASSKEY_DELETE_FAILED' }, { status: 500 })
      } finally {
        client.release()
      }
    }

    const passkey = await pool.query<{ user_id: string }>('SELECT "userId" AS user_id FROM "passkey" WHERE id = $1', [body.id])
    if (passkey.rowCount !== 1 || passkey.rows[0]?.user_id !== session.user.id) return Response.json({ message: 'Passkey not found.', code: 'PASSKEY_NOT_FOUND' }, { status: 401 })
  }
  return auth.handler(request)
}

export const GET = handle
export const POST = handle
