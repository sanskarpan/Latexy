import { readFileSync } from 'node:fs'
import type { Route } from '@playwright/test'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { fulfillQualityJson, qualityOrigins, QUALITY_FEATURES, QUALITY_PLANS } from '../../e2e/quality/mock-api'

function route(method = 'GET', headers: Record<string, string> = {}) {
  const fulfill = vi.fn().mockResolvedValue(undefined)
  return { value: { request: () => ({ method: () => method, headers: () => headers }), fulfill } as unknown as Route, fulfill }
}

afterEach(() => vi.unstubAllEnvs())

describe('quality browser API fixtures', () => {
  it('answers credentialed cross-origin requests with an exact origin instead of wildcard CORS', async () => {
    const r = route('GET', { origin: 'http://localhost:5182' })
    await fulfillQualityJson(r.value, { features: QUALITY_FEATURES })
    const response = r.fulfill.mock.calls[0][0]
    expect(response.status).toBe(200)
    expect(response.headers).toMatchObject({ 'access-control-allow-origin': 'http://localhost:5182', 'access-control-allow-credentials': 'true', vary: 'Origin' })
    expect(JSON.parse(response.body)).toEqual({ features: QUALITY_FEATURES })
  })
  it('answers preflight with the requested authorization headers and no application payload', async () => {
    const r = route('OPTIONS', { origin: 'http://localhost:5182', 'access-control-request-headers': 'authorization,content-type,x-client-id' })
    await fulfillQualityJson(r.value, QUALITY_PLANS)
    expect(r.fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 204, body: '', headers: expect.objectContaining({ 'access-control-allow-headers': 'authorization,content-type,x-client-id' }) }))
  })
  it('does not serialize a body for successful telemetry acknowledgements', async () => {
    const r = route('POST')
    await fulfillQualityJson(r.value, null, 204)
    expect(r.fulfill).toHaveBeenCalledWith(expect.objectContaining({ status: 204, body: '' }))
  })
  it('matches the quality server default and explicit backend origin overrides', () => {
    vi.stubEnv('PLAYWRIGHT_QUALITY_PORT', '6182')
    vi.stubEnv('PLAYWRIGHT_API_URL', undefined)
    vi.stubEnv('PLAYWRIGHT_BACKEND_URL', undefined)
    expect(qualityOrigins()).toEqual({ appOrigin: 'http://localhost:6182', backendOrigin: 'http://127.0.0.1:8182' })
    vi.stubEnv('PLAYWRIGHT_API_URL', 'http://localhost:8030/api')
    expect(qualityOrigins().backendOrigin).toBe('http://localhost:8030')
  })
  it('explicitly enables public templates and import while leaving background generation and unknown features closed', () => {
    expect(QUALITY_FEATURES).toMatchObject({ compile: true, a09: true, b04: true, b06: true, c06: false, d01: false, d18: false })
    expect(QUALITY_FEATURES.unknown_feature).toBeUndefined()
    expect(Object.keys(QUALITY_FEATURES).length).toBeGreaterThanOrEqual(129)
  })
  it('supplies the live plan response shape with both selectable and unavailable choices', () => {
    expect(QUALITY_PLANS.billing).toMatchObject({ feature_enabled: false, mode: 'disabled', available: false })
    expect(QUALITY_PLANS.plans.free.purchasable).toBe(true)
    expect(QUALITY_PLANS.plans.free.features).toMatchObject({ apiAccess: true, apiDailyLimit: 10 })
    expect(QUALITY_PLANS.plans.pro.purchasable).toBe(false)
    expect(QUALITY_PLANS.plans.pro.unavailable_reason).toBeTruthy()
    expect(QUALITY_PLANS.plans.pro.features.apiDailyLimit).toBe(100)
  })
  it('preserves an h2 before public pricing cards with h3 plan names', () => {
    const catalog = readFileSync(new URL('../components/billing/PublicPlanCatalog.tsx', import.meta.url), 'utf8')
    expect(catalog).toMatch(/<h2[^>]*>Available plans<\/h2>[\s\S]*<PricingCard/)
  })
})
