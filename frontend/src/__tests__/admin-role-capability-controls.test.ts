import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { createEntitlementWriteLock, patchEntitlementCell } from '@/lib/admin-entitlements'
import type { AdminEntitlementsState } from '@/lib/api-client'

const source = ts.createSourceFile('admin.tsx', readFileSync(new URL('../app/admin/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function fixture(key = 'b03') {
  return { registry: [], kill_switches: { [key]: true }, matrix: { pro: { [key]: true }, pro_annual: { [key]: true } }, plan_families: ['pro'], roles: ['user', 'admin'], role_matrix: { user: { [key]: true }, admin: { [key]: true } } } as AdminEntitlementsState
}
function harness(key = 'b03') {
  let data = fixture(key)
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'toggle' && node.initializer && ts.isCallExpression(node.initializer)) expression = node.initializer.arguments[0].getText(source)
    ts.forEachChild(node, visit)
  }
  visit(source)
  const apiClient = { updateKillSwitch: vi.fn(), updateMatrixCell: vi.fn(), updateRoleCell: vi.fn(), getAdminEntitlements: vi.fn() }
  const scope = {
    apiClient, pendingRef: { current: createEntitlementWriteLock() }, mounted: { current: true },
    setState: (fn: (state: AdminEntitlementsState) => AdminEntitlementsState) => { data = fn(data) },
    patchEntitlementCell, markBusy: vi.fn(), clearBusy: vi.fn(), setError: vi.fn(), toast: { error: vi.fn() }, window: { dispatchEvent: vi.fn() }, Event,
  }
  const js = ts.transpileModule(`const run = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const run = new Function(...Object.keys(scope), `${js}; return run`)(...Object.values(scope)) as (scope: string, key: string, next: boolean) => Promise<void>
  return { ...scope, run, state: () => data }
}
describe('admin role control dispatch and conflicts', () => {
  it.each(['global', 'pro', 'role:admin'])('sends expected old value for %s and only patches its own cell', async (scope) => {
    const h = harness(); const response = fixture()
    response.kill_switches.b03 = false; response.matrix.pro.b03 = false; response.role_matrix!.admin.b03 = false
    h.apiClient.updateKillSwitch.mockResolvedValue(response); h.apiClient.updateMatrixCell.mockResolvedValue(response); h.apiClient.updateRoleCell.mockResolvedValue(response)
    await h.run(scope, 'b03', false)
    const expected = scope === 'global' ? h.apiClient.updateKillSwitch : scope === 'pro' ? h.apiClient.updateMatrixCell : h.apiClient.updateRoleCell
    expect(expected).toHaveBeenCalledWith(...(scope === 'global' ? ['b03', false, true] : [scope === 'pro' ? 'pro' : 'admin', 'b03', false, true]))
    expect(h.state().kill_switches.b03).toBe(scope !== 'global')
    expect(h.state().matrix.pro.b03).toBe(scope !== 'pro')
    expect(h.state().role_matrix?.admin.b03).toBe(scope !== 'role:admin')
  })
  it('refreshes a conflicting switch and does not overwrite independent optimistic edits', async () => {
    const h = harness(); const fresh = fixture(); fresh.role_matrix!.admin.b03 = false
    h.apiClient.updateRoleCell.mockRejectedValue(new Error('HTTP 409: permission changed'))
    h.apiClient.getAdminEntitlements.mockResolvedValue(fresh)
    h.apiClient.updateMatrixCell.mockImplementation(() => new Promise(() => {}))
    void h.run('pro', 'b03', false)
    await h.run('role:admin', 'b03', false)
    expect(h.apiClient.getAdminEntitlements).toHaveBeenCalledOnce()
    expect(h.state().matrix.pro.b03).toBe(false)
    expect(h.state().role_matrix?.admin.b03).toBe(false)
    expect(h.toast.error).toHaveBeenCalledWith(expect.stringContaining('changed elsewhere'))
  })
  it('locks out further editing if an uncertain write cannot be verified', async () => {
    const h = harness(); h.apiClient.updateRoleCell.mockRejectedValue(new Error('offline')); h.apiClient.getAdminEntitlements.mockRejectedValue(new Error('offline'))
    await h.run('role:user', 'b03', false)
    expect(h.setError).toHaveBeenCalledWith(expect.stringContaining('Reload this page'))
  })
})


describe('real admin child operation writes', () => {
  const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image']
  it.each(leaves.flatMap((key) => ['global', 'pro', 'pro_annual', 'role:admin'].map((scope) => [key, scope])))('writes %s in %s with expected-state comparison', async (key, scope) => {
    const h = harness(key); const response = fixture(key)
    response.kill_switches[key] = false; response.matrix.pro[key] = false; response.matrix.pro_annual[key] = false; response.role_matrix!.admin[key] = false
    h.apiClient.updateKillSwitch.mockResolvedValue(response); h.apiClient.updateMatrixCell.mockResolvedValue(response); h.apiClient.updateRoleCell.mockResolvedValue(response)
    await h.run(scope, key, false)
    const method = scope === 'global' ? h.apiClient.updateKillSwitch : scope.startsWith('role:') ? h.apiClient.updateRoleCell : h.apiClient.updateMatrixCell
    expect(method).toHaveBeenCalledWith(...(scope === 'global' ? [key, false, true] : [scope.startsWith('role:') ? 'admin' : scope, key, false, true]))
    expect(h.state().kill_switches[key]).toBe(scope !== 'global')
    expect(h.state().matrix.pro[key]).toBe(scope !== 'pro')
    expect(h.state().matrix.pro_annual[key]).toBe(scope !== 'pro_annual')
    expect(h.state().role_matrix!.admin[key]).toBe(scope !== 'role:admin')
  })
  it('serializes repeated writes to the same child cell and refreshes conflicts', async () => {
    const key = leaves[0]; const h = harness(key); let resolve: (state: AdminEntitlementsState) => void = () => {}
    h.apiClient.updateRoleCell.mockImplementation(() => new Promise((done) => { resolve = done }))
    const first = h.run('role:admin', key, false)
    await h.run('role:admin', key, false)
    expect(h.apiClient.updateRoleCell).toHaveBeenCalledOnce()
    const updated = fixture(key); updated.role_matrix!.admin[key] = false; resolve(updated)
    await first
    h.apiClient.updateRoleCell.mockRejectedValue(new Error('HTTP 409: another operator changed the child'))
    h.apiClient.getAdminEntitlements.mockResolvedValue(updated)
    await h.run('role:admin', key, true)
    expect(h.state().role_matrix!.admin[key]).toBe(false)
    expect(h.toast.error).toHaveBeenCalledWith(expect.stringContaining('changed elsewhere'))
  })
})
