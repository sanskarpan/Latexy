import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import React from 'react'
import ts from 'typescript'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import { FIRST_USE_ENGINE_RESUME_TEMPLATE } from '@/lib/first-use-resume'
import { applyGuestBulletPatch, GUEST_ORIGINAL_BULLET, projectGuestBullet } from '../../e2e/quality/guest-engine-fixture'

const source = ts.createSourceFile('try/page.tsx', readFileSync(
  new URL('../app/try/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const page = source.statements.find((node): node is ts.FunctionDeclaration =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'TryPage')!
const statements = page.body!.statements
const declaration = (name: string) => statements.filter(ts.isVariableStatement)
  .flatMap(statement => Array.from(statement.declarationList.declarations))
  .find(node => node.name.getText(source) === name)!
const declarationIndex = (name: string) => statements.findIndex(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(item => item.name.getText(source) === name))
const identityCode = statements.slice(declarationIndex('previewRequestIdentityRef'), declarationIndex('activeJobAtRenderRef'))
  .map(node => node.getText(source)).join('\n')
const boundarySource = ts.createSourceFile('AccountContentBoundary.tsx', readFileSync(
  new URL('../components/AccountContentBoundary.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const boundary = boundarySource.statements.find((node): node is ts.FunctionDeclaration =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'AccountContentBoundary')!

function evaluate<T>(expression: string, scope: Record<string, unknown>): T {
  const js = ts.transpileModule(`const result = ${expression}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText
  return runInNewContext(`${js}\nresult`, scope) as T
}
const edited = (count: number) => `Built internal design system used across ${count} product surfaces`
type Patch = Parameters<typeof applyGuestBulletPatch>[0]
type PatchResult = ReturnType<typeof applyGuestBulletPatch>
type Slot = { current?: unknown; value?: unknown; dependencies?: unknown[]; cleanup?: () => void }
const changed = (previous: unknown[] | undefined, next: unknown[]) => !previous || previous.length !== next.length
  || next.some((value, index) => !Object.is(value, previous[index]))

// Execute the actual owner boundary, page save/identity code and preview hook.
// State setters are scoped to each mounted incarnation, matching React's
// unmount semantics; the browser contract verifies form/input DOM behavior.
async function harness() {
  vi.resetModules()
  vi.useFakeTimers()
  let hooks: { slots: Slot[]; effects: Array<() => void> } | undefined
  let index = 0
  vi.doMock('react', () => ({
    useRef: (current: unknown) => hooks!.slots[index++] ??= { current },
    useMemo: (create: () => unknown, dependencies: unknown[]) => {
      const slot = hooks!.slots[index++] ??= {}
      if (changed(slot.dependencies, dependencies)) { slot.value = create(); slot.dependencies = dependencies }
      return slot.value
    },
    useEffect: (effect: () => (() => void) | void, dependencies: unknown[]) => {
      const slot = hooks!.slots[index++] ??= {}
      if (changed(slot.dependencies, dependencies)) {
        slot.dependencies = dependencies
        hooks!.effects.push(() => { slot.cleanup?.(); slot.cleanup = effect() || undefined })
      }
    },
  }))
  const { usePreviewScheduler } = await import('@/hooks/usePreviewScheduler')
  let owner = 'anonymous'
  const boundaryRefs: Array<{ current: unknown }> = []; let boundaryIndex = 0
  const boundaryRender = evaluate<(props: { children: null }) => React.ReactElement>(`(${boundary.parameters.map(node => node.getText(boundarySource)).join(', ')}) => ${boundary.body!.getText(boundarySource)}`, {
    React, Fragment: React.Fragment,
    useRef: (current: unknown) => boundaryRefs[boundaryIndex++] ??= { current },
    useEffect: () => {}, usePathname: () => '/try', isConfirmedSessionUnauthorized, AccountContentScopeProvider: 'AccountContentScopeProvider',
    useSession: () => ({ data: owner === 'anonymous' ? null : { user: { id: owner } }, isPending: false, error: null }),
  })
  const features = new Set(['a09', 'b10', 'c01'])
  const previews = vi.fn(async (_source: string) => 'current-preview')
  const requests: Array<{ body: Patch; resolve: (result: PatchResult) => void }> = []
  const patch = vi.fn((body: Patch) => new Promise<PatchResult>(resolve => requests.push({ body, resolve })))
  function createMount(key: React.Key | null) {
    let content = FIRST_USE_ENGINE_RESUME_TEMPLATE
    let document = projectGuestBullet(content)
    let mounted = true
    let identityRef: { current: unknown } | undefined
    const hookState = { slots: [] as Slot[], effects: [] as Array<() => void> }
    const setLatexContent = vi.fn((next: string) => { if (mounted) content = next })
    const setEngineDocument = vi.fn((next: typeof document) => { if (mounted) document = next })
    let queuePreview: ReturnType<typeof usePreviewScheduler>
    function useRenderIdentity(identity = `${owner}:device`) {
      identityRef = evaluate(`(() => { ${identityCode}; return previewRequestIdentityRef })()`, {
        previewAccountIdentity: identity, useRef: (current: unknown) => identityRef ?? { current },
      })
      hooks = hookState; index = 0
      queuePreview = usePreviewScheduler({ identity, enabled: features.has('c01') && features.has('b10'),
        blocked: false, jobId: null, status: 'idle', submit: previews })
      const effects = hookState.effects; hookState.effects = []; effects.forEach(effect => effect())
    }
    const mount = {
      key, setLatexContent, setEngineDocument, renderIdentity: useRenderIdentity,
      get content() { return content }, get document() { return document },
      save(text: string, engineSupported = true) {
        const save = evaluate<(node: typeof document.nodes[number], text: string) => Promise<void>>(
          declaration('saveGuestField').initializer!.getText(source), {
            Error, performance, engineSupported, engineDocument: document, sourceHash: document.source_sha256,
            sourceAtRenderRef: { current: content }, latexContent: content, previewRequestIdentityRef: identityRef,
            canRef: { current: (key: string) => features.has(key) },
            resolvedSession: owner === 'anonymous' ? null : { user: { id: owner } },
            apiClient: { patchGuestEngineDocument: patch }, setLatexContent, setEngineDocument, queuePreview,
          },
        )
        return save(document.nodes[0], text)
      },
      unmount() { mounted = false; hookState.slots.forEach(slot => slot.cleanup?.()) },
    }
    mount.renderIdentity()
    return mount
  }
  let current: ReturnType<typeof createMount> | undefined
  const render = (nextOwner = owner) => {
    owner = nextOwner
    boundaryIndex = 0
    const tree = boundaryRender({ children: null })
    const key = (tree.props as { children: React.ReactElement }).children.key
    if (!current || current.key !== key) { current?.unmount(); current = createMount(key) }
    return current
  }
  render()
  return { render, features, patch, requests, previews, dispose: () => current?.unmount() }
}

afterEach(() => { vi.useRealTimers(); vi.doUnmock('react'); vi.resetModules() })

describe('guest field saves stay with their account incarnation', () => {
  it.each([false, true])('does not apply or preview an unmounted guest response after %s round-trip, then saves only the current edit', async roundTrip => {
    const h = await harness()
    const old = h.render()
    const pending = old.save(edited(8))
    expect(h.patch).toHaveBeenCalledOnce()
    let current = h.render('changed-account')
    if (roundTrip) current = h.render('anonymous')
    expect(current.key).not.toBe(old.key)
    expect(current.document.nodes[0].text).toBe(GUEST_ORIGINAL_BULLET)

    h.requests[0].resolve(applyGuestBulletPatch(h.requests[0].body))
    await pending
    await vi.advanceTimersByTimeAsync(0)
    expect(current.content).toBe(FIRST_USE_ENGINE_RESUME_TEMPLATE)
    expect(current.document).toEqual(projectGuestBullet(FIRST_USE_ENGINE_RESUME_TEMPLATE))
    expect(current.setLatexContent).not.toHaveBeenCalled()
    expect(current.setEngineDocument).not.toHaveBeenCalled()
    expect(h.previews).not.toHaveBeenCalled()
    expect(h.requests).toHaveLength(1)

    const saved = current.save(edited(9))
    expect(h.requests).toHaveLength(2)
    expect(h.requests[1].body).toEqual({ ...h.requests[0].body,
      patches: [{ ...h.requests[0].body.patches[0], text: edited(9) }],
    })
    h.requests[1].resolve(applyGuestBulletPatch(h.requests[1].body))
    await saved
    await vi.advanceTimersByTimeAsync(0)
    const currentSource = FIRST_USE_ENGINE_RESUME_TEMPLATE.replace(GUEST_ORIGINAL_BULLET, edited(9))
    expect(current.content).toBe(currentSource)
    expect(current.document).toEqual(projectGuestBullet(currentSource))
    expect(current.setLatexContent).toHaveBeenCalledExactlyOnceWith(currentSource)
    expect(h.previews).toHaveBeenCalledExactlyOnceWith(currentSource)
    h.dispose()
  })

  it.each([false, true])('also rejects a still-mounted old identity after %s round-trip before any state write', async roundTrip => {
    const h = await harness()
    const current = h.render()
    const pending = current.save(edited(8))
    const rejected = expect(pending).rejects.toThrow('Your session changed. Reopen the field before saving.')
    current.renderIdentity('changed-account:device')
    if (roundTrip) current.renderIdentity('anonymous:device')
    h.requests[0].resolve(applyGuestBulletPatch(h.requests[0].body))
    await rejected
    await vi.advanceTimersByTimeAsync(0)
    expect(current.content).toBe(FIRST_USE_ENGINE_RESUME_TEMPLATE)
    expect(current.setLatexContent).not.toHaveBeenCalled()
    expect(current.setEngineDocument).not.toHaveBeenCalled()
    expect(h.previews).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['a09', 'b10', 'c01', 'engine'])('denies a new guest field save without %s before mutation or preview dispatch', async denied => {
    const h = await harness()
    const current = h.render()
    h.features.delete(denied)
    await expect(current.save(edited(8), denied !== 'engine')).rejects.toThrow('Stale field')
    await vi.advanceTimersByTimeAsync(0)
    expect(h.patch).not.toHaveBeenCalled()
    expect(current.content).toBe(FIRST_USE_ENGINE_RESUME_TEMPLATE)
    expect(current.setLatexContent).not.toHaveBeenCalled()
    expect(current.setEngineDocument).not.toHaveBeenCalled()
    expect(h.previews).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['b10', 'c01'])('recovers an already-admitted owned save after %s denial without dispatching a denied preview', async denied => {
    const h = await harness()
    const current = h.render()
    const admitted = current.save(edited(8))
    expect(h.patch).toHaveBeenCalledOnce()
    h.features.delete(denied)
    current.renderIdentity()
    h.requests[0].resolve(applyGuestBulletPatch(h.requests[0].body))
    await admitted
    await vi.advanceTimersByTimeAsync(0)
    const admittedSource = FIRST_USE_ENGINE_RESUME_TEMPLATE.replace(GUEST_ORIGINAL_BULLET, edited(8))
    expect(current.content).toBe(admittedSource)
    expect(current.document).toEqual(projectGuestBullet(admittedSource))
    expect(current.setLatexContent).toHaveBeenCalledExactlyOnceWith(admittedSource)
    expect(h.previews).not.toHaveBeenCalled()

    h.features.add(denied)
    current.renderIdentity()
    const recovered = current.save(edited(9))
    expect(h.requests[1].body.latex_content).toBe(admittedSource)
    expect(h.requests[1].body.expected_source_sha256).toBe(current.document.source_sha256)
    expect(h.requests[1].body.patches[0].expected_node_revision).toBe(current.document.nodes[0].node_revision)
    h.requests[1].resolve(applyGuestBulletPatch(h.requests[1].body))
    await recovered
    await vi.advanceTimersByTimeAsync(0)
    const recoveredSource = FIRST_USE_ENGINE_RESUME_TEMPLATE.replace(GUEST_ORIGINAL_BULLET, edited(9))
    expect(current.content).toBe(recoveredSource)
    expect(current.document).toEqual(projectGuestBullet(recoveredSource))
    expect(h.previews).toHaveBeenCalledExactlyOnceWith(recoveredSource)
    h.dispose()
  })
})
