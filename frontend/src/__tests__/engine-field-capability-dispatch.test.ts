import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = ts.createSourceFile('editor/page.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const handlers = ['saveResumeField', 'reorderResumeStructure'] as const
function callback(name: typeof handlers[number], scope: Record<string, unknown>) {
  let expression: ts.Expression | undefined
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name && node.initializer && ts.isCallExpression(node.initializer)) expression = node.initializer.arguments[0]
    ts.forEachChild(node, visit)
  }
  visit(source)
  expect(expression, name).toBeDefined()
  const code = ts.transpileModule(`const action = ${expression!.getText(source)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return runInNewContext(`${code}\naction`, scope) as (...args: unknown[]) => Promise<void>
}
function deferred() {
  let resolve!: () => void
  const promise = new Promise<void>((done) => { resolve = done })
  return { promise, resolve }
}
function harness(name: typeof handlers[number]) {
  const features = new Set(['b10', 'c01'])
  const authReady = deferred(), response = deferred()
  const dispatch = vi.fn()
  const setEngineDocument = vi.fn(), setLatexContent = vi.fn(), setSavedSnapshot = vi.fn(), queuePreview = vi.fn()
  const result = { document: { content_revision: 5 }, latex_content: 'saved source' }
  const mutate = vi.fn(async (_resume: unknown, _body: unknown, context: { isCurrent: () => boolean }) => {
    await authReady.promise
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch()
    await response.promise
    return result
  })
  const action = callback(name, {
    Error, performance, canRef: { current: (key: string) => features.has(key) },
    sourceAtRenderRef: { current: 'current source' }, engineSupported: true,
    visibleEngineDocument: { source_mode: 'managed', source_sha256: 'current hash', content_revision: 4 },
    engineDocumentIdentityRef: { current: 'owner:resume' }, sessionUserId: 'owner', resumeId: 'resume',
    sourceHash: 'current hash', canEditDocument: true, offlinePdfOwnerId: 'owner',
    offlinePdfIdentityRef: { current: { generation: 2 } }, isCurrentOfflinePdfIdentity: () => true,
    apiClient: { getAuthToken: () => 'owner-token', patchEngineDocument: mutate, reorderEngineDocument: mutate },
    setEngineDocument, setLatexContent, setSavedSnapshot, queuePreview,
  })
  return {
    features, authReady, response, dispatch, setEngineDocument, setLatexContent, queuePreview, result,
    start: () => name === 'saveResumeField'
      ? action({ node_id: 'field', node_revision: 'rev' }, 'Edited field')
      : action('section', ['entry-b', 'entry-a']),
  }
}

for (const name of handlers) {
  describe(`${name} capability dispatch and admitted recovery`, () => {
    it.each(['b10', 'c01'])('suppresses actual dispatch after %s revocation during auth refresh', async (feature) => {
      const h = harness(name)
      const pending = h.start()
      const rejected = expect(pending).rejects.toThrow('context changed before dispatch')
      h.features.delete(feature)
      h.authReady.resolve()
      await rejected
      expect(h.dispatch).not.toHaveBeenCalled()
      expect(h.setEngineDocument).not.toHaveBeenCalled()
      expect(h.setLatexContent).not.toHaveBeenCalled()
      expect(h.queuePreview).not.toHaveBeenCalled()
    })

    it.each(['b10', 'c01'])('recovers an owned successful write admitted before %s revocation', async (feature) => {
      const h = harness(name)
      const pending = h.start()
      h.authReady.resolve()
      await Promise.resolve(); await Promise.resolve()
      expect(h.dispatch).toHaveBeenCalledOnce()
      h.features.delete(feature)
      h.response.resolve()
      await pending
      expect(h.setEngineDocument).toHaveBeenCalledExactlyOnceWith(h.result.document)
      expect(h.setLatexContent).toHaveBeenCalledExactlyOnceWith('saved source')
      expect(h.queuePreview).toHaveBeenCalledExactlyOnceWith('saved source', expect.any(Number), true)
    })
  })
}


it('hides legacy candidate application after d03 denial while retaining the result panel', () => {
  let expression: ts.Expression | undefined
  function visit(node: ts.Node) {
    if ((ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) && node.tagName.getText(source) === 'AIPanel') {
      const attribute = node.attributes.properties.find((item) => ts.isJsxAttribute(item) && item.name.getText(source) === 'canEditDocument') as ts.JsxAttribute
      expression = (attribute.initializer as ts.JsxExpression).expression
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  expect(expression).toBeDefined()
  expect(runInNewContext(expression!.getText(source), { canEditDocument: true, can: () => false })).toBe(false)
  expect(runInNewContext(expression!.getText(source), { canEditDocument: true, can: () => true })).toBe(true)
  expect(runInNewContext(expression!.getText(source), { canEditDocument: false, can: () => true })).toBe(false)
})
