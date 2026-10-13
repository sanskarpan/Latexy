import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from 'typescript'

const pageSource = readFileSync(resolve(process.cwd(), 'src/app/workspace/[resumeId]/edit/page.tsx'), 'utf8')
const pageAst = ts.createSourceFile('page.tsx', pageSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const pageFunction = pageAst.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ResumeEditPage') as ts.FunctionDeclaration
const pageStatements = pageFunction.body!.statements
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
function findLoadEffect(node: ts.Node) {
  if (ts.isCallExpression(node) && node.expression.getText(pageAst) === 'useEffect'
    && node.arguments[0]?.getText(pageAst).includes('const fetchResume =')) {
    const body = (node.arguments[0] as ts.ArrowFunction).body as ts.Block
    const declaration = body.statements.filter(ts.isVariableStatement).flatMap(statement => [...statement.declarationList.declarations])
      .find(item => item.name.getText(pageAst) === 'isActive')
    sourceLoadActiveExpression = declaration!.initializer!.getText(pageAst)
  }
  ts.forEachChild(node, findLoadEffect)
}
findLoadEffect(pageFunction)
const activeLoadJs = ts.transpileModule(`const isActive = ${sourceLoadActiveExpression}`, {
  compilerOptions: { target: ts.ScriptTarget.ES2022 },
}).outputText
const actualSourceLoadIsActive = new Function('context', `with (context) { ${activeLoadJs}; return isActive() }`) as
  (context: Record<string, unknown>) => boolean

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
  let rawSession: { user: { id: string }; session: { token: string } } | null = { user: { id: rawOwner }, session: { token } }
  let pending = false; let authError: Error | null = null; let grants = new Set(all); let sourceWritable = true
  let isLoading = !autoLoad; let resumeLoadError: string | null = null
  let offlineDraftLoaded = false; let offlinePdfLoaded = false
  let dirty = false; let instance: Instance
  const instances = new Map<string, Instance>()
  const effects = new Map<Instance, Map<number, () => void>>()
  let seen = new Set<string>()
  const same = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index])))
  vi.doMock('react', async original => ({
    ...await original<typeof import('react')>(),
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
  vi.doMock('next/navigation', () => ({ useRouter: () => router }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({
    data: rawSession, isPending: pending, error: authError,
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
    const sourceScope = useEditorSourceLoadScope(auth.session?.user?.id ?? null, documentId, auth.session,
      Boolean(auth.session?.user?.id && !auth.isPending && !auth.error))
    source = sourceScope
    const { beginLoad, finishLoad } = sourceScope
    useEffect(() => {
      if (!autoLoad) return
      const ticket = beginLoad()
      finishLoad(ticket, 'ready', 'server')
    }, [beginLoad, finishLoad])
    const sourceLoadReady = source.isSourceReady() && !isLoading && !resumeLoadError
    recovery = useLatexGeneratorRecovery({ ownerId: auth.session?.user?.id ?? null, documentId,
      authReady: Boolean(auth.session?.user?.id && !auth.isPending && !auth.error),
      can: feature => grants.has(feature), newWorkAllowed: sourceLoadReady && sourceWritable,
      sourceLoadReady: source.isSourceReady, active: tab === 'generate' })
    current.current = recovery
    const pageReturn = actualPageLoadGuards({ editorRecoveryLoadBoundary, latexGeneratorRecovery: recovery,
      sourceLoadStatus: source.status, isLoading, resumeLoadError, sessionData: auth.session, sessionError: auth.error,
      offlineDraftLoaded, offlinePdfLoaded, LoadingSpinner: 'LoadingSpinner', Link: 'a', AlertCircle: 'AlertCircle',
      SessionLoadError: 'SessionLoadError' }, React)
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
    if (typeof node.type === 'function') {
      const target = instances.get(nextPath) ?? { slots: [], index: 0, alive: true }
      instances.set(nextPath, target); seen.add(nextPath); target.index = 0
      const previous = instance; instance = target
      const result = (node.type as (props: Record<string, unknown>) => unknown)(node.props)
      instance = previous
      return walk(result, `${nextPath}/component`)
    }
    return { ...node, props: { ...node.props, children: walk(node.props.children, `${nextPath}/children`) } }
  }
  const unmount = () => {
    for (const target of instances.values()) { target.alive = false; target.slots.forEach(slot => slot.cleanup?.()) }
    instances.clear(); effects.clear()
  }
  function render(flushEffects = true) {
    let tree: unknown
    for (let pass = 0; pass < 25; pass++) {
      dirty = false; seen = new Set()
      tree = walk(jsx(Editor, {}), 'editor')
      for (const [key, target] of instances) if (!seen.has(key)) {
        target.alive = false; target.slots.forEach(slot => slot.cleanup?.()); instances.delete(key); effects.delete(target)
      }
      if (!flushEffects) return tree
      const queued = [...effects.entries()]; effects.clear()
      queued.forEach(([target, callbacks]) => { if (target.alive) callbacks.forEach(effect => effect()) })
      if (!dirty) return tree
    }
    throw new Error('Component lifecycle failed to settle')
  }
  return { render, api, result, onInsert, writeText, unmount, recovery: () => recovery,
    sessionReference: () => rawSession,
    authReady: () => Boolean(rawSession && !pending && !authError),
    source: () => source,
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
    expect(retainedShellInsert()).toBe(true); click(button(tree, 'Insert at cursor')); expect(h.onInsert).toHaveBeenCalledWith(h.result.latex)
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
    expect(h.recovery().key).toBe(recoveryKey); click(insert); expect(h.onInsert).toHaveBeenCalledOnce()
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

  it.each(['document', 'owner', 'logout'])('blocks new-scope source use and rejects old load tickets after %s ABA', async kind => {
    const h = await harness(false); h.render(); const firstLoad = h.beginLoad(); h.finishLoad(firstLoad, 'ready'); h.render()
    draft(h); const oldScope = h.recovery(); const oldLoad = h.beginLoad(); h.render()
    if (kind === 'document') h.document('document-B'); else h.auth(kind === 'logout' ? null : 'owner-B')
    let tree = h.render(); expect(elements(tree).some(node => node.type === 'LoadingSpinner')).toBe(true)
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

  it('tags offline source success separately and never authorizes generation from a PDF-only recovery', async () => {
    const h = await harness(false); h.render(); const pdf = h.beginLoad(); h.finishLoad(pdf, 'pdf-only')
    let tree = h.render(); expect(h.source().isSourceReady()).toBe(false)
    expect(label(tree)).not.toContain('Generate LaTeX'); expect(recoveryContainer(tree)).toBeUndefined()
    const draftLoad = h.beginLoad(); h.finishLoad(draftLoad, 'ready', 'offline'); tree = h.render()
    expect(h.source().kind).toBe('offline'); expect(h.source().isSourceReady()).toBe(true)
    expect(button(tree, 'Generate LaTeX')).toBeDefined(); h.unmount()
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
    expect(source).toContain("finishSourceLoad(sourceLoad, 'ready', pendingDraft ? 'offline' : 'server')")
    expect(source).toContain("finishSourceLoad(sourceLoad, 'ready', 'offline')")
    expect(source).toContain('latexGeneratorRecovery.mounted && !sourceLoadReady')
    expect(source).not.toContain('<CapabilityGate feature="d14"><LatexGeneratorPanel')
  })
})
