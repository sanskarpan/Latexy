import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import type { AcceptedPreviewRecoveryIdentity } from '@/lib/accepted-artifact-recovery'

const source = ts.createSourceFile('editor/page.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let callback: ts.Expression | undefined
let lifecycleEffect: ts.Expression | undefined
function visit(node: ts.Node) {
  if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'blocksAcceptedArtifactRecoveryAdmission'
      && node.initializer && ts.isCallExpression(node.initializer)) {
    callback = node.initializer.arguments[0]
  }
  if (ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect'
      && node.arguments[1]?.getText(source) === '[offlinePdfOwnerId, resumeId]'
      && node.arguments[0].getText(source).includes('acceptedArtifactRecoveryControllerRef.current?.abort()')) {
    lifecycleEffect = node.arguments[0]
  }
  ts.forEachChild(node, visit)
}
visit(source)
if (!callback) throw new Error('Missing production recovery admission callback')
const code = ts.transpileModule(`(${callback.getText(source)})`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
}).outputText.trim().replace(/;$/, '')

const identity: AcceptedPreviewRecoveryIdentity = {
  ownerId: 'owner-A', resumeId: 'resume-A', generation: 1, source: 'source A', contentRevision: 9,
}

function harness(kind: 'pending' | 'retry', change: Partial<AcceptedPreviewRecoveryIdentity> = {}) {
  const current = { ...identity, ...change }
  const revision = { current: current.contentRevision }
  const blocks = runInNewContext(code, {
    offlinePdfIdentityRef: { current }, resumeContentRevisionRef: revision,
    acceptedArtifactRecoveryPendingIdentity: kind === 'pending' ? identity : null,
    acceptedArtifactRecoveryRetryIdentity: kind === 'retry' ? identity : null,
  }) as (source: string) => boolean
  return { blocks, revision }
}

describe.each(['pending', 'retry'] as const)('production %s recovery admission gate', kind => {
  it('blocks the exact unresolved document version', () => {
    expect(harness(kind).blocks(identity.source)).toBe(true)
  })

  it.each([
    { ownerId: 'owner-B' }, { resumeId: 'resume-B' }, { generation: 2 }, { contentRevision: 10 },
  ])('does not apply an old gate to a different identity: %o', change => {
    expect(harness(kind, change).blocks(identity.source)).toBe(false)
  })

  it('does not block a newly saved revision after editing away and reverting the text', () => {
    const h = harness(kind)
    expect(h.blocks(identity.source)).toBe(true)
    h.revision.current = 10
    expect(h.blocks('source B')).toBe(false)
    h.revision.current = 11
    expect(h.blocks(identity.source)).toBe(false)
  })

  it('keeps the unresolved version blocked if text is reverted without saving a new revision', () => {
    const h = harness(kind)
    expect(h.blocks('source B')).toBe(false)
    expect(h.blocks(identity.source)).toBe(true)
  })
})

it('aborts the current manual retry when its document scope is left', () => {
  if (!lifecycleEffect) throw new Error('Missing recovery lifecycle cleanup')
  const effectCode = ts.transpileModule(`(${lifecycleEffect.getText(source)})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText.trim().replace(/;$/, '')
  const initial = { abort: vi.fn() }
  const manualRetry = { abort: vi.fn() }
  const ref = { current: initial as { abort: () => void } | null }
  const setup = runInNewContext(effectCode, { acceptedArtifactRecoveryControllerRef: ref }) as () => () => void
  const cleanup = setup()
  ref.current = manualRetry
  cleanup()
  expect(manualRetry.abort).toHaveBeenCalledOnce()
  expect(initial.abort).not.toHaveBeenCalled()
  expect(ref.current).toBeNull()
})
