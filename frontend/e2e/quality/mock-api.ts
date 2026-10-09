import registry from '../../../backend/app/core/capability_catalog.json'
import type { Route } from '@playwright/test'

export function qualityOrigins() {
  const port = Number.parseInt(process.env.PLAYWRIGHT_QUALITY_PORT ?? '5182', 10)
  return {
    appOrigin: new URL(`http://localhost:${port}`).origin,
    backendOrigin: new URL(process.env.PLAYWRIGHT_API_URL ?? process.env.PLAYWRIGHT_BACKEND_URL ?? `http://127.0.0.1:${port + 2000}`).origin,
  }
}

/** Cross-origin fixtures must match the credentialed API client's CORS contract.
 * OPTIONS is a preflight, never an application read or mutation. */
export function fulfillQualityJson(route: Route, data: unknown, status = 200) {
  const request = route.request()
  const requestHeaders = request.headers()
  const headers = {
    'access-control-allow-origin': requestHeaders.origin ?? qualityOrigins().appOrigin,
    'access-control-allow-credentials': 'true',
    'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
    'access-control-allow-headers': requestHeaders['access-control-request-headers'] ?? 'authorization, content-type',
    'content-type': 'application/json',
    vary: 'Origin',
  }
  const responseStatus = request.method() === 'OPTIONS' ? 204 : status
  return route.fulfill({ status: responseStatus, headers, body: responseStatus === 204 ? '' : JSON.stringify(data) })
}

/** Exercise public templates/import deliberately; keep background generation off.
 * Unknown keys are never silently granted by the fixture. */
export const QUALITY_FEATURES: Record<string, boolean> = {
  compile: true,
  ...Object.fromEntries(registry.map(({ key, gateable }) => [key, !gateable])),
  a09: true,
  b04: true,
  b06: true,
}

export const QUALITY_PLANS = {
  plans: {
    free: {
      id: 'free', name: 'Free', description: 'A free account for core document work.',
      price: 0, currency: 'INR', interval: 'month', billing_period: 'monthly',
      visible: true, purchasable: true, display_order: 0,
      features: { compilations: '10 / day', optimizations: 3, historyRetention: 7, prioritySupport: false, apiAccess: true, apiDailyLimit: 10 },
    },
    pro: {
      id: 'pro', name: 'Pro', description: 'More room for document and AI workflows.',
      price: 69900, currency: 'INR', interval: 'month', billing_period: 'monthly',
      visible: true, purchasable: false, unavailable_reason: 'Purchases disabled in this test', display_order: 1,
      features: { compilations: 'unlimited', optimizations: 100, historyRetention: 30, prioritySupport: true, apiAccess: true, apiDailyLimit: 100 },
    },
  },
  billing: { feature_enabled: false, mode: 'disabled', available: false, reason: 'fixture', message: 'Purchases disabled in this test' },
}
