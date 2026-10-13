import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import React, { act, createElement, startTransition, Suspense, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountContentScopeProvider, type AccountContentScope } from '@/contexts/AccountContentScope'
import { useEditorSourceLoadScope, useLatexGeneratorRecovery } from '@/hooks/useLatexGeneratorRecovery'

type Host = { type: string; props: Record<string, unknown>; children: Host[]; text?: string }
type Renderer = { createContainer: (...args: unknown[]) => unknown; updateContainer: (...args: unknown[]) => void; flushSync: (work: () => void) => void }
const require = createRequire(import.meta.url)
const fiberRequire = createRequire(require.resolve('@react-three/fiber'))
const reconcile = fiberRequire('react-reconciler') as (host: Record<string, unknown>) => Renderer
const { ConcurrentRoot, DefaultEventPriority } = fiberRequire('react-reconciler/constants') as { ConcurrentRoot: number; DefaultEventPriority: number }
function concurrentRoot() {
  const container: Host = { type: 'root', props: {}, children: [] }
  const append = (parent: Host, child: Host) => { parent.children = parent.children.filter(item => item !== child); parent.children.push(child) }
  const remove = (parent: Host, child: Host) => { parent.children = parent.children.filter(item => item !== child) }
  const renderer = reconcile({
    now: Date.now, supportsMutation: true, isPrimaryRenderer: true,
    getRootHostContext: () => ({}), getChildHostContext: () => ({}), getPublicInstance: (instance: Host) => instance,
    prepareForCommit: () => null, resetAfterCommit: () => {}, shouldSetTextContent: () => false,
    createInstance: (type: string, props: Record<string, unknown>) => ({ type, props, children: [] }),
    createTextInstance: (text: string) => ({ type: 'text', props: {}, children: [], text }),
    appendInitialChild: append, appendChild: append, appendChildToContainer: append,
    insertBefore: (parent: Host, child: Host, before: Host) => { remove(parent, child); parent.children.splice(parent.children.indexOf(before), 0, child) },
    insertInContainerBefore: (parent: Host, child: Host, before: Host) => { remove(parent, child); parent.children.splice(parent.children.indexOf(before), 0, child) },
    removeChild: remove, removeChildFromContainer: remove, clearContainer: (parent: Host) => { parent.children = [] },
    finalizeInitialChildren: () => false, prepareUpdate: () => true,
    commitUpdate: (instance: Host, _payload: unknown, _type: unknown, _previous: unknown, props: Record<string, unknown>) => { instance.props = props },
    commitTextUpdate: (instance: Host, _previous: unknown, next: string) => { instance.text = next },
    resetTextContent: () => {}, hideInstance: () => {}, unhideInstance: () => {}, hideTextInstance: () => {}, unhideTextInstance: () => {},
    scheduleTimeout: setTimeout, cancelTimeout: clearTimeout, noTimeout: -1,
    getCurrentEventPriority: () => DefaultEventPriority, detachDeletedInstance: () => {},
  })
  const root = renderer.createContainer(container, ConcurrentRoot, null, false, null, '', (error: unknown) => { throw error }, null)
  const render = (node: React.ReactNode) => renderer.updateContainer(node, root, null, null)
  return { container, renderer, render }
}

