import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

type SessionData = { user: { id: string }; session: { token: string } }
type SessionAtom = { value: { data: SessionData | null; isPending: boolean; isRefetching: boolean; error: unknown; refetch: () => Promise<void> };
  set: (state: SessionAtom['value']) => void }

const pageSource = readFileSync(resolve(process.cwd(), 'src/app/workspace/[resumeId]/edit/page.tsx'), 'utf8')
const pageAst = ts.createSourceFile('page.tsx', pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const pageFunction = pageAst.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ResumeEditPage') as ts.FunctionDeclaration
const pageStatements = pageFunction.body!.statements
const confirmedEndedDeclaration = pageStatements.find(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(declaration => declaration.name.getText(pageAst) === 'confirmedSessionEnded'))!
const offlineOwnerDeclaration = pageStatements.find(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(declaration => declaration.name.getText(pageAst) === 'offlinePdfOwnerId'))!
const authorityStart = pageStatements.findIndex(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(declaration => declaration.name.getText(pageAst) === 'sessionUnauthorized'))
const authorityEnd = pageStatements.indexOf(confirmedEndedDeclaration)
const authorityJs = ts.transpileModule(`${pageStatements.slice(authorityStart, authorityEnd + 1).map(node => node.getText(pageAst)).join('\n')}
${offlineOwnerDeclaration.getText(pageAst)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const actualSessionAuthority = new Function('context', `with (context) { ${authorityJs}; return { confirmedSessionEnded, offlinePdfOwnerId } }`) as
  (context: Record<string, unknown>) => { confirmedSessionEnded: boolean; offlinePdfOwnerId: string | null }
const pageBoundaryDeclaration = pageStatements.find(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(declaration => declaration.name.getText(pageAst) === 'editorLoadBoundary'))!
function containsPageReturn(node: ts.Node): boolean {
  if (ts.isReturnStatement(node)) return true
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return false
  return node.getChildren(pageAst).some(containsPageReturn)
}
const pageGuardStatements = pageStatements.filter(node => ts.isIfStatement(node) && containsPageReturn(node))
const boundaryJs = ts.transpileModule(`function actualPageLoadGuards() {
  ${pageBoundaryDeclaration.getText(pageAst)}
  ${pageGuardStatements.map(node => node.getText(pageAst)).join('\n')}
  return undefined
}`, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText
// Execute the actual page's top-level JSX return branches. If none returns, the
// exact same keyed editor subtree remains in place in the lifecycle runner.
const actualPageLoadGuards = new Function('context', 'React', `with (context) { ${boundaryJs}; return actualPageLoadGuards() }`) as
  (context: Record<string, unknown>, react: unknown) => import('react').ReactElement | null | undefined
let sourceLoadActiveExpression = ''
let sourceLoadWaitStatement = ''
let sourceAuthReadyExpression = ''
let generatorAuthReadyExpression = ''
function findLoadEffect(node: ts.Node) {
  if (ts.isCallExpression(node) && node.expression.getText(pageAst) === 'useEditorSourceLoadScope') {
    sourceAuthReadyExpression = node.arguments[3].getText(pageAst)
  }
  if (ts.isCallExpression(node) && node.expression.getText(pageAst) === 'useLatexGeneratorRecovery') {
    const options = node.arguments[0] as ts.ObjectLiteralExpression
    const ready = options.properties.find(property => ts.isPropertyAssignment(property) && property.name.getText(pageAst) === 'authReady') as ts.PropertyAssignment
    generatorAuthReadyExpression = ready.initializer.getText(pageAst)
  }
  if (ts.isCallExpression(node) && node.expression.getText(pageAst) === 'useEffect'
    && node.arguments[0]?.getText(pageAst).includes('const fetchResume =')) {
    const body = (node.arguments[0] as ts.ArrowFunction).body as ts.Block
    const declaration = body.statements.filter(ts.isVariableStatement).flatMap(statement => [...statement.declarationList.declarations])
      .find(item => item.name.getText(pageAst) === 'isActive')
    sourceLoadActiveExpression = declaration!.initializer!.getText(pageAst)
    sourceLoadWaitStatement = body.statements[0].getText(pageAst)
  }
  ts.forEachChild(node, findLoadEffect)
}
findLoadEffect(pageFunction)
const activeLoadJs = ts.transpileModule(`const isActive = ${sourceLoadActiveExpression}`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const actualSourceLoadIsActive = new Function('context', `with (context) { ${activeLoadJs}; return isActive() }`) as
  (context: Record<string, unknown>) => boolean
const actualSourceAuthReady = new Function('context', `with (context) { return ${sourceAuthReadyExpression} }`) as
  (context: Record<string, unknown>) => boolean
const actualGeneratorAuthReady = new Function('context', `with (context) { return ${generatorAuthReadyExpression} }`) as
  (context: Record<string, unknown>) => boolean
const actualSourceLoadCanBegin = new Function('context', `with (context) {
  function beginAllowed() { ${sourceLoadWaitStatement}; return true }; return Boolean(beginAllowed())
}`) as (context: Record<string, unknown>) => boolean

type Element = { type: unknown; key?: string | null; props: Record<string, unknown> }
type Slot = { value?: unknown; deps?: unknown[]; cleanup?: () => void }
type Instance = { slots: Slot[]; index: number; alive: boolean }
const leaves = ['d14_latex', 'd14_table_text', 'd14_table_image', 'd14_math_text', 'd14_math_image']
const all = ['d14', 'ai_writing', 'c01', ...leaves]
const label = (node: unknown): string => typeof node === 'string' ? node : Array.isArray(node)
  ? node.map(label).join('') : node && typeof node === 'object' && 'props' in node ? label((node as Element).props.children) : ''
const elements = (node: unknown): Element[] => Array.isArray(node) ? node.flatMap(elements)
  : node && typeof node === 'object' && 'props' in node ? [node as Element, ...elements((node as Element).props.children)] : []
const button = (tree: unknown, name: string) => {
  const node = elements(tree).find(item => item.type === 'button' && label(item).trim() === name)
  expect(node, name).toBeDefined()
  return node!
}
const click = (node: Element) => (node.props.onClick as () => unknown)()
const textarea = (tree: unknown) => elements(tree).find(node => node.type === 'textarea')!
const change = (node: Element, value: string) => (node.props.onChange as (event: unknown) => void)({ target: { value } })
const settle = async () => { for (let i = 0; i < 6; i++) await Promise.resolve() }
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes })
  return { promise, resolve }
}

/** A keyed component/hook lifecycle runner that executes the real shell mount
 * conditional, retains hidden children and cleans up replaced child keys. */
async function harness(autoLoad = true) {
  vi.resetModules()
  let rawOwner: string | null = 'owner-A'; let documentId = 'document-A'; let token = 'token-A'
  let rawSession: SessionData | null = { user: { id: rawOwner }, session: { token } }
  let actualAtom: SessionAtom | null = null
  let pending = false; let refetching = false; let authError: Error | null = null; let grants = new Set(all); let sourceWritable = true
  let isLoading = !autoLoad; let resumeLoadError: string | null = null
  let offlineDraftLoaded = false; let offlinePdfLoaded = false
  const offlineIdentityDeniedRef = { current: false }
  let dirty = false; let instance: Instance
  let accountAuthority: import('@/contexts/AccountContentScope').AccountContentScope | null = null
  let accountKey = ''; let skipEditor = false; let editorTree: unknown
  let lastAuthority: import('@/contexts/AccountContentScope').AccountContentScope | null = null
  const pendingUnmount: Instance[] = []
  const instances = new Map<string, Instance>()
  const effects = new Map<Instance, Map<number, () => void>>()
  const layouts = new Map<Instance, Map<number, () => void>>()
  let seen = new Set<string>()
  const same = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index])))
  vi.doMock('react', async original => ({
    ...await original<typeof import('react')>(),
    useContext: () => accountAuthority,
    useRef: (value: unknown) => { const slot = instance.index++; instance.slots[slot] ??= { value: { current: value } }; return instance.slots[slot].value },
    useState: (value: unknown) => {
      const target = instance; const slot = target.index++
      target.slots[slot] ??= { value: typeof value === 'function' ? (value as () => unknown)() : value }
      return [target.slots[slot].value, (next: unknown) => {
        if (!target.alive) return
        const previous = target.slots[slot].value
        const value = typeof next === 'function' ? (next as (old: unknown) => unknown)(previous) : next
        if (!Object.is(previous, value)) { target.slots[slot].value = value; dirty = true }
      }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => {
      const slot = instance.index++
      if (!same(instance.slots[slot]?.deps, deps)) instance.slots[slot] = { value: callback, deps }
      return instance.slots[slot].value
    },
    useLayoutEffect: (effect: () => void | (() => void), deps: unknown[]) => {
      const target = instance; const slot = target.index++; const previous = target.slots[slot]
      if (!same(previous?.deps, deps)) {
        target.slots[slot] = { deps, cleanup: previous?.cleanup }
        const queue = layouts.get(target) ?? new Map<number, () => void>()
        layouts.set(target, queue)
        queue.set(slot, () => { target.slots[slot].cleanup?.(); target.slots[slot].cleanup = effect() || undefined })
      }
    },
    useEffect: (effect: () => void | (() => void), deps: unknown[]) => {
      const target = instance; const slot = target.index++; const previous = target.slots[slot]
      if (!same(previous?.deps, deps)) {
        target.slots[slot] = { deps, cleanup: previous?.cleanup }
        const queue = effects.get(target) ?? new Map<number, () => void>()
        effects.set(target, queue)
        queue.set(slot, () => { target.slots[slot].cleanup?.(); target.slots[slot].cleanup = effect() || undefined })
      }
    },
  }))
  let panel: typeof import('@/components/LatexGeneratorPanel').default
  vi.doMock('next/dynamic', () => ({ default: () => (props: Parameters<typeof panel>[0]) => panel(props) }))
  const router = { push: vi.fn() }
  vi.doMock('next/navigation', () => ({ useRouter: () => router, usePathname: () => `/workspace/${documentId}/edit` }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => actualAtom?.value ?? ({
    data: rawSession, isPending: pending, isRefetching: refetching, error: authError,
  }) }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants
    return { can: (feature: string) => snapshot.has(feature) }
  } }))
  const result = { latex: '\\section{Retained fragment}', cached: false, rows: 2, columns: 2 }
  const api = { getAuthToken: () => token, generateLatex: vi.fn().mockResolvedValue(result),
    generateLatexTable: vi.fn().mockResolvedValue(result), generateLatexTableFromImage: vi.fn().mockResolvedValue(result),
    generateLatexMath: vi.fn().mockResolvedValue(result), generateLatexMathFromImage: vi.fn().mockResolvedValue(result) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator', { onLine: true, clipboard: { writeText } })
  vi.stubGlobal('window', { location: { pathname: '/workspace/document-A/edit' } })
  panel = (await import('@/components/LatexGeneratorPanel')).default
  const Shell = (await import('@/components/LatexGeneratorRecoveryShell')).default
  const { useLatexGeneratorRecovery, useEditorSourceLoadScope, editorRecoveryLoadBoundary } = await import('@/hooks/useLatexGeneratorRecovery')
  const { useRequireAuth } = await import('@/hooks/useRequireAuth')
  const Boundary = (await import('@/components/AccountContentBoundary')).default
  const { AccountContentScopeProvider } = await import('@/contexts/AccountContentScope')
  const React = await import('react')
  const { useState, useRef, useEffect } = React
  const { jsx, jsxs } = await import('react/jsx-runtime')
  const onInsert = vi.fn()
  let recovery!: ReturnType<typeof useLatexGeneratorRecovery>
  let source!: ReturnType<typeof useEditorSourceLoadScope>
  function Editor() {
    const auth = useRequireAuth()
    const [tab, setTab] = useState('preview')
    const current = useRef<ReturnType<typeof useLatexGeneratorRecovery> | null>(null)
    const authContext = { sessionUserId: auth.session?.user?.id ?? null, sessionLoading: auth.isPending,
      sessionRefetching: auth.isRefetching, sessionError: auth.error }
    const authority = actualSessionAuthority({ ...authContext, sessionData: auth.session, rememberedOfflineOwner: 'owner-A', isConfirmedSessionUnauthorized, useRef: () => offlineIdentityDeniedRef })
    const sourceScope = useEditorSourceLoadScope(auth.session?.user?.id ?? null, documentId, auth.session,
      actualSourceAuthReady(authContext))
    source = sourceScope
    const { beginLoad, finishLoad, ownsLoad } = sourceScope
    useEffect(() => {
      if (!autoLoad || !actualSourceLoadCanBegin({ sessionLoading: auth.isPending, sessionRefetching: auth.isRefetching })) return
      const ticket = beginLoad()
      if (!ownsLoad(ticket)) return
      finishLoad(ticket, 'ready', 'server')
    }, [beginLoad, finishLoad, ownsLoad, auth.isPending, auth.isRefetching])
    const sourceLoadReady = source.isSourceReady() && !isLoading && !resumeLoadError
    recovery = useLatexGeneratorRecovery({ ownerId: auth.session?.user?.id ?? null, documentId,
      authReady: actualGeneratorAuthReady(authContext),
      can: feature => grants.has(feature), newWorkAllowed: sourceLoadReady && sourceWritable,
      sourceLoadReady: source.isSourceReady, active: tab === 'generate' })
    current.current = recovery
    // This hook/shell fixture already owns its synthetic source. Actual queued
    // page content/scope publication is covered by editor-content-scope.test.ts.
    const ownedDocument = { ownerId: authority.offlinePdfOwnerId, resumeId: documentId }
    const pageReturn = actualPageLoadGuards({ editorRecoveryLoadBoundary, latexGeneratorRecovery: recovery, interviewRecovery: { mounted: false },
      sourceLoadStatus: source.status, isLoading, resumeLoadError, sessionData: auth.session, sessionError: auth.error,
      offlineDraftLoaded, offlinePdfLoaded, confirmedSessionEnded: authority.confirmedSessionEnded, LoadingSpinner: 'LoadingSpinner', Link: 'a', AlertCircle: 'AlertCircle',
      SessionLoadError: 'SessionLoadError', loadedDocumentScopeRef: { current: ownedDocument },
      committedDocumentContent: { scope: ownedDocument, sourceLoaded: true } }, React)
    if (pageReturn !== undefined) return pageReturn
    return jsxs('div', { children: [
      jsx('button', { children: 'Preview', onClick: () => setTab('preview') }),
      recovery.canAccess && jsx('button', { children: recovery.canStart ? 'Generate LaTeX' : 'Recover LaTeX',
        onClick: () => { if (current.current?.canAccess) setTab('generate') } }),
      jsx(Shell, { recovery, active: tab === 'generate' && recovery.canAccess, documentId, documentContext: 'Current source', onInsert }),
    ] })
  }
  function walk(value: unknown, path: string): unknown {
    if (Array.isArray(value)) return value.map((child, index) => walk(child, `${path}/${index}`))
    if (!value || typeof value !== 'object' || !('props' in value)) return value
    const node = value as Element
    const nextPath = `${path}:${node.key ?? ''}`
    if (node.type === AccountContentScopeProvider) {
      const previous = accountAuthority
      accountAuthority = node.props.value as import('@/contexts/AccountContentScope').AccountContentScope
      lastAuthority = accountAuthority
      accountKey = String((node.props.children as Element).key)
      const child = walk(node.props.children, `${nextPath}/provider`)
      accountAuthority = previous
      return child
    }
    if (node.type === Editor && skipEditor) {
      for (const key of instances.keys()) if (key.startsWith(nextPath)) seen.add(key)
      return editorTree
    }
    if (typeof node.type === 'function') {
      const target = instances.get(nextPath) ?? { slots: [], index: 0, alive: true }
      instances.set(nextPath, target); seen.add(nextPath); target.index = 0
      const previous = instance; instance = target
      const result = (node.type as (props: Record<string, unknown>) => unknown)(node.props)
      instance = previous
      const rendered = walk(result, `${nextPath}/component`)
      if (node.type === Editor) editorTree = rendered
      return rendered
    }
    return { ...node, props: { ...node.props, children: walk(node.props.children, `${nextPath}/children`) } }
  }
  const unmount = () => {
    for (const target of instances.values()) { target.alive = false; target.slots.forEach(slot => slot.cleanup?.()) }
    pendingUnmount.forEach(target => target.slots.forEach(slot => slot.cleanup?.())); pendingUnmount.length = 0
    instances.clear(); effects.clear(); layouts.clear()
  }
  function render(flushEffects = true, boundaryOnly = false) {
    skipEditor = boundaryOnly
    let tree: unknown
    for (let pass = 0; pass < 25; pass++) {
      dirty = false; seen = new Set()
      tree = walk(jsx(Boundary, { children: jsx(Editor, {}) }), 'root')
      for (const [key, target] of instances) if (!seen.has(key)) {
        target.alive = false; pendingUnmount.push(target); instances.delete(key); effects.delete(target); layouts.delete(target)
      }
      const committedLayouts = [...layouts.entries()]; layouts.clear()
      committedLayouts.forEach(([target, callbacks]) => { if (target.alive) callbacks.forEach(effect => effect()) })
      if (!flushEffects) { if (dirty) continue; return tree }
      pendingUnmount.forEach(target => target.slots.forEach(slot => slot.cleanup?.())); pendingUnmount.length = 0
      const queued = [...effects.entries()]; effects.clear()
      queued.forEach(([target, callbacks]) => { if (target.alive) callbacks.forEach(effect => effect()) })
      if (!dirty) return tree
    }
    throw new Error('Component lifecycle failed to settle')
  }
  return { render, renderBoundaryOnly: () => render(false, true), authority: () => lastAuthority!, api, result, onInsert, writeText, unmount, // The effective mounted key includes the real outer Fragment incarnation.
    recovery: () => ({ ...recovery, key: `${accountKey}/${recovery.key}` }),
    useActualSessionAtom: async () => {
      // This is the exact installed implementation, not a re-created refresh
      // fixture. Equal success data deliberately retains its original reference.
      const sessionModule = path.join(path.dirname(createRequire(import.meta.url).resolve('better-auth/client')), 'session-atom.mjs')
      const { getSessionAtom } = await import(pathToFileURL(sessionModule).href)
      const response = deferred<{ data: SessionData | null; error: { status: number; message: string } | null }>()
      const fetch = vi.fn(() => response.promise)
      const { session: atom } = getSessionAtom(fetch, {}) as { session: SessionAtom }
      const session = rawSession!
      atom.set({ ...atom.value, data: session, isPending: false, isRefetching: false, error: null })
      actualAtom = atom
      return { atom, response, fetch, session, start: async () => {
        const completion = atom.value.refetch(); await Promise.resolve()
        expect(atom.value.isPending).toBe(false); expect(atom.value.isRefetching).toBe(true)
        expect(atom.value.data).toBe(session)
        return { completion }
      } }
    },
    sessionReference: () => rawSession,
    authReady: () => Boolean(rawSession && !pending && !refetching && !authError),
    isPending: () => pending,
    source: () => source,
    offlineLoaded: () => { offlineDraftLoaded = true; offlinePdfLoaded = true },
    beginLoad: () => { isLoading = true; resumeLoadError = null; return source.beginLoad() },
    finishLoad: (ticket: Parameters<typeof source.finishLoad>[0], status: 'ready' | 'error' | 'pdf-only', kind: 'server' | 'offline' = 'server') => {
      if (!source.finishLoad(ticket, status, status === 'ready' ? kind : null)) return false
      isLoading = false; resumeLoadError = status === 'error' ? 'Source reload failed' : null
      offlineDraftLoaded = status === 'ready' && kind === 'offline'; offlinePdfLoaded = status === 'pdf-only'
      return true
    },
    allow: (next: string[]) => { grants = new Set(next) },
    auth: (owner: string | null, isPending = false, error: Error | null = null) => {
      rawOwner = owner; pending = isPending; authError = error
      rawSession = owner ? { user: { id: owner }, session: { token } } : null
    },
    readiness: (isPending: boolean, error: Error | null = null) => { pending = isPending; authError = error },
    refetching: (active: boolean) => { refetching = active },
    document: (next: string) => { documentId = next }, token: (next: string) => {
      token = next; rawSession = rawOwner ? { user: { id: rawOwner }, session: { token } } : null
    },
    writable: (next: boolean) => { sourceWritable = next } }
}
type Harness = Awaited<ReturnType<typeof harness>>
function enter(h: Harness) { click(button(h.render(), 'Generate LaTeX')); return h.render() }
function draft(h: Harness) { change(textarea(enter(h)), 'Create a saved fragment'); return h.render() }
function recoveryContainer(tree: unknown) { return elements(tree).find(node => 'data-latex-generator-recovery' in node.props) }

afterEach(() => {
  for (const name of ['react', 'next/dynamic', 'next/navigation', '@/lib/auth-client', '@/contexts/EntitlementsContext', '@/lib/api-client']) vi.doUnmock(name)
  vi.unstubAllGlobals(); vi.resetModules()
})

describe('D14 editor recovery shell and keyed component lifecycle', () => {
  it.each(['d14', 'ai_writing', 'all leaves'])('hides new entry when %s is OFF without mounting the panel', async denied => {
    const h = await harness(); h.allow(all.filter(feature => denied === 'all leaves' ? !leaves.includes(feature) : feature !== denied))
    const tree = h.render()
    expect(label(tree)).not.toContain('Generate LaTeX'); expect(recoveryContainer(tree)).toBeUndefined()
    expect(h.api.generateLatex).not.toHaveBeenCalled(); h.unmount()
  })

  it.each(['d14', 'ai_writing', 'd14_latex', 'all leaves'])('retains draft, in-flight result and recovery tab through %s revocation and tab navigation', async denied => {
    const h = await harness(); const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const oldGenerate = button(draft(h), 'Generate fragment'); click(oldGenerate); h.render()
    h.allow(all.filter(feature => denied === 'all leaves' ? !leaves.includes(feature) : feature !== denied))
    let tree = h.render(); expect(h.recovery().available).toBe(true)
    click(button(tree, 'Preview')); tree = h.render(); expect(recoveryContainer(tree)?.props.hidden).toBe(true)
    pending.resolve(h.result); await settle(); tree = h.render()
    expect(label(tree)).toContain(h.result.latex)
    click(button(tree, denied === 'd14_latex' ? 'Generate LaTeX' : 'Recover LaTeX')); tree = h.render()
    expect(recoveryContainer(tree)?.props.hidden).toBe(false); expect(label(tree)).toContain('Create a saved fragment')
    click(oldGenerate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.unmount()
  })

  it('preserves draft and completion through missing-session refresh/error and token rotation while admission/insertion wait', async () => {
    const h = await harness(); const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const oldGenerate = button(draft(h), 'Generate fragment'); const key = h.recovery().key; click(oldGenerate); h.render()
    h.auth(null, true); let tree = h.render(); expect(h.recovery().key).toBe(key)
    expect(label(tree)).toContain('Recover LaTeX'); expect(label(tree)).toContain('Create a saved fragment')
    click(button(tree, 'Preview')); h.auth(null, false, new Error('temporary')); tree = h.render()
    expect(h.recovery().key).toBe(key); expect(recoveryContainer(tree)?.props.hidden).toBe(true)
    pending.resolve(h.result); await settle(); click(button(h.render(), 'Recover LaTeX')); tree = h.render()
    expect(label(tree)).toContain(h.result.latex); const retainedShellInsert = h.recovery().mayInsert
    expect(retainedShellInsert()).toBe(false)
    click(oldGenerate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.auth('owner-A'); h.token('rotated-token'); tree = h.render()
    expect(h.recovery().key).toBe(key); expect(label(tree)).toContain(h.result.latex)
    expect(retainedShellInsert()).toBe(false); expect(h.recovery().mayInsert()).toBe(true); click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledWith(h.result.latex)
    h.unmount()
  })

  it('admits generation with C01 OFF but fences retained source insertion', async () => {
    const h = await harness(); click(button(draft(h), 'Generate fragment')); await settle()
    let tree = h.render(); const retainedInsert = button(tree, 'Insert at cursor')
    h.allow(all.filter(feature => feature !== 'c01')); tree = h.render()
    expect(label(tree)).toContain('Generate LaTeX'); expect(label(tree)).toContain(h.result.latex)
    expect(h.recovery().canStart).toBe(true)
    click(retainedInsert); expect(h.onInsert).not.toHaveBeenCalled()
    h.writable(false); tree = h.render(); expect(label(tree)).toContain('Recover LaTeX')
    click(button(tree, 'Preview')); click(button(h.render(), 'Recover LaTeX')); tree = h.render()
    expect(recoveryContainer(tree)?.props.hidden).toBe(false)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.unmount()
  })

  it('shows new generation entry with C01 OFF even before a draft or result exists', async () => {
    const h = await harness(); h.allow(all.filter(feature => feature !== 'c01'))
    expect(button(h.render(), 'Generate LaTeX')).toBeDefined(); expect(h.recovery().available).toBe(false)
    click(button(draft(h), 'Generate fragment')); await settle()
    const tree = h.render(); expect(label(tree)).toContain(h.result.latex)
    expect(h.api.generateLatex).toHaveBeenCalledOnce()
    expect(elements(tree).some(node => node.type === 'button' && label(node) === 'Insert at cursor')).toBe(false)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.unmount()
  })

  it('blocks retained generation/insertion on a hidden tab and during source eligibility loss, while retaining recovery', async () => {
    const h = await harness(); const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    let tree = h.render(); const insert = button(tree, 'Insert at cursor')
    click(button(tree, 'Preview')); tree = h.render()
    expect(recoveryContainer(tree)?.props.hidden).toBe(true)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(h.render(), 'Generate LaTeX')); h.render(); h.writable(false); tree = h.render()
    expect(label(tree)).toContain('Recover LaTeX'); expect(label(tree)).toContain(h.result.latex)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    h.writable(true); tree = h.render(); click(insert)
    expect(h.onInsert).toHaveBeenCalledOnce(); h.unmount()
  })

  it('denies retained Generate, Insert, Copy and source finish through actual outer route ABA before passive cleanup', async () => {
    const h = await harness(false); h.render(); const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const tree = h.render(); const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment'); const old = h.recovery()
    h.document('document-B'); h.render(false); expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await click(copy); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    h.document('document-A'); h.render(false); expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await click(copy); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled()
    expect(old.mayStart()).toBe(false); expect(old.mayInsert()).toBe(false)
    const fresh = h.beginLoad(); h.finishLoad(fresh, 'ready'); h.render(); expect(textarea(enter(h)).props.value).toBe('')
    h.unmount()
  })

  it.each(['document', 'owner', 'logout'])('fences pending results and retained callbacks after confirmed %s changes and ABA', async kind => {
    const h = await harness(); const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const tree = draft(h); const retainedGenerate = button(tree, 'Generate fragment'); const oldScope = h.recovery()
    click(retainedGenerate); h.render()
    if (kind === 'document') h.document('document-B')
    else h.auth(kind === 'logout' ? null : 'owner-B')
    h.render()
    if (kind === 'document') h.document('document-A')
    else h.auth('owner-A')
    let current = h.render(); expect(h.recovery().key).not.toBe(oldScope.key)
    oldScope.onRecoveryChange(true); expect(oldScope.mayInsert()).toBe(false)
    pending.resolve(h.result); await settle(); current = h.render()
    expect(label(current)).not.toContain(h.result.latex); expect(label(current)).not.toContain('Create a saved fragment')
    expect(h.recovery().available).toBe(false)
    click(retainedGenerate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    h.unmount()
  })

  it('invalidates recovery and insertion callbacks on actual editor unmount', async () => {
    const h = await harness(); draft(h); const recovery = h.recovery(); h.unmount()
    recovery.onRecoveryChange(true); expect(recovery.mayInsert()).toBe(false)
  })

  it('executes the actual page load/error returns before first source success, with no premature generator entry', async () => {
    const h = await harness(false); let tree = h.render()
    expect(elements(tree).some(node => node.type === 'LoadingSpinner')).toBe(true)
    expect(recoveryContainer(tree)).toBeUndefined(); expect(label(tree)).not.toContain('Generate LaTeX')
    const failed = h.beginLoad(); tree = h.render(); h.finishLoad(failed, 'error'); tree = h.render()
    expect(label(tree)).toContain('Resume could not be loaded'); expect(label(tree)).toContain('Source reload failed')
    expect(recoveryContainer(tree)).toBeUndefined(); expect(h.recovery().canStart).toBe(false)
    const ready = h.beginLoad(); h.render(); h.finishLoad(ready, 'ready'); tree = h.render()
    expect(h.source().kind).toBe('server'); expect(button(tree, 'Generate LaTeX')).toBeDefined()
    expect(h.source().isSourceReady()).toBe(true); h.unmount()
  })

  it('preserves the actual page subtree through same-scope loading/error while admitted completion/copy continues and mutations wait', async () => {
    const h = await harness(); const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const generate = button(draft(h), 'Generate fragment'); click(generate); h.render(); const key = h.recovery().key
    const load = h.beginLoad(); let tree = h.render()
    expect(h.recovery().key).toBe(key); expect(recoveryContainer(tree)).toBeDefined()
    expect(elements(tree).some(node => node.type === 'LoadingSpinner')).toBe(false)
    expect(h.recovery().canStart).toBe(false); expect(label(tree)).toContain('Create a saved fragment')
    pending.resolve(h.result); await settle(); tree = h.render()
    expect(label(tree)).toContain(h.result.latex)
    h.finishLoad(load, 'error'); tree = h.render()
    expect(recoveryContainer(tree)).toBeDefined(); expect(label(tree)).toContain(h.result.latex)
    click(generate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    expect(h.recovery().mayInsert()).toBe(false)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    click(button(tree, 'Preview')); click(button(h.render(), 'Recover LaTeX')); tree = h.render()
    expect(recoveryContainer(tree)?.props.hidden).toBe(false)
    const retry = h.beginLoad(); h.render(); h.finishLoad(retry, 'ready'); tree = h.render()
    expect(h.recovery().key).toBe(key); expect(label(tree)).toContain(h.result.latex)
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce(); h.unmount()
  })

  it('fences generation and insertion synchronously when source reload begins before a parent render', async () => {
    const h = await harness(); const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const insert = button(h.render(), 'Insert at cursor')
    expect(h.recovery().canStart).toBe(true); const load = h.beginLoad()
    // Static props are still from the ready render. Live source guards must win.
    expect(h.recovery().canStart).toBe(true); expect(h.recovery().mayStart()).toBe(false)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    h.render(); h.finishLoad(load, 'ready'); h.render(); click(insert)
    expect(h.onInsert).toHaveBeenCalledOnce(); h.unmount()
  })

  it.each(['pending-ready', 'error-ready', 'missing-session-ready', 'token-rotation', 'same-owner-session-refresh'])('renews only source admission during %s render before any passive fetch effect', async transition => {
    const h = await harness(false); h.render(); const priorLoad = h.beginLoad(); h.finishLoad(priorLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    let tree = h.render(); const insert = button(tree, 'Insert at cursor'); const recoveryKey = h.recovery().key
    const priorEpoch = h.source().epoch
    const priorSession = h.sessionReference()
    expect(h.authReady()).toBe(true)
    if (transition === 'pending-ready') {
      h.readiness(true); h.render(false); h.readiness(false)
    } else if (transition === 'error-ready') {
      h.readiness(false, new Error('Temporary session lookup failure')); h.render(false); h.readiness(false)
    } else if (transition === 'missing-session-ready') {
      h.auth(null, true); h.render(false); h.auth('owner-A')
    } else if (transition === 'token-rotation') h.token('rotated-token')
    else h.auth('owner-A')
    if (transition === 'pending-ready' || transition === 'error-ready') expect(h.sessionReference()).toBe(priorSession)
    if (transition === 'token-rotation' || transition === 'same-owner-session-refresh') expect(h.sessionReference()).not.toBe(priorSession)
    expect(h.authReady()).toBe(true)
    tree = h.render(false)
    expect(h.source().epoch).toBeGreaterThan(priorEpoch); expect(h.source().status).toBe('unresolved')
    expect(h.source().isSourceReady()).toBe(false); expect(h.recovery().key).toBe(recoveryKey)
    expect(recoveryContainer(tree)).toBeDefined(); expect(label(tree)).toContain('Create a saved fragment')
    expect(label(tree)).toContain(h.result.latex)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(priorLoad.identity.alive).toBe(true) // Passive cleanup has not run.
    expect(h.source().ownsLoad(priorLoad)).toBe(false); expect(h.finishLoad(priorLoad, 'ready')).toBe(false)
    const sourceIdentityCheck = vi.fn(() => true)
    expect(actualSourceLoadIsActive({ cancelled: false, sourceLoad: priorLoad, ownsSourceLoad: h.source().ownsLoad,
      isCurrentOfflinePdfIdentity: sourceIdentityCheck, ownerAtStart: 'owner-A', resumeId: 'document-A', generationAtStart: 1 })).toBe(false)
    expect(sourceIdentityCheck).not.toHaveBeenCalled()
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    const latest = h.beginLoad(); expect(h.source().ownsLoad(latest)).toBe(true)
    expect(h.finishLoad(latest, 'ready')).toBe(true); tree = h.render(false)
    expect(h.recovery().mayStart()).toBe(true); expect(h.recovery().mayInsert()).toBe(true)
    expect(h.recovery().key).toBe(recoveryKey); click(insert); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce()
    h.render(); h.unmount()
  })

  it('preserves verified source readiness and recovery across harmless renders of the same stable session', async () => {
    const h = await harness(false); h.render(); const loaded = h.beginLoad(); h.finishLoad(loaded, 'ready'); h.render()
    draft(h); const epoch = h.source().epoch; const key = h.recovery().key; const session = h.sessionReference()
    h.render(false); h.render(false)
    expect(h.sessionReference()).toBe(session); expect(h.source().epoch).toBe(epoch)
    expect(h.source().isSourceReady()).toBe(true); expect(h.source().ownsLoad(loaded)).toBe(true)
    expect(h.recovery().key).toBe(key); expect(h.recovery().mayStart()).toBe(true)
    expect(h.recovery().mayInsert()).toBe(true); expect(h.api.generateLatex).not.toHaveBeenCalled()
    h.render(); h.unmount()
  })

  it('keeps an admitted completion and copy across token rotation before effects while rejecting superseded source loads', async () => {
    const h = await harness(false); h.render(); const originalLoad = h.beginLoad(); h.finishLoad(originalLoad, 'ready'); h.render()
    const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const generate = button(draft(h), 'Generate fragment'); click(generate); h.render(); const key = h.recovery().key
    const oldPendingSourceLoad = h.beginLoad(); h.render(false)
    h.token('fresh-session-token'); h.render(false)
    expect(h.source().ownsLoad(oldPendingSourceLoad)).toBe(false)
    pending.resolve(h.result); await settle(); let tree = h.render(false)
    expect(label(tree)).toContain(h.result.latex); expect(h.recovery().key).toBe(key)
    expect(h.finishLoad(oldPendingSourceLoad, 'ready')).toBe(false)
    click(generate); await settle(); expect(h.api.generateLatex).toHaveBeenCalledOnce()
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    const newLoad = h.beginLoad(); h.finishLoad(newLoad, 'ready'); tree = h.render(false)
    expect(h.recovery().mayStart()).toBe(true); expect(label(tree)).toContain(h.result.latex)
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce(); h.render(); h.unmount()
  })

  it('permanently retires admission through the actual outer refetch lease cycle when the editor never renders the intermediate state', async () => {
    const h = await harness(false); const actual = await h.useActualSessionAtom(); h.render()
    const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const tree = h.render(); const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment')
    const oldSource = h.source(); const oldRecovery = h.recovery(); const oldLease = h.authority(); const session = h.sessionReference()
    const key = oldRecovery.key; expect(oldSource.isSourceReady()).toBe(true)
    const { completion } = await actual.start(); h.renderBoundaryOnly()
    expect(h.source()).toBe(oldSource); expect(h.authority()).not.toBe(oldLease)
    expect(oldLease.isCurrent()).toBe(true); expect(oldLease.canAdmit()).toBe(false)
    expect(h.authority().recoveryIdentity).toBe(oldLease.recoveryIdentity)
    actual.response.resolve({ data: structuredClone(actual.session), error: null }); await completion; h.renderBoundaryOnly()
    expect(h.source()).toBe(oldSource); expect(h.sessionReference()).toBe(session)
    expect(h.authority().canAdmit()).toBe(true); expect(oldLease.canAdmit()).toBe(false)
    expect(oldLoad.identity.alive).toBe(true); expect(oldSource.isSourceReady()).toBe(false)
    expect(oldSource.ownsLoad(oldLoad)).toBe(false); expect(oldSource.finishLoad(oldLoad, 'ready', 'server')).toBe(false)
    click(generate); click(insert); await click(copy); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    let current = h.render(false); expect(h.recovery().key).toBe(key); expect(label(current)).toContain(h.result.latex)
    expect(label(current)).toContain('Create a saved fragment'); expect(h.recovery().mayStart()).toBe(false)
    const latest = h.beginLoad(); h.finishLoad(latest, 'ready'); current = h.render(false)
    expect(h.recovery().mayStart()).toBe(true); expect(h.recovery().mayInsert()).toBe(true)
    expect(oldSource.isSourceReady()).toBe(false); expect(oldRecovery.mayStart()).toBe(false); expect(oldRecovery.mayInsert()).toBe(false)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(current, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce()
    click(button(h.render(), 'Generate fragment again')); await settle(); expect(h.api.generateLatex).toHaveBeenCalledTimes(2)
    h.unmount()
  })

  it.each(['success', 'failure'])('retires current uncertain offline tickets through actual outer %s refetch without an editor render', async outcome => {
    const h = await harness(false); const actual = await h.useActualSessionAtom(); h.render()
    const loaded = h.beginLoad(); h.finishLoad(loaded, 'ready'); h.render()
    click(button(draft(h), 'Generate fragment')); await settle(); h.render()
    const first = await actual.start(); h.render(false)
    actual.response.resolve({ data: null, error: { status: 503, message: 'Initial uncertainty' } }); await first.completion
    h.render(false); const cold = h.beginLoad(); expect(h.source().ownsLoad(cold)).toBe(true)
    expect(h.finishLoad(cold, 'ready', 'offline')).toBe(true); let tree = h.render(false)
    const copy = button(tree, 'Copy fragment'); const old = h.source(); const lease = h.authority(); const key = h.recovery().key
    const version = cold.identity.version; const sequence = cold.identity.sequence
    expect(old.kind).toBe('offline'); expect(old.isSourceReady()).toBe(false); expect(lease.isAdmissionCurrent()).toBe(true)
    const retry = deferred<{ data: SessionData | null; error: { status: number; message: string } | null }>()
    actual.fetch.mockReturnValueOnce(retry.promise); const completion = actual.atom.value.refetch(); await Promise.resolve(); h.renderBoundaryOnly()
    expect(h.source()).toBe(old); expect(cold.identity.alive).toBe(true); expect(lease.isCurrent()).toBe(true)
    expect(lease.isAdmissionCurrent()).toBe(false); expect(old.beginLoad().sequence).toBe(-1)
    expect(old.ownsLoad(cold)).toBe(false); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    expect(cold.identity.version).toBe(version); expect(cold.identity.sequence).toBe(sequence)
    retry.resolve(outcome === 'success' ? { data: structuredClone(actual.session), error: null }
      : { data: null, error: { status: 503, message: 'Changed uncertainty' } }); await completion; h.renderBoundaryOnly()
    expect(h.source()).toBe(old); expect(old.beginLoad().sequence).toBe(-1); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    await click(copy); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    tree = h.render(false); expect(h.recovery().key).toBe(key); expect(label(tree)).toContain(h.result.latex)
    const current = h.beginLoad(); expect(h.source().ownsLoad(current)).toBe(true)
    expect(h.finishLoad(current, 'ready', outcome === 'success' ? 'server' : 'offline')).toBe(true); tree = h.render(false)
    expect(old.ownsLoad(cold)).toBe(false); expect(old.isSourceReady()).toBe(false)
    if (outcome === 'success') { expect(h.recovery().mayStart()).toBe(true); click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce() }
    else { expect(h.recovery().mayStart()).toBe(false); expect(h.source().kind).toBe('offline') }
    h.unmount()
  })

  it('restores anonymous cold offline source only under its current uncertain outer lease', async () => {
    const h = await harness(false); h.auth(null, false, new Error('Cold offline503')); h.render(false)
    const cold = h.beginLoad(); expect(cold.identity.ownerId).toBeNull(); expect(cold.identity.authReady).toBe(false)
    expect(h.source().ownsLoad(cold)).toBe(true); expect(h.finishLoad(cold, 'ready', 'offline')).toBe(true); h.render(false)
    const old = h.source(); const lease = h.authority(); const version = cold.identity.version; const sequence = cold.identity.sequence
    expect(old.kind).toBe('offline'); expect(old.isSourceReady()).toBe(false); expect(lease.canAdmit()).toBe(false)
    h.readiness(false, new Error('Different cold offline503')); h.renderBoundaryOnly()
    expect(h.source()).toBe(old); expect(lease.isCurrent()).toBe(true); expect(lease.isAdmissionCurrent()).toBe(false)
    expect(old.beginLoad().sequence).toBe(-1); expect(old.ownsLoad(cold)).toBe(false); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    expect(cold.identity.version).toBe(version); expect(cold.identity.sequence).toBe(sequence)
    h.render(false); const current = h.beginLoad(); expect(h.source().ownsLoad(current)).toBe(true)
    expect(h.finishLoad(current, 'ready', 'offline')).toBe(true); h.render(false)
    expect(h.source().isSourceReady()).toBe(false); expect(h.recovery().mayStart()).toBe(false)
    expect(old.beginLoad().sequence).toBe(-1); expect(old.finishLoad(cold, 'ready', 'offline')).toBe(false)
    expect(h.api.generateLatex).not.toHaveBeenCalled(); expect(h.onInsert).not.toHaveBeenCalled(); h.unmount()
  })

  it('blocks stable-data authenticated refetch with cold pending false before effects and waits for fresh source after completion', async () => {
    const h = await harness(false); h.render(); const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    let tree = h.render(); const insert = button(tree, 'Insert at cursor')
    const session = h.sessionReference(); const recoveryKey = h.recovery().key; const epoch = h.source().epoch
    h.refetching(true); tree = h.render(false)
    expect(h.sessionReference()).toBe(session); expect(h.isPending()).toBe(false)
    expect(h.source().epoch).toBeGreaterThan(epoch); expect(h.source().status).toBe('unresolved')
    expect(h.recovery().key).toBe(recoveryKey); expect(label(tree)).toContain('Create a saved fragment')
    expect(label(tree)).toContain(h.result.latex); expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(h.source().ownsLoad(oldLoad)).toBe(false); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.refetching(false); tree = h.render(false)
    expect(h.sessionReference()).toBe(session); expect(h.isPending()).toBe(false); expect(h.authReady()).toBe(true)
    expect(h.source().isSourceReady()).toBe(false); expect(h.recovery().mayStart()).toBe(false)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    const currentLoad = h.beginLoad(); h.finishLoad(currentLoad, 'ready'); tree = h.render(false)
    expect(h.recovery().mayStart()).toBe(true); expect(h.recovery().key).toBe(recoveryKey)
    click(insert); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce(); h.render(); h.unmount()
  })

  it('keeps admitted completion and Copy during real authenticated-refetch flags while a superseded source ticket cannot renew admission', async () => {
    const h = await harness(false); h.render(); const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const pending = deferred<typeof h.result>(); h.api.generateLatex.mockReturnValueOnce(pending.promise)
    const generate = button(draft(h), 'Generate fragment'); click(generate); h.render()
    const session = h.sessionReference(); const key = h.recovery().key
    h.refetching(true); h.render(false); pending.resolve(h.result); await settle(); let tree = h.render(false)
    expect(h.sessionReference()).toBe(session); expect(h.isPending()).toBe(false)
    expect(label(tree)).toContain(h.result.latex); expect(h.recovery().key).toBe(key)
    expect(h.finishLoad(oldLoad, 'ready')).toBe(false); click(generate); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.recovery().mayInsert()).toBe(false)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    h.refetching(false); tree = h.render(false); expect(h.recovery().mayStart()).toBe(false)
    const fresh = h.beginLoad(); h.finishLoad(fresh, 'ready'); tree = h.render(false)
    expect(label(tree)).toContain(h.result.latex); click(button(tree, 'Insert at cursor'))
    expect(h.onInsert).toHaveBeenCalledOnce(); h.render(); h.unmount()
  })

  it.each(['success', 'failure'])('executes the installed Better Auth stable-data %s refetch through actual auth/source/recovery/shell hooks', async outcome => {
    const h = await harness(false); const actual = await h.useActualSessionAtom(); h.render()
    const loaded = h.beginLoad(); h.finishLoad(loaded, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    let tree = h.render(); const insert = button(tree, 'Insert at cursor'); const key = h.recovery().key
    const { completion } = await actual.start(); tree = h.render(false)
    expect(actual.atom.value.data).toBe(actual.session); expect(actual.atom.value.isPending).toBe(false)
    expect(h.source().isSourceReady()).toBe(false); expect(h.source().ownsLoad(loaded)).toBe(false)
    expect(h.finishLoad(loaded, 'ready')).toBe(false); expect(loaded.identity.alive).toBe(true)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(h.recovery().key).toBe(key); expect(label(tree)).toContain('Create a saved fragment')
    expect(label(tree)).toContain(h.result.latex)
    await click(button(tree, 'Copy fragment')); expect(h.writeText).toHaveBeenCalledWith(h.result.latex)
    actual.response.resolve(outcome === 'success' ? { data: structuredClone(actual.session), error: null }
      : { data: null, error: { status: 503, message: 'Synthetic authenticated refetch failure' } })
    await completion; tree = h.render(false)
    expect(actual.atom.value.data).toBe(actual.session); expect(actual.atom.value.isPending).toBe(false)
    expect(actual.atom.value.isRefetching).toBe(false); expect(h.recovery().mayStart()).toBe(false)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(label(tree)).toContain(h.result.latex); expect(h.recovery().key).toBe(key)
    if (outcome === 'failure') {
      actual.fetch.mockResolvedValueOnce({ data: structuredClone(actual.session), error: null })
      await actual.atom.value.refetch(); h.render(false)
    }
    // Successful auth alone never reopens source writes; current source must load.
    expect(h.recovery().mayInsert()).toBe(false)
    const latest = h.beginLoad(); h.finishLoad(latest, 'ready'); tree = h.render(false)
    expect(h.recovery().mayStart()).toBe(true); click(insert); expect(h.onInsert).not.toHaveBeenCalled()
    click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledOnce()
    expect(label(tree)).toContain(h.result.latex); h.render(); h.unmount()
  })

  it('purges recovery on installed Better Auth401 and gives a fresh same-owner session a new incarnation', async () => {
    const h = await harness(false); const actual = await h.useActualSessionAtom(); h.render()
    const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const resolvedTree = h.render(); const insert = button(resolvedTree, 'Insert at cursor'); const copy = button(resolvedTree, 'Copy fragment'); const oldRecovery = h.recovery(); const key = oldRecovery.key
    const { completion } = await actual.start(); h.render(false); h.offlineLoaded()
    actual.response.resolve({ data: null, error: { status: 401, message: 'Synthetic expired session' } }); await completion
    let tree = h.render(false)
    expect(actual.atom.value.data).toBeNull(); expect(label(tree)).toBe(''); expect(h.recovery().key).not.toBe(key)
    expect(h.recovery().mounted).toBe(false); expect(h.recovery().available).toBe(false)
    expect(recoveryContainer(tree)).toBeUndefined(); expect(label(tree)).not.toContain(h.result.latex)
    expect(label(tree)).not.toContain('Create a saved fragment')
    expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await click(copy); oldRecovery.onRecoveryChange(true); await settle()
    expect(h.writeText).not.toHaveBeenCalled()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(h.source().ownsLoad(oldLoad)).toBe(false); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    actual.fetch.mockResolvedValueOnce({ data: structuredClone(actual.session), error: null })
    await actual.atom.value.refetch(); tree = h.render(false)
    expect(actual.atom.value.data?.user.id).toBe(actual.session.user.id)
    expect(h.recovery().key).not.toBe(key); expect(h.recovery().mayStart()).toBe(false)
    const freshLoad = h.beginLoad(); h.finishLoad(freshLoad, 'ready'); tree = h.render()
    expect(label(tree)).not.toContain(h.result.latex); expect(textarea(enter(h)).props.value).toBe('')
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    expect(oldRecovery.mayStart()).toBe(false); expect(oldRecovery.mayInsert()).toBe(false)
    h.unmount()
  })

  it('denies retained Generate, Insert, Copy and source finish through actual outer route ABA before passive cleanup', async () => {
    const h = await harness(false); h.render(); const oldLoad = h.beginLoad(); h.finishLoad(oldLoad, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const tree = h.render(); const insert = button(tree, 'Insert at cursor'); const copy = button(tree, 'Copy fragment'); const old = h.recovery()
    h.document('document-B'); h.render(false); expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await click(copy); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    h.document('document-A'); h.render(false); expect(oldLoad.identity.alive).toBe(true)
    click(generate); click(insert); await click(copy); expect(h.finishLoad(oldLoad, 'ready')).toBe(false)
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled(); expect(h.writeText).not.toHaveBeenCalled()
    expect(old.mayStart()).toBe(false); expect(old.mayInsert()).toBe(false)
    const fresh = h.beginLoad(); h.finishLoad(fresh, 'ready'); h.render(); expect(textarea(enter(h)).props.value).toBe('')
    h.unmount()
  })

  it.each(['document', 'owner', 'logout'])('blocks new-scope source use and rejects old load tickets after %s ABA', async kind => {
    const h = await harness(false); h.render(); const firstLoad = h.beginLoad(); h.finishLoad(firstLoad, 'ready'); h.render()
    draft(h); const oldScope = h.recovery(); const oldLoad = h.beginLoad(); h.render()
    if (kind === 'document') h.document('document-B'); else h.auth(kind === 'logout' ? null : 'owner-B')
    let tree = h.render(); if (kind === 'logout') expect(label(tree)).toBe('')
    else expect(elements(tree).some(node => node.type === 'LoadingSpinner')).toBe(true)
    expect(recoveryContainer(tree)).toBeUndefined(); expect(h.source().isSourceReady()).toBe(false)
    const middleLoad = h.beginLoad(); h.render()
    if (kind === 'document') h.document('document-A'); else h.auth('owner-A')
    tree = h.render(); expect(recoveryContainer(tree)).toBeUndefined()
    expect(h.finishLoad(oldLoad, 'ready')).toBe(false); expect(h.finishLoad(middleLoad, 'ready')).toBe(false)
    expect(h.source().isSourceReady()).toBe(false); expect(h.recovery().mayStart()).toBe(false)
    oldScope.onRecoveryChange(true); expect(oldScope.mayInsert()).toBe(false)
    const currentLoad = h.beginLoad(); h.finishLoad(currentLoad, 'ready'); tree = h.render()
    expect(button(tree, 'Generate LaTeX')).toBeDefined(); expect(h.recovery().available).toBe(false)
    expect(label(enter(h))).not.toContain('Create a saved fragment'); h.unmount()
  })

  it('requires a ready state commit before finishLoad can renew retained generation and insertion', async () => {
    const h = await harness(false); h.render(); const initial = h.beginLoad(); h.finishLoad(initial, 'ready'); h.render()
    const generate = button(draft(h), 'Generate fragment'); click(generate); await settle()
    const insert = button(h.render(), 'Insert at cursor'); const load = h.beginLoad()
    expect(h.finishLoad(load, 'ready')).toBe(true); expect(h.source().isSourceReady()).toBe(false)
    click(generate); click(insert); await settle()
    expect(h.api.generateLatex).toHaveBeenCalledOnce(); expect(h.onInsert).not.toHaveBeenCalled()
    h.render(); expect(h.source().isSourceReady()).toBe(true)
    expect(h.finishLoad(load, 'error')).toBe(true); expect(h.source().isSourceReady()).toBe(false)
    expect(h.finishLoad(load, 'ready')).toBe(true); expect(h.source().isSourceReady()).toBe(false)
    h.render(); expect(h.source().isSourceReady()).toBe(true); h.unmount()
  })

  it('tags offline source success separately and never authorizes generation from a PDF-only recovery', async () => {
    const h = await harness(false); h.render(); const pdf = h.beginLoad(); h.finishLoad(pdf, 'pdf-only')
    let tree = h.render(); expect(h.source().isSourceReady()).toBe(false)
    expect(label(tree)).not.toContain('Generate LaTeX'); expect(recoveryContainer(tree)).toBeUndefined()
    const draftLoad = h.beginLoad(); h.finishLoad(draftLoad, 'ready', 'offline'); tree = h.render()
    expect(h.source().kind).toBe('offline'); expect(h.source().isSourceReady()).toBe(true)
    expect(button(tree, 'Generate LaTeX')).toBeDefined(); h.unmount()
  })

  it.each([401, 'empty'])('the actual saved editor ignores remembered offline owner and loaded flags on confirmed %s session end', status => {
    const authority = actualSessionAuthority({ sessionUserId: null, sessionData: null, sessionLoading: false, sessionRefetching: false,
      sessionError: status === 401 ? { status: 401 } : null, rememberedOfflineOwner: 'owner-A', isConfirmedSessionUnauthorized, useRef: () => ({ current: false }) })
    expect(authority.confirmedSessionEnded).toBe(true); expect(authority.offlinePdfOwnerId).toBeNull()
  })

  it('the actual saved editor never revives remembered offline owner on401→503 and requires settled new owner to clear denial', () => {
    const ref = { current: false }
    const base = { sessionUserId: null, sessionData: null, sessionLoading: false, sessionRefetching: false,
      rememberedOfflineOwner: 'owner-A', isConfirmedSessionUnauthorized, useRef: () => ref }
    expect(actualSessionAuthority({ ...base, sessionError: { status: 401 } }).offlinePdfOwnerId).toBeNull()
    expect(actualSessionAuthority({ ...base, sessionError: { status: 503 } }).offlinePdfOwnerId).toBeNull()
    expect(actualSessionAuthority({ ...base, sessionUserId: 'owner-A', sessionData: {}, sessionRefetching: true, sessionError: null }).offlinePdfOwnerId).toBeNull()
    expect(actualSessionAuthority({ ...base, sessionUserId: 'owner-A', sessionData: {}, sessionError: null }).offlinePdfOwnerId).toBe('owner-A')
  })

  it('binds the editor menu, fallback and persistent shell to the exercised recovery policy', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/app/workspace/[resumeId]/edit/page.tsx'), 'utf8')
    expect(source).toContain("tab === 'generate' && !latexGeneratorRecoveryRef.current?.canAccess")
    expect(source).toContain("rightTab === 'generate' && !latexGeneratorRecovery.canAccess")
    expect(source).toContain("id === 'generate' ? latexGeneratorRecovery.canAccess")
    expect(source).toContain("latexGeneratorRecovery.canStart ? 'Generate LaTeX' : 'Recover LaTeX'")
    expect(source).toContain('<LatexGeneratorRecoveryShell')
    expect(source).toContain('newWorkAllowed: sourceLoadReady &&')
    expect(source).toContain('const canEditDocument = sourceLoadReady &&')
    expect(source).toContain('sourceLoadReady: isSourceReady')
    expect(source).toContain('isRefetching: sessionRefetching')
    expect(source).toContain('!sessionLoading && !sessionRefetching && !sessionError')
    expect(source).toContain('if (sessionLoading || sessionRefetching) return')
    expect(source).toContain("finishSourceLoad(sourceLoad, 'ready', pendingDraft ? 'offline' : 'server')")
    expect(source).toContain("finishSourceLoad(sourceLoad, 'ready', 'offline')")
    expect(source).toContain('latexGeneratorRecovery.mounted && !sourceLoadReady')
    expect(source).not.toContain('<CapabilityGate feature="d14"><LatexGeneratorPanel')
  })
})
