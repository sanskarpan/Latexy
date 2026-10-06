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

  const stored = (await chrome.storage.local.get(key))[key]
  const valid = stored && Number(stored.expiresAt) > Date.now()
  if (stored && !valid) await chrome.storage.local.remove(key)
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
