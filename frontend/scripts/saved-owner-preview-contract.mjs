/** The renderer harness supplies only a freshly owned loopback *_test database. */
export function isolatedPreviewDatabase(value) {
  let url
  try { url = new URL(value) } catch { throw new Error('An explicit isolated preview database is required') }
  if (url.protocol !== 'postgresql:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || !url.port || !url.pathname.endsWith('_test') || !/^\/[a-zA-Z0-9_]+$/.test(url.pathname)
    || url.search || url.hash) throw new Error('An explicit loopback *_test preview database is required')
  return value
}

/** Bind the normal UI signup exchange without exposing session values in errors. */
export function uiIssuedOwnerSession(value, email) {
  if (typeof email !== 'string' || !/^test_real_renderer_[a-f0-9-]{36}@example\.invalid$/.test(email)
    || !value || value.user?.email !== email
    || typeof value.user?.id !== 'string' || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.user.id)
    || typeof value.token !== 'string' || value.token.length < 1 || value.token.length > 4096
    || /[\s\x00-\x1f\x7f]/.test(value.token)) {
    throw new Error('Normal UI signup did not issue the exact synthetic owner session')
  }
  return { id: value.user.id, headers: { Authorization: `Bearer ${value.token}` } }
}

/** Bounded original-response bytes, never source/session values in errors. */
export function ownedPdfCapture(value, now = Date.now()) {
  if (!value || value.error || value.status !== 200 || value.artifactId !== ''
    || !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value.jobId)
    || !Number.isFinite(value.deadlineAt) || now > value.deadlineAt
    || !Number.isInteger(value.bodyBytes) || value.bodyBytes < 5 || value.bodyBytes > 20 * 1024 * 1024
    || typeof value.bodyBase64 !== 'string' || value.bodyBase64.length > Math.ceil(20 * 1024 * 1024 / 3) * 4
    || !/^[A-Za-z0-9+/]*={0,2}$/.test(value.bodyBase64)) {
    throw new Error('Owned PDF original-response capture failed')
  }
  const body = Buffer.from(value.bodyBase64, 'base64')
  if (body.length !== value.bodyBytes || body.subarray(0, 5).toString() !== '%PDF-') {
    throw new Error('Owned PDF original-response bytes are invalid')
  }
  return { jobId: value.jobId, body }
}
