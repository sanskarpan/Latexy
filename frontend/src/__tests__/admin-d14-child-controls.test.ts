import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import { entitlementAncestryLabels, entitlementBlocker, matchesFeatureKind, matchesFeatureSearch, registryControlCounts } from '@/lib/admin-entitlements'
import type { AdminEntitlementsState, EntitlementFeatureDef } from '@/lib/api-client'

const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image']
function state(): AdminEntitlementsState {
  const parent: EntitlementFeatureDef = { key: 'ai_writing', label: 'AI Writing Tools', category: 'editor', gateable: true, control_kind: 'parent' }
  const product: EntitlementFeatureDef = { key: 'd14', label: 'LaTeX generator', category: 'editor', gateable: true, control_kind: 'product', inventory_id: 'D14', product_inventory_id: 'D14', parent_key: parent.key }
  const registry = [parent, product, ...leaves.map((key) => ({ key, label: key, category: 'editor', gateable: true, control_kind: 'subfeature' as const, inventory_id: null, product_inventory_id: 'D14', parent_key: product.key }))]
  const enabled = () => Object.fromEntries(registry.map(({ key }) => [key, true]))
  return { registry, kill_switches: enabled(), matrix: { pro: enabled(), pro_annual: enabled() }, plan_families: ['pro'], plan_keys: ['pro', 'pro_annual'], plan_family_by_key: { pro: 'pro', pro_annual: 'pro' }, roles: ['anonymous', 'user', 'support', 'admin'], role_matrix: Object.fromEntries(['anonymous', 'user', 'support', 'admin'].map((role) => [role, enabled()])) }
}

function realGrouped(data: AdminEntitlementsState, kindFilter: string, query = '') {
  const source = ts.createSourceFile('admin.tsx', readFileSync(new URL('../app/admin/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'grouped' && node.initializer && ts.isCallExpression(node.initializer)) expression = node.initializer.arguments[0].getText(source)
    ts.forEachChild(node, visit)
  }
  visit(source)
  const js = ts.transpileModule(`const run = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return new Function('state', 'kindFilter', 'query', 'categoryFilter', 'CATEGORY_ORDER', 'matchesFeatureSearch', 'matchesFeatureKind', `${js}; return run()`)(data, kindFilter, query, 'all', ['editor'], matchesFeatureSearch, matchesFeatureKind) as Array<{ category: string; features: EntitlementFeatureDef[] }>
}

describe('real admin D14 child inventory filtering', () => {
  it('filters child operations independently of product and parent controls', () => {
    const data = state()
    expect(realGrouped(data, 'subfeatures').flatMap(({ features }) => features.map(({ key }) => key))).toEqual(leaves)
    expect(realGrouped(data, 'groups').flatMap(({ features }) => features.map(({ key }) => key))).toEqual(['ai_writing'])
    expect(realGrouped(data, 'products').flatMap(({ features }) => features.map(({ key }) => key))).toEqual(['d14'])
    expect(realGrouped(data, 'subfeatures', 'D14 math').flatMap(({ features }) => features.map(({ key }) => key))).toEqual(['d14_math_text', 'd14_math_image'])
    expect(registryControlCounts(data.registry)).toEqual({ parent: 1, product: 1, subfeature: 5 })
  })
  it('keeps the real catalog at 129 products, five children and 31 parents', () => {
    const products = JSON.parse(readFileSync(new URL('../../../backend/app/core/capability_catalog.json', import.meta.url), 'utf8')) as EntitlementFeatureDef[]
    const children = JSON.parse(readFileSync(new URL('../../../backend/app/core/capability_subfeature_catalog.json', import.meta.url), 'utf8')) as EntitlementFeatureDef[]
    const registry = [...products.map((feature) => ({ ...feature, control_kind: 'product' as const })), ...children]
    expect(registryControlCounts(registry)).toEqual({ parent: 0, product: 129, subfeature: 5 })
    expect(children.map(({ key }) => key)).toEqual(leaves)
    expect(products.filter(({ gateable }) => !gateable)).toHaveLength(16)
  })
  it('shows full ancestry and identifies outer, product and leaf blockers', () => {
    const data = state(); const child = data.registry[2]
    expect(entitlementAncestryLabels(data, child)).toBe('LaTeX generator → AI Writing Tools')
    for (const key of ['d14_latex', 'd14', 'ai_writing']) {
      data.kill_switches[key] = false
      expect(entitlementBlocker(data, child)).toContain(`${data.registry.find((feature) => feature.key === key)!.label}: globally disabled`)
      data.kill_switches[key] = true
      data.role_matrix!.admin[key] = false
      expect(entitlementBlocker(data, child, undefined, 'admin')).toContain('disabled for role admin')
      data.role_matrix!.admin[key] = true
      data.matrix.pro[key] = false
      expect(entitlementBlocker(data, child, 'pro_annual')).toContain('disabled for pro')
      data.matrix.pro[key] = true
      data.matrix.pro_annual[key] = false
      expect(entitlementBlocker(data, child, 'pro_annual')).toContain('disabled for pro_annual')
      data.matrix.pro_annual[key] = true
    }
    data.kill_switches.d14_latex = false
    expect(entitlementBlocker(data, data.registry[3], 'pro_annual', 'admin')).toBeNull()
  })
  it('rejects missing and cyclic ancestors without hiding configuration errors', () => {
    const data = state(); const child = data.registry[2]
    data.registry[0].parent_key = child.key
    expect(entitlementAncestryLabels(data, child)).toBe('Invalid parent configuration')
    data.registry[0].parent_key = 'missing'
    expect(entitlementAncestryLabels(data, child)).toBe('Missing parent configuration')
  })
})
