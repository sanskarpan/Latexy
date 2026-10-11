const CAPTURE_PREFIX = 'latexy:capture:'
const CAPTURE_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

window.addEventListener('message', async (event) => {
  if (event.source !== window || event.origin !== window.location.origin) return
  const message = event.data
  if (!message || message.source !== 'latexy-web' || !CAPTURE_ID.test(message.captureId || '')) return

  const key = `${CAPTURE_PREFIX}${message.captureId}`
  if (message.type === 'LXY_CAPTURE_ACK') {
    await chrome.storage.local.remove(key)
    return
  }
  if (message.type !== 'LXY_CAPTURE_REQUEST') return

  let ownerId = null
  let allowed = false
  try {
    const response = await fetch('/api/extension/entitlements', {
      credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(8000),
    })
    const entitlement = response.ok ? await response.json() : null
    ownerId = entitlement?.owner_id
    allowed = entitlement?.available === true && entitlement?.capture_available === true && typeof ownerId === 'string' && Boolean(ownerId)
  } catch { /* Availability failures deny new handoffs; acknowledgements still clear data. */ }
  if (!allowed) {
    window.postMessage({ source: 'latexy-extension', type: 'LXY_CAPTURE_RESPONSE', captureId: message.captureId,
      capture: null, error: 'Job Companion is unavailable or your session could not be verified.' }, window.location.origin)
    return
  }

  const stored = (await chrome.storage.local.get(key))[key]
  const valid = stored && stored.ownerId === ownerId && Number(stored.expiresAt) > Date.now()
  if (stored && Number(stored.expiresAt) <= Date.now()) await chrome.storage.local.remove(key)
  window.postMessage(
    {
      source: 'latexy-extension',
      type: 'LXY_CAPTURE_RESPONSE',
      captureId: message.captureId,
      capture: valid ? stored.capture : null,
      error: valid ? null : 'Capture expired or was already imported.',
    },
    window.location.origin,
  )
})
