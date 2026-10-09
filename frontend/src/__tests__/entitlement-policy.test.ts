import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { BASELINE_FEATURES, isFeatureAllowed, parseEffectiveFeatures } from '@/lib/entitlement-policy'
import { capabilityForRoute, exportCapabilities } from '@/lib/capability-ui-policy'
import { entitlementBlocker, matchesFeatureSearch, patchEntitlementCell, createEntitlementWriteLock } from '@/lib/admin-entitlements'
import type { AdminEntitlementsState, EntitlementFeatureDef } from '@/lib/api-client'

const parent: EntitlementFeatureDef = { key: 'editor_ai', label: 'Editor AI', category: 'editor', gateable: true }
const child: EntitlementFeatureDef = { key: 'd06', label: 'Writing assistant', category: 'editor', gateable: true, parent_key: 'editor_ai', inventory_id: 'D06', description: 'Improve selected text' }
function state(): AdminEntitlementsState {
  return { registry: [parent, child], kill_switches: { editor_ai: true, d06: true }, matrix: { pro: { editor_ai: true, d06: true }, pro_annual: { editor_ai: true, d06: true } }, plan_families: ['pro'], plan_keys: ['pro', 'pro_annual'], plan_family_by_key: { pro: 'pro', pro_annual: 'pro' } }
}

describe('effective capability policy', () => {
  it('keeps the offline baseline exactly aligned with the server immutable catalog', () => {
    const catalog = JSON.parse(readFileSync(resolve(__dirname, '../../../backend/app/core/capability_catalog.json'), 'utf8')) as EntitlementFeatureDef[]
    const baseline = ['compile', ...catalog.filter((entry) => !entry.gateable).map((entry) => entry.key)]
    expect([...BASELINE_FEATURES].sort()).toEqual(baseline.sort())
  })
  it('fails closed for absent, unknown, inherited object properties and nonboolean values', () => {
    expect(isFeatureAllowed({}, 'd06')).toBe(false)
    expect(isFeatureAllowed({}, 'typo')).toBe(false)
    expect(isFeatureAllowed({}, 'toString')).toBe(false)
    expect(isFeatureAllowed(Object.create({ d06: true }), 'd06')).toBe(false)
    expect(isFeatureAllowed({ d06: false }, 'd06')).toBe(false)
    expect(isFeatureAllowed({ d06: true }, 'd06')).toBe(true)
  })
  it('preserves only explicitly immutable baseline access through failures', () => {
    for (const key of BASELINE_FEATURES) expect(isFeatureAllowed({}, key)).toBe(true)
    expect(isFeatureAllowed({ c05: false }, 'c05')).toBe(true)
    for (const key of ['a06', 'b08', 'b09', 'c02', 'c03', 'c06', 'c22', 'd01', 'f01']) expect(isFeatureAllowed({}, key)).toBe(false)
  })
  it('validates responses rather than coercing malformed grants', () => {
    expect(parseEffectiveFeatures({ d06: true, c06: false })).toEqual({ d06: true, c06: false })
    for (const invalid of [undefined, null, [], 'all', { d06: 'false' }, { d06: 1 }]) expect(() => parseEffectiveFeatures(invalid)).toThrow()
  })
  it('guards optional direct routes while preserving owned source, history and security', () => {
    expect(capabilityForRoute('/workspace/builder/r1')).toBe('b08')
    expect(capabilityForRoute('/workspace/r1/optimize')).toBe('d01')
    expect(capabilityForRoute('/workspace/r1/batch-tailor')).toBe('d05')
    for (const path of ['/workspace/r1/edit', '/workspace/history', '/workspace', '/settings', '/byok', '/developer', '/billing', '/admin', '/reset-password']) expect(capabilityForRoute(path)).toBeNull()
  })
})

describe('admin effective permission explanations', () => {
  it('searches inventory IDs, descriptions and parent keys', () => {
    expect(matchesFeatureSearch(child, 'D06 selected')).toBe(true)
    expect(matchesFeatureSearch(child, 'editor_ai')).toBe(true)
    expect(matchesFeatureSearch(child, 'unrelated')).toBe(false)
  })
  it('explains global parent blocks even if child switches are on', () => {
    const data = state(); data.kill_switches.editor_ai = false
    expect(entitlementBlocker(data, child, 'pro_annual')).toBe('Editor AI: globally disabled')
  })
  it('combines family, SKU and ancestor restrictions', () => {
    const data = state(); data.matrix.pro.editor_ai = false
    expect(entitlementBlocker(data, child, 'pro_annual')).toBe('Editor AI: disabled for pro')
    data.matrix.pro.editor_ai = true; data.matrix.pro_annual.d06 = false
    expect(entitlementBlocker(data, child, 'pro_annual')).toBe('Writing assistant: disabled for pro_annual')
    expect(entitlementBlocker(data, child, 'pro')).toBeNull()
  })
  it('does not display immutable capabilities as disabled', () => {
    const data = state(); data.kill_switches.d06 = false
    expect(entitlementBlocker(data, { ...child, gateable: false }, 'pro')).toBeNull()
  })
  it('fails closed on invalid graph data', () => {
    const data = state(); data.registry[0] = { ...parent, parent_key: 'd06' }
    expect(entitlementBlocker(data, child)).toBe('Invalid parent configuration')
    expect(entitlementBlocker(state(), { ...child, parent_key: 'missing' })).toBe('Missing parent configuration')
  })
})


describe('admin writes and recovery exports', () => {
  it('merges out-of-order results for different cells without replaying stale whole snapshots', () => {
    let current = state()
    current = patchEntitlementCell(current, 'global', 'd06', false)!
    current = patchEntitlementCell(current, 'pro', 'editor_ai', false)!
    current = patchEntitlementCell(current, 'pro', 'editor_ai', false)!
    current = patchEntitlementCell(current, 'global', 'd06', false)!
    expect(current.kill_switches.d06).toBe(false)
    expect(current.matrix.pro.editor_ai).toBe(false)
    expect(current.matrix.pro_annual.editor_ai).toBe(true)
    // A failed first edit rolls back only its own cell.
    current = patchEntitlementCell(current, 'global', 'd06', true)!
    expect(current.matrix.pro.editor_ai).toBe(false)
  })
  it('synchronously locks repeated clicks while allowing independent cells', () => {
    const lock = createEntitlementWriteLock()
    expect(lock.acquire('pro:d06')).toBe(true)
    expect(lock.acquire('pro:d06')).toBe(false)
    expect(lock.acquire('basic:d06')).toBe(true)
    lock.release('pro:d06')
    expect(lock.acquire('pro:d06')).toBe(true)
  })
  it('keeps PDF and source accessible while independently restricting enhanced exports', () => {
    expect(exportCapabilities('pdf')).toEqual([])
    expect(exportCapabilities('tex')).toEqual([])
    expect(exportCapabilities('json')).toEqual(['h01', 'b07'])
    expect(exportCapabilities('svg')).toEqual(['h02'])
    expect(exportCapabilities('figma')).toEqual(['h03'])
    expect(exportCapabilities('email')).toEqual(['h05'])
    expect(exportCapabilities('google_drive')).toEqual(['g06'])
  })
})
