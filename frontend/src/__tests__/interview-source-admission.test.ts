import { createRequire } from 'node:module'
import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import React, { act, createElement, startTransition, Suspense, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AccountContentScopeProvider, type AccountContentScope } from '@/contexts/AccountContentScope'
import { useEditorSourceLoadScope, editorRecoveryLoadBoundary } from '@/hooks/useLatexGeneratorRecovery'
import { useInterviewPrepRecovery } from '@/hooks/useInterviewPrepRecovery'

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
  return { render, refetching: (value: boolean) => { refetching = value }, error: (value: unknown) => { error = value },
    session: (value: typeof session) => { session = value } }
}

const text = (host: Host): string => host.text ?? host.children.map(text).join('')
afterEach(() => vi.unstubAllGlobals())

async function harness(lazy = false) {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  const root = concurrentRoot()
  let session = { user: { id: 'owner-A' }, session: { token: 'token-A' } }
  const boundary = boundaryLease(session)
  let authority = boundary.render(); let authReady = true
  let owner = 'owner-A'; let document = 'document-A'; let grants = new Set(['e02', 'e03'])
  let source!: ReturnType<typeof useEditorSourceLoadScope>
  let interview!: ReturnType<typeof useInterviewPrepRecovery>
  let setSource!: React.Dispatch<React.SetStateAction<string>>
  let setPulse!: React.Dispatch<React.SetStateAction<number>>
  let held = false; let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let releasePanel!: () => void
  const panelGate = new Promise<void>(resolve => { releasePanel = resolve })
  const dynamic = require('next/dist/shared/lib/app-dynamic').default
  const InterviewPrepPanel = dynamic(async () => {
    await panelGate
    return { default: () => createElement('practice', null, 'Interview recovery loaded') }
  })
  const page = ts.createSourceFile('page.tsx', readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let shell!: ts.Expression
  const findShell = (node: ts.Node) => {
    if (ts.isJsxExpression(node) && node.expression?.getText(page).startsWith('interviewRecovery.mounted &&')) shell = node.expression
    ts.forEachChild(node, findShell)
  }
  findShell(page)
  const shellJs = ts.transpileModule(`const shell = ${shell.getText(page)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText
  const renderActualShell = new Function('context', 'React', `with(context) { ${shellJs}; return shell }`) as
    (context: Record<string, unknown>, react: typeof React) => React.ReactNode
  function Editor() {
    const [content, updateSource] = useState('source-A'); const [pulse, updatePulse] = useState(0)
    setSource = updateSource; setPulse = updatePulse
    source = useEditorSourceLoadScope(owner, document, session, authReady)
    interview = useInterviewPrepRecovery({ ownerId: owner, resumeId: document, authToken: session.session.token, authReady, sourceReady: source.isSourceReady, can: key => grants.has(key) })
    if (held && content === 'source-B') throw gate
    return createElement('editor', null, `${content}:${pulse}:${interview.scopeRef.current.ready ? 'ready' : 'blocked'}:${interview.mounted ? 'recovery' : 'empty'}`,
      lazy ? renderActualShell({ interviewRecovery: interview, visibleRightTab: 'interview', InterviewPrepPanel,
        Suspense, LoadingSpinner: () => createElement('spinner', null, 'Loading interview'), resumeId: document,
        jobDescription: '', isSourceReady: source.isSourceReady }, React) : null)
  }
  const render = () => root.render(createElement(AccountContentScopeProvider, { value: authority }, createElement(Suspense, { fallback: 'loading' }, createElement(Editor))))
  await act(async () => render())
  return {
    root, boundary, render, source: () => source, interview: () => interview,
    refresh: async () => { await act(async () => render()) },
    load: async () => { let ticket!: ReturnType<typeof source.beginLoad>; await act(async () => { ticket = source.beginLoad(); source.finishLoad(ticket, 'ready', 'server') }); return ticket },
    activate: async () => { expect(interview.activate()).toBe(true); await act(async () => setPulse(value => value + 1)) },
    allow: async (features: string[]) => { grants = new Set(features); await act(async () => render()) },
    notify: async () => { authority = boundary.render(); await act(async () => render()) },
    auth: (ready: boolean) => { authReady = ready },
    owner: (value: string, doc = document) => { owner = value; document = doc; session = { user: { id: owner }, session: { token: `token-${owner}` } }; boundary.session(session) },
    hold: () => { held = true },
    queueSource: () => setSource('source-B'),
    release: async () => { held = false; await act(async () => release()) },
    pulse: async () => { await act(async () => root.renderer.flushSync(() => setPulse(value => value + 1))) },
    loadPanel: async () => { await act(async () => releasePanel()) },
    close: async () => { held = false; release(); releasePanel(); await act(async () => root.render(null)) },
  }
}

describe('interview admission uses committed source and account authority', () => {
  it('keeps the real cold lazy interview shell inside the committed source editor', async () => {
    vi.stubGlobal('window', {})
    const h = await harness(true)
    try {
      await h.load(); await h.activate()
      expect(text(h.root.container)).toContain('Loading interview')
      expect(text(h.root.container)).toContain('source-A:1:ready:recovery')
      expect(h.source().isSourceReady()).toBe(true)
      await h.loadPanel()
      expect(text(h.root.container)).toContain('Interview recovery loaded')
      expect(h.source().isSourceReady()).toBe(true)
    } finally { await h.close() }
  })

  it('denies cold access, admits E03 without E02, and preserves visited recovery after both grants revoke', async () => {
    const h = await harness()
    try {
      expect(h.interview().canAccess).toBe(false); expect(h.interview().activate()).toBe(false)
      await h.load(); await h.allow(['e03'])
      expect(h.interview().canAccess).toBe(true)
      await h.activate(); const scope = h.interview().scopeRef.current
      await h.allow([])
      expect(h.interview().scopeRef.current).toBe(scope); expect(h.interview().mounted).toBe(true)
      expect(h.interview().canAccess).toBe(true)
      expect(editorRecoveryLoadBoundary({ preserveRecovery: h.interview().mounted, sourceStatus: 'error', isLoading: false,
        resumeLoadError: 'Reload failed', hasSession: true, sessionError: null, offlineDraftLoaded: false, offlinePdfLoaded: false })).toBe('editor')
    } finally { await h.close() }
  })

  it('retires admission during an outer refetch skipped by the child and keeps only same-owner recovery', async () => {
    const h = await harness()
    try {
      const ticket = await h.load(); await h.activate()
      const oldSource = h.source(); const scope = h.interview().scopeRef.current
      h.boundary.refetching(true); h.boundary.render()
      expect(oldSource.isSourceReady()).toBe(false); expect(oldSource.finishLoad(ticket, 'ready', 'server')).toBe(false)
      h.boundary.refetching(false); h.boundary.render()
      expect(oldSource.isSourceReady()).toBe(false)
      await h.notify()
      expect(h.interview().scopeRef.current).toBe(scope); expect(h.interview().mounted).toBe(true)
      expect(scope.ready).toBe(false)
      await h.load(); expect(scope.ready).toBe(true); expect(oldSource.isSourceReady()).toBe(false)
      h.boundary.error({ status: 401 }); h.boundary.render()
      expect(h.interview().activate()).toBe(false)
      await h.notify(); expect(h.interview().mounted).toBe(false)
    } finally { await h.close() }
  })

  it.each(['owner', 'document'])('does not revive a retired %s incarnation on A to B to A', async kind => {
    const h = await harness()
    try {
      await h.load(); await h.activate(); const old = h.interview(); const oldScope = old.scopeRef.current
      if (kind === 'owner') {
        h.owner('owner-B'); h.boundary.render(); h.owner('owner-A'); h.boundary.render()
        expect(old.activate()).toBe(false)
        await h.notify()
      } else {
        h.owner('owner-A', 'document-B'); await h.notify()
        h.owner('owner-A', 'document-A'); await h.notify()
      }
      expect(h.interview().scopeRef.current).not.toBe(oldScope)
      expect(h.interview().mounted).toBe(false); expect(old.activate()).toBe(false)
    } finally { await h.close() }
  })

  it('cannot admit queued source readiness before its actual React commit', async () => {
    const h = await harness()
    try {
      await h.load(); await h.activate()
      const scope = h.interview().scopeRef.current
      let reload!: ReturnType<ReturnType<typeof h.source>['beginLoad']>
      await act(async () => { reload = h.source().beginLoad() })
      h.hold()
      await act(async () => startTransition(() => { h.source().finishLoad(reload, 'ready', 'server'); h.queueSource() }))
      expect(h.source().isSourceReady()).toBe(false); expect(scope.ready).toBe(false)
      expect(h.interview().mounted).toBe(true)
      await h.pulse()
      expect(text(h.root.container)).toContain('source-A:2:blocked:recovery')
      expect(h.source().isSourceReady()).toBe(false)
      await h.release()
      expect(h.source().isSourceReady()).toBe(true); expect(scope.ready).toBe(true)
    } finally { await h.close() }
  })

  it('wires the shared readiness and local lazy boundary into the actual editor', () => {
    const page = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')
    expect(page).toContain('preserveRecovery: latexGeneratorRecovery.mounted || interviewRecovery.mounted')
    expect(page).toContain('sourceReady={isSourceReady}')
    expect(page).toContain('<Suspense fallback={<LoadingSpinner />}>' )
    expect(page).not.toContain('<CapabilityGate feature="e02"><InterviewPrepPanel')
  })
})
