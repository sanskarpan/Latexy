import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { applyGuestBulletPatch, GUEST_ORIGINAL_BULLET, projectGuestBullet } from '../../e2e/quality/guest-engine-fixture'
import { FIRST_USE_ENGINE_RESUME_TEMPLATE } from '@/lib/first-use-resume'

const digest = (text: string) => createHash('sha256').update(text).digest('hex')
const source = FIRST_USE_ENGINE_RESUME_TEMPLATE
const edited = (count: number) => `Built internal design system used across ${count} product surfaces`
function patchBody(latex_content: string, text: string) {
  const document = projectGuestBullet(latex_content)
  const node = document.nodes[0]
  return { latex_content, expected_source_sha256: document.source_sha256,
    patches: [{ node_id: node.node_id, expected_node_revision: node.node_revision, text }] }
}

// Execute the actual registered browser handlers, not just a parallel mock in
// this test. The old handlers fabricated absent text and returned successful no-ops.
function routeHandler(file: string, path: string) {
  const contents = readFileSync(new URL(`../../e2e/quality/${file}`, import.meta.url), 'utf8')
  const ast = ts.createSourceFile(file, contents, ts.ScriptTarget.Latest, true)
  let expression = ''
  function visit(node: ts.Node) {
    if (!expression && ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)
      && node.expression.name.text === 'route' && node.arguments[0] && ts.isStringLiteral(node.arguments[0])
      && node.arguments[0].text === path) expression = node.arguments[1].getText(ast)
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(expression).not.toBe('')
  const js = ts.transpileModule(`const handler = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const handle = runInNewContext(`${js}\nhandler`, { expect, digest, GUEST_ORIGINAL_BULLET, projectGuestBullet, applyGuestBulletPatch })
  return async (body: unknown) => {
    const fulfill = vi.fn()
    await handle({ request: () => ({ postDataJSON: () => body }), fulfill })
    expect(fulfill).toHaveBeenCalledOnce()
    return fulfill.mock.calls[0][0].json
  }
}

describe('source-bound guest engine browser fixtures', () => {
  it('uses the current /try seed and a real, nonnegative source span', () => {
    const page = readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8')
    expect(page).toContain('FIRST_USE_ENGINE_RESUME_TEMPLATE as DEMO_RESUME_TEMPLATE')
    expect(source).toContain(GUEST_ORIGINAL_BULLET)
    const document = projectGuestBullet(source)
    const node = document.nodes[0]
    expect(node.source_span.start).toBeGreaterThanOrEqual(0)
    expect(source.slice(node.source_span.start, node.source_span.end)).toBe(node.text)
    expect(node.node_revision).toBe(digest(node.text))
    expect(document.source_sha256).toBe(digest(source))
  })

  it.each(['resume-engine-preview.spec.ts', 'resume-preview-recovery.spec.ts'])('executes %s read/patch handlers against the actual seed', async file => {
    const read = routeHandler(file, '**/public/engine/document')
    const patch = routeHandler(file, '**/public/engine/document/patch')
    const initial = await read({ latex_content: source })
    expect(initial.document.nodes[0].text).toBe(GUEST_ORIGINAL_BULLET)
    const result = await patch(patchBody(source, edited(8)))
    expect(result.latex_content).toBe(source.replace(GUEST_ORIGINAL_BULLET, edited(8)))
    expect(result.latex_content).not.toBe(source)
    expect(result.document.nodes[0].text).toBe(edited(8))
    expect(result.document.source_sha256).toBe(digest(result.latex_content))
    expect((await read({ latex_content: result.latex_content })).document).toEqual(result.document)
  })

  it('cancellation recovery applies the second edit to the first edited revision', async () => {
    const patch = routeHandler('resume-preview-recovery.spec.ts', '**/public/engine/document/patch')
    const first = await patch(patchBody(source, edited(8)))
    const second = await patch(patchBody(first.latex_content, edited(9)))
    expect(second.latex_content).toBe(source.replace(GUEST_ORIGINAL_BULLET, edited(9)))
    expect(second.latex_content).not.toContain(edited(8))
    expect(second.document.nodes[0].node_revision).toBe(digest(edited(9)))
    expect(second.document.source_sha256).toBe(digest(second.latex_content))
  })

  it('splices the projected bullet rather than an earlier duplicate in opaque source', () => {
    const duplicate = `% ${GUEST_ORIGINAL_BULLET}\n${source}`
    const result = applyGuestBulletPatch(patchBody(duplicate, edited(8)))
    expect(result.latex_content).toBe(`% ${GUEST_ORIGINAL_BULLET}\n${source.replace(GUEST_ORIGINAL_BULLET, edited(8))}`)
  })

  it.each(['source', 'node', 'id', 'count'] as const)('rejects stale or malformed %s identity instead of accepting a no-op', identity => {
    const body = patchBody(source, edited(8))
    if (identity === 'source') body.expected_source_sha256 = digest('stale source')
    if (identity === 'node') body.patches[0].expected_node_revision = digest('stale text')
    if (identity === 'id') body.patches[0].node_id = 'unknown-node'
    if (identity === 'count') body.patches.push(body.patches[0])
    expect(() => applyGuestBulletPatch(body)).toThrow('stale source or node identity')
  })

  it('does not fabricate an editable node when the source has no bullet', () => {
    expect(() => projectGuestBullet('synthetic source without a bullet')).toThrow('no plain bullet')
  })

  it('asserts and closes only the expected candidate-export toast before interacting with Reject', () => {
    const fixture = readFileSync(new URL('../../e2e/quality/resume-engine-preview.spec.ts', import.meta.url), 'utf8')
    const asserted = fixture.indexOf('await expect(exportWarning).toBeVisible()')
    const closed = fixture.indexOf("await exportToast.getByRole('button', { name: 'Close toast', exact: true }).click()")
    const removed = fixture.indexOf('await expect(exportToast).toHaveCount(0)')
    const rejected = fixture.indexOf("await rejectedSuggestion.getByRole('button', { name: 'Reject', exact: true }).click()")
    expect(fixture).toContain("page.locator('[data-sonner-toast]').filter({ has: exportWarning })")
    expect(asserted).toBeGreaterThan(0)
    expect(closed).toBeGreaterThan(asserted)
    expect(removed).toBeGreaterThan(closed)
    expect(rejected).toBeGreaterThan(removed)
    expect(fixture).not.toContain('force: true')
    expect(fixture).not.toContain('waitForTimeout')
    expect(fixture).toContain('expect(runtimeErrors).toEqual([])')
  })
})