// Execute the installed Boundary body without visiting its child. This models a
// complete outer auth cycle before a queued consumer gets a chance to render;
// its resulting provider value then notifies a genuine concurrent React tree.
function boundaryLease(session: { user: { id: string }; session: { token: string } } | null) {
  const source = readFileSync(new URL('../components/AccountContentBoundary.tsx', import.meta.url), 'utf8')
  const ast = ts.createSourceFile('AccountContentBoundary.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const body = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'AccountContentBoundary') as ts.FunctionDeclaration
  const js = ts.transpileModule(`function Boundary(${body.parameters.map(node => node.getText(ast)).join(',')}) ${body.body!.getText(ast)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText
  const evaluate = new Function('context', `with(context) { ${js}; return Boundary({children:null}) }`) as
    (context: Record<string, unknown>) => React.ReactElement<{ value: AccountContentScope }>
  const refs: Array<{ current: unknown }> = []; let index = 0; let refetching = false; let error: unknown = null
  const render = () => { index = 0; return evaluate({ React, Fragment: React.Fragment, AccountContentScopeProvider,
    useRef: (value: unknown) => refs[index++] ??= { current: value }, useEffect: () => {},
    usePathname: () => '/workspace/document-A/edit', useSession: () => ({ data: session, isPending: false, isRefetching: refetching, error }),
    isConfirmedSessionUnauthorized }).props.value }
  return { render, refetching: (value: boolean) => { refetching = value }, error: (value: unknown) => { error = value } }
}

const text = (host: Host): string => host.text ?? host.children.map(text).join('')
afterEach(() => vi.unstubAllGlobals())

describe('source readiness requires a real concurrent React commit', () => {
  it('retires old admission permanently when actual Boundary refetch completes before the real provider consumer renders', async () => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    const root = concurrentRoot(); const session = { user: { id: 'owner-A' }, session: { token: 'stable-token' } }
    const boundary = boundaryLease(session); const oldLease = boundary.render()
    let source!: ReturnType<typeof useEditorSourceLoadScope>; let recovery!: ReturnType<typeof useLatexGeneratorRecovery>; let renders = 0
    const generated = vi.fn(); const inserted = vi.fn(); const copied = vi.fn()
    function Editor() {
      renders += 1
      source = useEditorSourceLoadScope('owner-A', 'document-A', session, true)
      recovery = useLatexGeneratorRecovery({ ownerId: 'owner-A', documentId: 'document-A', authReady: true,
        active: true, can: () => true, newWorkAllowed: source.isSourceReady(), sourceLoadReady: source.isSourceReady })
      return createElement('editor', null, `${recovery.canStart ? 'ready' : 'blocked'}:${recovery.available ? 'admitted fragment' : 'empty'}`)
    }
    const notify = (value: AccountContentScope) => root.render(createElement(AccountContentScopeProvider, { value }, createElement(Editor)))
    await act(async () => notify(oldLease))
    let oldTicket!: ReturnType<typeof source.beginLoad>
    await act(async () => { oldTicket = source.beginLoad(); source.finishLoad(oldTicket, 'ready', 'server') })
    await act(async () => recovery.onRecoveryChange(true))
    const oldSource = source; const oldRecovery = recovery; const key = recovery.key; const count = renders
    const generate = () => { if (oldRecovery.mayStart()) generated() }
    const insert = () => { if (oldRecovery.mayInsert()) inserted() }
    const copy = () => { if (oldLease.isCurrent() && recovery.available) copied('admitted fragment') }
    boundary.refetching(true); const refreshing = boundary.render()
    expect(refreshing.recoveryIdentity).toBe(oldLease.recoveryIdentity); expect(oldLease.canAdmit()).toBe(false)
    boundary.refetching(false); const settled = boundary.render()
    expect(renders).toBe(count); expect(settled.canAdmit()).toBe(true); expect(oldLease.canAdmit()).toBe(false)
    expect(oldLease.isCurrent()).toBe(true); expect(oldSource.isSourceReady()).toBe(false)
    expect(oldSource.ownsLoad(oldTicket)).toBe(false); expect(oldSource.finishLoad(oldTicket, 'ready', 'server')).toBe(false)
    generate(); insert(); copy(); expect(generated).not.toHaveBeenCalled(); expect(inserted).not.toHaveBeenCalled()
    expect(copied).toHaveBeenCalledExactlyOnceWith('admitted fragment')
    await act(async () => notify(settled))
    expect(renders).toBeGreaterThan(count); expect(recovery.key).toBe(key); expect(recovery.available).toBe(true)
    expect(text(root.container)).toBe('blocked:admitted fragment')
    let latest!: ReturnType<typeof source.beginLoad>
    await act(async () => { latest = source.beginLoad(); source.finishLoad(latest, 'ready', 'server') })
    expect(text(root.container)).toBe('ready:admitted fragment'); expect(recovery.mayStart()).toBe(true)
    generate(); insert(); expect(generated).not.toHaveBeenCalled(); expect(inserted).not.toHaveBeenCalled()
    expect(oldSource.isSourceReady()).toBe(false); expect(oldSource.finishLoad(oldTicket, 'ready', 'server')).toBe(false)
    if (recovery.mayStart()) generated(); if (recovery.mayInsert()) inserted()
    expect(generated).toHaveBeenCalledOnce(); expect(inserted).toHaveBeenCalledOnce()
    await act(async () => root.render(null))
  })

  it.each([false, true])('allows only the current uncertain offline ticket and retires it before the consumer observes outer lease changes, anonymous=%s', async anonymous => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    const root = concurrentRoot(); const session = anonymous ? null : { user: { id: 'owner-A' }, session: { token: 'stable-token' } }
    const boundary = boundaryLease(session); let authReady = false; let renders = 0
    boundary.error({ status: 503 }); const uncertain = boundary.render()
    let source!: ReturnType<typeof useEditorSourceLoadScope>
    function Editor() { renders += 1; source = useEditorSourceLoadScope(anonymous ? null : 'owner-A', 'document-A', session, authReady); return createElement('editor', null, source.status) }
    const notify = (value: AccountContentScope) => root.render(createElement(AccountContentScopeProvider, { value }, createElement(Editor)))
    await act(async () => notify(uncertain))
    let cold!: ReturnType<typeof source.beginLoad>
    await act(async () => { cold = source.beginLoad(); expect(source.ownsLoad(cold)).toBe(true); expect(source.finishLoad(cold, 'ready', 'offline')).toBe(true) })
    expect(source.kind).toBe('offline'); expect(source.isSourceReady()).toBe(false)
    const old = source; const version = cold.identity.version; const sequence = cold.identity.sequence; const count = renders
    boundary.error({ status: 503, message: 'Different uncertainty' }); const changed = boundary.render()
    expect(renders).toBe(count); expect(uncertain.isCurrent()).toBe(true); expect(uncertain.isAdmissionCurrent()).toBe(false)
    expect(changed.isAdmissionCurrent()).toBe(true); expect(changed.canAdmit()).toBe(false)
    expect(old.beginLoad().sequence).toBe(-1); expect(cold.identity.version).toBe(version); expect(cold.identity.sequence).toBe(sequence)
    expect(old.ownsLoad(cold)).toBe(false); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    boundary.error(anonymous ? { status: 503, message: 'Another cold offline uncertainty' } : null); const settled = boundary.render(); authReady = !anonymous
    expect(renders).toBe(count); expect(old.beginLoad().sequence).toBe(-1); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    await act(async () => notify(settled))
    let fresh!: ReturnType<typeof source.beginLoad>
    await act(async () => { fresh = source.beginLoad(); expect(source.finishLoad(fresh, 'ready', anonymous ? 'offline' : 'server')).toBe(true) })
    expect(source.isSourceReady()).toBe(!anonymous); expect(old.isSourceReady()).toBe(false); expect(old.ownsLoad(cold)).toBe(false)
    await act(async () => root.render(null))
  })

  it.each([{ supersede: false, strict: false }, { supersede: true, strict: true }])('denies queued ready before source commit, including superseded lanes=$supersede and StrictMode=$strict', async ({ supersede, strict }) => {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    const root = concurrentRoot(); const session = { user: { id: 'owner-A' } }
    const authority = { recoveryIdentity: {}, isCurrent: () => true, isAdmissionCurrent: () => true, canAdmit: () => true }
    let scope!: ReturnType<typeof useEditorSourceLoadScope>; let recovery!: ReturnType<typeof useLatexGeneratorRecovery>
    let setSource!: React.Dispatch<React.SetStateAction<string>>; let setPulse!: React.Dispatch<React.SetStateAction<number>>
    let held = false; let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    const generated = vi.fn(); const inserted = vi.fn(); const copied = vi.fn()
    function Editor() {
      const [source, updateSource] = useState('source-A'); const [pulse, updatePulse] = useState(0)
      setSource = updateSource; setPulse = updatePulse
      scope = useEditorSourceLoadScope('owner-A', 'document-A', session, true)
      recovery = useLatexGeneratorRecovery({ ownerId: 'owner-A', documentId: 'document-A', authReady: true,
        can: () => true, active: true, newWorkAllowed: scope.isSourceReady(), sourceLoadReady: scope.isSourceReady })
      if (held && source === 'source-B') throw gate
      return createElement('editor', null, `${source}:${pulse}:${recovery.canStart ? 'ready' : 'blocked'}`)
    }
    const editor = createElement(Suspense, { fallback: 'loading' }, createElement(Editor))
    const tree = createElement(AccountContentScopeProvider, { value: authority }, strict ? createElement(React.StrictMode, null, editor) : editor)
    await act(async () => root.render(tree))
    let initial!: ReturnType<typeof scope.beginLoad>
    await act(async () => { initial = scope.beginLoad(); scope.finishLoad(initial, 'ready', 'server') })
    expect(scope.isSourceReady()).toBe(true); expect(text(root.container)).toContain('source-A:0:ready')
    await act(async () => recovery.onRecoveryChange(true))
    const admitted = recovery; const readyGetter = scope.isSourceReady
    const generate = () => { if (admitted.mayStart()) generated() }
    const insert = () => { if (admitted.mayInsert()) inserted() }
    const copy = () => { if (authority.isCurrent() && recovery.available) copied('admitted fragment') }
    let reload!: ReturnType<typeof scope.beginLoad>
    await act(async () => { reload = scope.beginLoad() })
    expect(scope.isSourceReady()).toBe(false)
    held = true
    await act(async () => startTransition(() => {
      scope.finishLoad(reload, 'ready', 'server'); setSource('source-B')
      // The completion ref changes immediately, but no matching lane has committed.
      expect(scope.isSourceReady()).toBe(false); generate(); insert()
    }))
    expect(text(root.container)).toContain('source-A:0:blocked'); expect(scope.isSourceReady()).toBe(false)
    await act(async () => root.renderer.flushSync(() => setPulse(value => value + 1)))
    expect(text(root.container)).toContain('source-A:1:blocked'); expect(scope.isSourceReady()).toBe(false)
    generate(); insert(); expect(generated).not.toHaveBeenCalled(); expect(inserted).not.toHaveBeenCalled()
    expect(recovery.available).toBe(true); copy(); expect(copied).toHaveBeenCalledExactlyOnceWith('admitted fragment')
    if (supersede) {
      let latest!: ReturnType<typeof scope.beginLoad>
      await act(async () => root.renderer.flushSync(() => { latest = scope.beginLoad(); setSource('source-C') }))
      expect(scope.finishLoad(reload, 'ready', 'server')).toBe(false)
      held = false; await act(async () => release())
      expect(text(root.container)).toContain('source-C:1:blocked'); expect(readyGetter()).toBe(false)
      generate(); insert(); expect(generated).not.toHaveBeenCalled(); expect(inserted).not.toHaveBeenCalled()
      await act(async () => startTransition(() => { scope.finishLoad(latest, 'ready', 'server'); setSource('source-D') }))
      expect(text(root.container)).toContain('source-D:1:ready')
    } else {
      held = false; await act(async () => release())
      expect(text(root.container)).toContain('source-B:1:ready')
    }
    expect(readyGetter()).toBe(true); expect(scope.isSourceReady()).toBe(true); expect(recovery.available).toBe(true)
    generate(); insert(); expect(generated).toHaveBeenCalledOnce(); expect(inserted).toHaveBeenCalledOnce()
    await act(async () => root.render(null))
    expect(scope.isSourceReady()).toBe(false)
  })
})
