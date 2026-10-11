import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const ast = ts.createSourceFile('plan-catalog.spec.ts', readFileSync(
  new URL('../../e2e/plan-catalog.spec.ts', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)

function expression(name: string) {
  let result = ''
  function visit(node: ts.Node) {
    if (!result && ts.isCallExpression(node) && node.expression.getText(ast) === `page.${name}`) {
      if (name === 'addInitScript') result = node.arguments[0].getText(ast)
      else if (node.arguments[0]?.getText(ast) === "'**/subscription/plans'") result = node.arguments[1].getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(result).not.toBe('')
  return ts.transpileModule(`var callback = ${result}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
}

function harness() {
  class Element {
    constructor(readonly textContent = 'Try again', readonly cardText: string | null = "Couldn't load billing info Temporary pricing outage") {}
    closest(selector: string) { return selector === 'button' ? this : this.cardText === null ? null : { textContent: this.cardText } }
  }
  let click!: (event: { isTrusted: boolean; target: unknown }) => void
  const scope = {
    window: {} as { __pricingRetryDispatches?: number }, Element, expect,
    document: { addEventListener: vi.fn((_type: string, listener: typeof click, capture: boolean) => { expect(capture).toBe(true); click = listener }) },
    page: { evaluate: (read: () => number) => read() },
    outageRequests: 0, recoveredRequests: 0,
    makeCatalog: () => ({ plans: { pro: { name: 'Pro' } } }),
  }
  runInNewContext(`${expression('addInitScript')}\ncallback()`, scope)
  const route = runInNewContext(`${expression('route')}\ncallback`, scope) as (route: unknown) => Promise<unknown>
  const fulfill = vi.fn()
  const request = (token = 'catalog-token') => route({ request: () => ({ headers: () => ({ authorization: `Bearer ${token}` }) }), fulfill })
  return { scope, Element, click: (isTrusted = true, target: unknown = new Element()) => click({ isTrusted, target }), request, fulfill }
}

describe('pricing retry browser fixture causality', () => {
  it('keeps automatic refetches failed until the real scoped Retry action, then recovers exactly once', async () => {
    const h = harness()
    await h.request(); await h.request(); await h.request()
    expect(h.fulfill.mock.calls.map(([response]) => response.status)).toEqual([503, 503, 503])
    expect(h.scope.recoveredRequests).toBe(0)
    h.click()
    await h.request()
    expect(h.scope.window.__pricingRetryDispatches).toBe(1)
    expect(h.scope.outageRequests).toBe(3)
    expect(h.scope.recoveredRequests).toBe(1)
    expect(h.fulfill.mock.calls[3][0].json.plans.pro.name).toBe('Pro')
  })

  it('does not recover for synthetic, unrelated, or toast-only clicks', async () => {
    const h = harness()
    h.click(false)
    h.click(true, new h.Element('Monthly'))
    h.click(true, new h.Element('Try again', 'Temporary pricing outage'))
    h.click(true, new h.Element('Try again', null))
    h.click(true, {})
    await h.request()
    expect(h.scope.window.__pricingRetryDispatches).toBeUndefined()
    expect(h.fulfill).toHaveBeenCalledWith({ status: 503, json: { detail: 'Temporary pricing outage' } })
    expect(h.scope.recoveredRequests).toBe(0)
  })

  it('cannot recover a pricing request from a different auth owner', async () => {
    const h = harness()
    h.click()
    await expect(h.request('other-token')).rejects.toThrow()
    expect(h.fulfill).not.toHaveBeenCalled()
    expect(h.scope.recoveredRequests).toBe(0)
  })
})
