export interface ExtensionJobCapture {
  company: string
  title: string
  description: string
  location: string
  url: string
  source: 'json_ld' | 'visible_page'
}

const CAPTURE_ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

function boundedText(value: unknown, max: number, preserveLines = false): string {
  if (typeof value !== 'string') return ''
  const normalized = preserveLines
    ? value
        .split(/\r?\n/)
        .map((line) => line.replace(/[\t ]+/g, ' ').trim())
        .filter(Boolean)
        .join('\n')
    : value.replace(/\s+/g, ' ').trim()
  return normalized.slice(0, max)
}

export function validExtensionCaptureId(value: string | null): value is string {
  return typeof value === 'string' && CAPTURE_ID_RE.test(value)
}

export function parseExtensionCapture(value: unknown): ExtensionJobCapture | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const company = boundedText(raw.company, 200)
  const title = boundedText(raw.title, 200)
  const description = boundedText(raw.description, 20_000, true)
  const location = boundedText(raw.location, 200)
  const source = raw.source === 'json_ld' ? 'json_ld' : 'visible_page'
  let url = ''
  try {
    const parsed = new URL(boundedText(raw.url, 500))
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return null
    url = parsed.toString().slice(0, 500)
  } catch {
    return null
  }
  if (!company || !title) return null
  return { company, title, description, location, url, source }
}

export function requestExtensionCapture(
  captureId: string,
  timeoutMs = 4_000,
): Promise<ExtensionJobCapture> {
  if (!validExtensionCaptureId(captureId)) {
    return Promise.reject(new Error('Invalid browser-extension capture identifier.'))
  }

  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error: Error | null, capture?: ExtensionJobCapture) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      window.removeEventListener('message', onMessage)
      if (error) reject(error)
      else if (capture) resolve(capture)
    }
    const onMessage = (event: MessageEvent) => {
      if (event.source !== window || event.origin !== window.location.origin) return
      const message = event.data as Record<string, unknown> | null
      if (
        !message ||
        message.source !== 'latexy-extension' ||
        message.type !== 'LXY_CAPTURE_RESPONSE' ||
        message.captureId !== captureId
      ) return
      const capture = parseExtensionCapture(message.capture)
      if (!capture) {
        finish(new Error(boundedText(message.error, 300) || 'The extension capture is unavailable.'))
        return
      }
      window.postMessage(
        { source: 'latexy-web', type: 'LXY_CAPTURE_ACK', captureId },
        window.location.origin,
      )
      finish(null, capture)
    }
    window.addEventListener('message', onMessage)
    const timer = window.setTimeout(
      () => finish(new Error('Latexy Job Companion did not respond. Check that the extension is installed.')),
      timeoutMs,
    )
    window.postMessage(
      { source: 'latexy-web', type: 'LXY_CAPTURE_REQUEST', captureId },
      window.location.origin,
    )
  })
}
