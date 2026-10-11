import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const SOURCE = readFileSync(new URL('../components/DiffViewerModal.tsx', import.meta.url), 'utf8')
const AST = ts.createSourceFile('DiffViewerModal.tsx', SOURCE, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function extractCheckpointFetchEffect() {
  let expression: ts.Expression | undefined
  function visit(node: ts.Node) {
    if (
      ts.isCallExpression(node)
      && node.expression.getText(AST) === 'useEffect'
      && node.arguments[0]
      && ts.isArrowFunction(node.arguments[0])
      && node.arguments[0].getText(AST).includes('apiClient.getCheckpointContent')
    ) {
      expression = node.arguments[0]
    }
    ts.forEachChild(node, visit)
  }
  visit(AST)
  expect(expression, 'checkpoint fetch effect').toBeDefined()
  const javascript = ts.transpileModule(`const effect = ${expression!.getText(AST)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return javascript
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

async function flushPromises() {
  await new Promise((resolve) => setTimeout(resolve, 0))
}

function checkpointFetchHarness() {
  let token = 'owner-a-token'
  const pending = deferred<{ optimized_latex: string }>()
  const calls: Array<{ resumeId: string; checkpointId: string; context: { authToken: string; isCurrent: () => boolean } }> = []
  const setters = {
    leftLatex: vi.fn(),
    rightLatex: vi.fn(),
    leftLabel: vi.fn(),
    rightLabel: vi.fn(),
    loading: vi.fn(),
    error: vi.fn(),
    diffStats: vi.fn(),
  }
  const mountedRef = { current: true }
  const resumeIdRef = { current: 'resume-a' }
  const ownerIdRef = { current: 'owner-a' }
  const restoreGenerationRef = { current: 10 }
  const scope = {
    apiClient: {
      getAuthToken: () => token,
      getCheckpointContent: (resumeId: string, checkpointId: string, context: typeof calls[number]['context']) => {
        calls.push({ resumeId, checkpointId, context })
        return pending.promise
      },
    },
    checkpointA: { id: 'checkpoint-a', created_at: '2026-01-01T00:00:00Z' },
    checkpointB: null,
    resumeId: 'resume-a',
    ownerId: 'owner-a',
    currentLatex: 'current latex',
    isParentDiffMode: false,
    parentLatex: undefined,
    parentTitle: undefined,
    variantLatex: undefined,
    variantTitle: undefined,
    mountedRef,
    resumeIdRef,
    ownerIdRef,
    restoreGenerationRef,
    setLeftLatex: setters.leftLatex,
    setRightLatex: setters.rightLatex,
    setLeftLabel: setters.leftLabel,
    setRightLabel: setters.rightLabel,
    setLoading: setters.loading,
    setError: setters.error,
    setDiffStats: setters.diffStats,
    makeLabel: () => 'Checkpoint A',
    toast: { error: vi.fn() },
  }
  const effect = new Function(...Object.keys(scope), `${extractCheckpointFetchEffect()}; return effect`)(
    ...Object.values(scope),
  ) as () => (() => void) | undefined
  return { effect, pending, calls, setters, ownerIdRef, restoreGenerationRef, setToken: (next: string) => { token = next } }
}

describe('DiffViewerModal keyboard lifecycle', () => {
  it('attaches Escape handling before the visible modal is painted', () => {
    expect(SOURCE).toContain('useLayoutEffect(() => {')
    expect(SOURCE).toContain("if (e.key === 'Escape')")
    expect(SOURCE).toContain("window.addEventListener('keydown', handler)")
  })

  it('uses server recovery for stamped checkpoints and gates raw source restores on c01', () => {
    expect(SOURCE).toContain('apiClient.restoreOptimization(requestResumeId, confirmRestore.checkpointId, {')
    expect(SOURCE).toContain('onRestore(latex)')
    expect(SOURCE).toContain("canRef.current('c01')")
    expect(SOURCE).toContain("(!isParentDiffMode || can('c01')) && onRestore")
    expect(SOURCE).toContain('restoreInFlightRef.current')
    expect(SOURCE).toContain('ownerIdRef.current !== requestOwnerId')
    expect(SOURCE).toContain('restoreGenerationRef.current === restoreGeneration')
  })

  it('binds checkpoint reads to account, document, and comparison generation', () => {
    expect(SOURCE).toContain('apiClient.getCheckpointContent(requestResumeId, checkpointA.id, accountContext)')
    expect(SOURCE).toContain('apiClient.getCheckpointContent(requestResumeId, checkpointB.id, accountContext)')
    expect(SOURCE).toContain('ownerIdRef.current === requestOwnerId')
    expect(SOURCE).toContain('apiClient.getAuthToken() === requestToken')
    expect(SOURCE).toContain('restoreGenerationRef.current === requestGeneration')
    expect(SOURCE).toContain('setLeftLatex(null)')
    expect(SOURCE).toContain('setRightLatex(null)')
  })

  it('drops a delayed checkpoint read across an owner A-to-B-to-A transition', async () => {
    const h = checkpointFetchHarness()
    const cleanup = h.effect()
    expect(h.calls).toHaveLength(1)
    expect(h.calls[0].context.authToken).toBe('owner-a-token')
    expect(h.calls[0].context.isCurrent()).toBe(true)

    // Model account B becoming current and then A again while the already
    // dispatched A read remains in flight. Identity alone matches again, but
    // the layout-effect generation makes the original request stale.
    h.ownerIdRef.current = 'owner-b'
    h.restoreGenerationRef.current += 1
    h.setToken('owner-b-token')
    h.ownerIdRef.current = 'owner-a'
    h.restoreGenerationRef.current += 1
    h.setToken('owner-a-token')
    expect(h.calls[0].context.isCurrent()).toBe(false)

    const beforeResolve = Object.fromEntries(Object.entries(h.setters).map(([key, setter]) => [key, setter.mock.calls.length]))
    h.pending.resolve({ optimized_latex: 'private owner A checkpoint' })
    await flushPromises()
    cleanup?.()

    expect(h.setters.leftLatex).not.toHaveBeenCalled()
    expect(h.setters.leftLabel).not.toHaveBeenCalled()
    expect(h.setters.rightLatex).toHaveBeenCalledTimes(beforeResolve.rightLatex)
    expect(h.setters.rightLabel).toHaveBeenCalledTimes(beforeResolve.rightLabel)
    expect(h.setters.error).toHaveBeenCalledTimes(beforeResolve.error)
    expect(h.setters.loading).toHaveBeenCalledTimes(beforeResolve.loading)
  })

  it('applies a checkpoint read that remains in the same owner and document generation', async () => {
    const h = checkpointFetchHarness()
    const cleanup = h.effect()
    expect(h.calls[0].context.isCurrent()).toBe(true)
    h.pending.resolve({ optimized_latex: 'owner A checkpoint' })
    await flushPromises()
    cleanup?.()

    expect(h.setters.leftLatex).toHaveBeenCalledWith('owner A checkpoint')
    expect(h.setters.leftLabel).toHaveBeenCalledWith('Checkpoint A')
    expect(h.setters.loading).toHaveBeenLastCalledWith(false)
    expect(h.setters.error).toHaveBeenCalledWith(false)
  })
})
