const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export interface WebVitalMetric {
  id: string
  name: string
  value: number
  rating?: string
  navigationType?: string
}

type TelemetryPayload = {
  kind: 'web_vital' | 'business_event'
  name: string
  route: string
  value?: number
  unit?: string
  metadata?: Record<string, unknown>
}

function randomHex(bytes: number): string {
  const values = new Uint8Array(bytes)
  crypto.getRandomValues(values)
  return Array.from(values, (value) => value.toString(16).padStart(2, '0')).join('')
}

function getSessionTraceId(): string {
  if (typeof window === 'undefined') return '00000000000000000000000000000000'
  const key = 'latexy_trace_id'
  const existing = sessionStorage.getItem(key)
  if (existing) return existing
  const traceId = randomHex(16)
  sessionStorage.setItem(key, traceId)
  return traceId
}

export function createTraceHeaders(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  const traceId = getSessionTraceId()
  const spanId = randomHex(8)
  const requestId = `req_${traceId.slice(0, 12)}_${spanId.slice(0, 8)}`
  return {
    traceparent: `00-${traceId}-${spanId}-01`,
    'X-Request-ID': requestId,
  }
}

async function sendTelemetry(payload: TelemetryPayload): Promise<void> {
  if (typeof window === 'undefined') return
  const body = JSON.stringify(payload)
  const url = `${API_BASE}/telemetry/frontend`
  const headers = {
    'Content-Type': 'application/json',
    ...createTraceHeaders(),
  }

  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      const sent = navigator.sendBeacon(url, blob)
      if (sent) return
    }
  } catch {
    // Fallback to fetch below.
  }

  void fetch(url, {
    method: 'POST',
    headers,
    body,
    keepalive: true,
  }).catch(() => undefined)
}

export function normalizeRoute(route: string | null | undefined): string {
  if (!route) return '/unknown'
  return route.length > 128 ? route.slice(0, 128) : route
}

export function trackWebVital(metric: WebVitalMetric, route: string): void {
  void sendTelemetry({
    kind: 'web_vital',
    name: metric.name,
    route: normalizeRoute(route),
    value: metric.value,
    unit: 'ms',
    metadata: {
      id: metric.id,
      rating: metric.rating,
      navigationType: metric.navigationType,
    },
  })
}

export function trackBusinessEvent(
  name: string,
  route: string,
  metadata?: Record<string, unknown>,
): void {
  void sendTelemetry({
    kind: 'business_event',
    name,
    route: normalizeRoute(route),
    metadata,
  })
}
