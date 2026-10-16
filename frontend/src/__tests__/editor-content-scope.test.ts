import { readFileSync, realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import { forgetOfflinePdfOwner, getRememberedOfflinePdfOwner, OFFLINE_PDF_OWNER_KEY } from '@/lib/offline-pdfs'
import { editorRecoveryLoadBoundary } from '@/hooks/useLatexGeneratorRecovery'
import { shouldSubmitInitialPreview } from '@/lib/accepted-artifact-recovery'

let identityCode: string, loadCode: string, pdfCode: string, renderCode: string
beforeAll(() => {
  const source = ts.createSourceFile('editor/page.tsx', readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const component = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ResumeEditPage') as ts.FunctionDeclaration
  const statements = [...component.body!.statements]
  const declaration = (name: string) => statements.find(node => ts.isVariableStatement(node) && node.declarationList.declarations.some(item => item.name.getText(source) === name))!
  const next = (node: ts.Statement) => statements[statements.indexOf(node) + 1]
  const initial = declaration('initialPreviewIdentityRef'), denied = declaration('offlineIdentityDeniedRef'), loaded = declaration('loadedDocumentScopeRef')
  const identity = [declaration('sessionUnauthorized'), declaration('sessionSignedOut'), declaration('sessionEnded'), initial, next(initial), denied, next(denied), declaration('confirmedSessionEnded'),
    declaration('offlinePdfOwnerId'), loaded, next(loaded), declaration('[committedDocumentContent, setCommittedDocumentContent]'),
    declaration('committedDocumentContentRef'), next(declaration('committedDocumentContentRef'))].map(node => node.getText(source)).join('\n')
  const compile = (code: string) => ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText
  identityCode = compile(`(() => { ${identity}; return { initialPreviewIdentityRef, offlineIdentityDeniedRef, offlinePdfOwnerId, loadedDocumentScopeRef, sessionUnauthorized, confirmedSessionEnded, committedDocumentContent, committedDocumentContentRef, setCommittedDocumentContent } })()`)
  let load: ts.CallExpression | undefined
  const visit = (node: ts.Node) => {
    if (ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect' && node.arguments[0]?.getText(source).includes('const fetchResume =')) load = node
    ts.forEachChild(node, visit)
  }
  visit(component)
  if (!load) throw new Error('Actual saved-editor load effect was not found')
  loadCode = compile(`(${load.arguments[0].getText(source)})()`)
  const pdf = (declaration('loadOfflinePdf') as ts.VariableStatement).declarationList.declarations[0].initializer as ts.CallExpression
  pdfCode = compile(`(${pdf.arguments[0].getText(source)})()`)
  const firstGuard = statements.indexOf(declaration('moreTabIds')) + 1
  const guards = statements.slice(firstGuard).filter(node => ts.isIfStatement(node) || node === declaration('editorLoadBoundary')).map(node => node.getText(source)).join('\n')
  // Execute the actual page return guards, not a separately authored visibility
  // predicate. The sentinel represents reaching its private editor JSX.
  renderCode = compile(`(() => { ${guards}; return { privateEditor: true, title, latexContent, savedSnapshot, pdf: restoredPdf } })()`)
}, 30_000)

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(yes => { resolve = yes })
  return { promise, resolve }
}
const A_SOURCE = 'Private source belonging to document A'
const session = (id: string) => ({ user: { id }, session: { token: `token-${id}` } })
function document(id: string, title: string, latex: string) { return { user_id: id, title, latex_content: latex, metadata: {} } }

function harness() {
  const refs: Array<{ current: unknown }> = []; let slot = 0
  const getResume = vi.fn().mockResolvedValue(document('owner-a', 'Title A', A_SOURCE))
  const getDraft = vi.fn().mockResolvedValue(null), getOfflineCompiledPdf = vi.fn().mockResolvedValue(null)
  const editor = { setValue: vi.fn() }
  const context: Record<string, any> = {
    AbortController, acceptedArtifactRecoveryControllerRef: { current: null },
    shouldSubmitInitialPreview, resumeContentRevisionRef: { current: null },
    sessionData: session('owner-a'), sessionUserId: 'owner-a', sessionLoading: false, sessionRefetching: false, sessionError: null,
    resumeId: 'document-a', rememberedOfflineOwner: 'owner-a', isLoading: false, resumeLoadError: null,
    title: 'Title A', latexContent: A_SOURCE, savedSnapshot: { title: 'Title A', latex: A_SOURCE },
    offlineDraftLoaded: true, offlinePdfLoaded: true, restoredPdf: 'old-pdf-a', navigator: { onLine: true },
    useRef: (value: unknown) => { const index = slot++; refs[index] ??= { current: value }; return refs[index] },
    useState: (value: unknown) => { const index = slot++; refs[index] ??= { current: value }; return [refs[index].current, (next: unknown) => { refs[index].current = next }] },
    isConfirmedSessionUnauthorized,
    isCurrentOfflinePdfIdentity: (owner: string | null, id: string) => owner === context.offlinePdfOwnerId && id === context.resumeId,
    offlinePdfIdentityRef: { current: { generation: 1 } },
    beginSuggestionDocumentLoad: () => ({}), finishSuggestionDocumentLoad: () => true,
    beginSourceLoad: () => { context.sourceLoadStatus = 'loading'; return {} },
    finishSourceLoad: (_ticket: unknown, status: string) => { context.sourceLoadStatus = status; return true }, ownsSourceLoad: () => true,
    editorRecoveryLoadBoundary, latexGeneratorRecovery: { mounted: false }, interviewRecovery: { mounted: false }, sourceLoadStatus: 'ready',
    apiClient: { getResume, getAcademicCVReport: vi.fn().mockResolvedValue({}) }, getDraft, getOfflineCompiledPdf,
    editorRef: { current: editor },
    React: { createElement: () => ({ privateEditor: false }) }, LoadingSpinner: () => null, SessionLoadError: () => null, AlertCircle: () => null, Link: () => null,
    setTitle: (value: string) => { context.title = value }, setLatexContent: (value: string) => { context.latexContent = value },
    setSavedSnapshot: (value: unknown) => { context.savedSnapshot = value }, setIsLoading: (value: boolean) => { context.isLoading = value },
    setResumeLoadError: (value: unknown) => { context.resumeLoadError = value },
    setOfflineDraftLoaded: (value: boolean) => { context.offlineDraftLoaded = value }, setOfflinePdfLoaded: (value: boolean) => { context.offlinePdfLoaded = value },
    setPreviewBlob: (value: unknown) => { context.restoredPdf = value }, setRightTab: vi.fn(),
  }
  const source = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')
  for (const name of source.match(/\bset[A-Z]\w+/g) ?? []) context[name] ??= vi.fn()
  const render = (owner: string | null = context.sessionUserId, id = context.resumeId) => {
    context.sessionUserId = owner; context.sessionData = owner ? session(owner) : null; context.resumeId = id; slot = 0
    Object.assign(context, runInNewContext(identityCode, context))
    return runInNewContext(renderCode, context) as { privateEditor?: boolean; title?: string; latexContent?: string; pdf?: string }
  }
  const startLoad = () => runInNewContext(loadCode, context)
  const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve() }
  const load = async () => { startLoad(); await settle(); return render() }
  render()
  return { context, getResume, getDraft, getOfflineCompiledPdf, editor, render, startLoad, settle, load,
    pdf: () => runInNewContext(pdfCode, context) as Promise<boolean> }
}

afterEach(() => vi.unstubAllGlobals())

describe('actual saved-editor private content incarnation', () => {
  it('cannot restore remembered private content on a new offline503 mount after a cold authoritative401 purge', async () => {
    const stored = new Map([[OFFLINE_PDF_OWNER_KEY, 'owner-a']])
    vi.stubGlobal('window', { localStorage: { getItem: (key: string) => stored.get(key) ?? null, removeItem: (key: string) => stored.delete(key) } })
    const header = ts.createSourceFile('GlobalHeader.tsx', readFileSync(new URL('../components/GlobalHeader.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const component = header.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'GlobalHeader') as ts.FunctionDeclaration
    const effect = component.body!.statements.find(node => ts.isExpressionStatement(node) && node.getText(header).includes('const previousOwner = lastOfflinePdfOwnerRef.current')) as ts.ExpressionStatement
    const code = ts.transpileModule(`(${(effect.expression as ts.CallExpression).arguments[0].getText(header)})()`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
    const purge = vi.fn().mockResolvedValue(undefined)
    runInNewContext(code, { effectiveUserId: undefined, confirmedNoSession: isConfirmedSessionUnauthorized({ status: 401 }),
      lastOfflinePdfOwnerRef: { current: null }, forgetOfflinePdfOwner, clearAllDrafts: purge, clearCompileQueue: purge, clearAllOfflineCompiledPdfs: purge })
    expect(getRememberedOfflinePdfOwner()).toBeNull(); expect(purge).toHaveBeenCalledTimes(3)
    const h = harness(); h.context.sessionError = { status: 503 }; h.context.navigator.onLine = false
    h.context.rememberedOfflineOwner = getRememberedOfflinePdfOwner(); h.render(null)
    await h.load()
    expect(h.context.offlinePdfOwnerId).toBeNull(); expect(h.getDraft).not.toHaveBeenCalled(); expect(h.getOfflineCompiledPdf).not.toHaveBeenCalled()
    expect(h.render()?.privateEditor).not.toBe(true)
  })

  // These retained-page owner/document cases are defense-in-depth lifecycle
  // probes: the real account boundary and Next segment key also remount them.
  it.each(['owner', 'document', 'owner-aba', 'document-aba'] as const)('hides prior source/offline flags before effects on %s change', async change => {
    const h = harness(); expect((await h.load()).privateEditor).toBe(true)
    if (change.startsWith('owner')) { h.render('owner-b'); if (change === 'owner-aba') h.render('owner-a') }
    else { h.render('owner-a', 'document-b'); if (change === 'document-aba') h.render('owner-a', 'document-a') }
    expect(h.context.isLoading).toBe(false); expect(h.context.offlineDraftLoaded).toBe(true); expect(h.context.offlinePdfLoaded).toBe(true)
    expect(h.render().privateEditor).not.toBe(true)
    h.getResume.mockResolvedValueOnce(document(h.context.sessionUserId, 'Fresh title', 'Fresh current source'))
    expect((await h.load()).privateEditor).toBe(true); expect(h.render().latexContent).toBe('Fresh current source')
  })

  it.each(['401', 'logout'] as const)('masks cached source immediately after %s and cannot revive it on a later network error', async invalidation => {
    const h = harness(); await h.load(); h.context.navigator.onLine = false
    h.context.sessionError = invalidation === '401' ? { status: 401 } : null
    expect(h.render(null)?.privateEditor).not.toBe(true); expect(h.context.offlinePdfOwnerId).toBeNull()
    h.context.sessionError = { status: 503 }
    expect(h.render(null)?.privateEditor).not.toBe(true); expect(h.context.offlinePdfOwnerId).toBeNull()
    h.context.sessionError = null; expect(h.render('owner-a')?.privateEditor).not.toBe(true)
    expect((await h.load()).privateEditor).toBe(true)
  })

  it('retains loaded same-owner source through refetch and transient network errors', async () => {
    const h = harness(); await h.load(); h.getResume.mockClear()
    h.context.sessionRefetching = true
    expect(h.render().privateEditor).toBe(true); h.startLoad(); expect(h.getResume).not.toHaveBeenCalled()
    h.context.sessionRefetching = false; h.context.sessionError = { status: 503 }
    expect(h.render().privateEditor).toBe(true); expect(h.render().latexContent).toBe(A_SOURCE)
  })

  it('rejects an old same-token source load after A→B→A before passive cleanup', async () => {
    const h = harness(); await h.load(); const old = deferred<ReturnType<typeof document>>()
    h.getResume.mockReturnValueOnce(old.promise); h.startLoad()
    h.render('owner-b'); h.render('owner-a')
    old.resolve(document('owner-a', 'Stale title', 'Stale source')); await h.settle()
    expect(h.context.title).toBe('Title A'); expect(h.context.latexContent).toBe(A_SOURCE); expect(h.render().privateEditor).not.toBe(true)
    h.getResume.mockResolvedValueOnce(document('owner-a', 'Fresh title', 'Fresh source'))
    expect((await h.load()).privateEditor).toBe(true); expect(h.render().latexContent).toBe('Fresh source')
  })

  it.each(['draft-load', 'pdf-action'] as const)('restores PDF-only B without exposing retained draft A through %s', async recovery => {
    const h = harness(); h.context.sessionError = { status: 503 }; h.context.navigator.onLine = false; h.render(null)
    h.getDraft.mockResolvedValueOnce({ title: 'Offline title A', latexContent: A_SOURCE, savedAt: '2026-10-13T12:00:00Z' })
    expect((await h.load()).privateEditor).toBe(true); expect(h.render().latexContent).toBe(A_SOURCE)
    expect(h.render(null, 'document-b').privateEditor).not.toBe(true)
    h.getOfflineCompiledPdf.mockResolvedValueOnce({ title: 'Offline PDF B', pdf: 'pdf-b' })
    if (recovery === 'draft-load') await h.load()
    else expect(await h.pdf()).toBe(true)
    expect(h.render().privateEditor).toBe(true); expect(h.render().title).toBe('Offline PDF B'); expect(h.render().latexContent).toBe('')
    expect(h.context.savedSnapshot).toEqual({ title: 'Offline PDF B', latex: '' }); expect(h.editor.setValue).toHaveBeenLastCalledWith('')
    expect(h.render().pdf).toBe('pdf-b')
  })
})

describe('actual saved-editor React concurrent content publication', () => {
  it.each(['server-source', 'offline-draft', 'pdf-action'] as const)('keeps queued %s private states masked until their scope commits', async recovery => {
    // Use the installed React18 concurrent reconciler. Immediate mock setters
    // cannot detect a sync-priority render ahead of async/default-lane updates.
    const require = createRequire(import.meta.url)
    const fiber = realpathSync(require.resolve('@react-three/fiber/package.json'))
    const React = require(require.resolve('react', { paths: [fiber] }))
    const makeReconciler = require(require.resolve('react-reconciler', { paths: [fiber] }))
    const constants = require(require.resolve('react-reconciler/constants', { paths: [fiber] }))
    const renderer = makeReconciler({
      now: Date.now, supportsMutation: true, isPrimaryRenderer: true,
      getRootHostContext: () => ({}), getChildHostContext: () => ({}),
      prepareForCommit: () => null, resetAfterCommit: () => {},
      shouldSetTextContent: () => false, createInstance: () => ({}), createTextInstance: () => ({}),
      appendInitialChild: () => {}, finalizeInitialChildren: () => false,
      appendChild: () => {}, appendChildToContainer: () => {}, removeChild: () => {}, removeChildFromContainer: () => {},
      clearContainer: () => {}, prepareUpdate: () => null, commitUpdate: () => {}, commitTextUpdate: () => {},
      scheduleTimeout: setTimeout, cancelTimeout: clearTimeout, noTimeout: -1,
      getCurrentEventPriority: () => constants.DefaultEventPriority, detachDeletedInstance: () => {},
    })
    const root = renderer.createContainer({}, constants.ConcurrentRoot, null, false, null, '', (error: unknown) => { throw error }, null)
    const h = harness()
    let owner: string | null = recovery === 'server-source' ? 'owner-a' : null
    let id = 'document-a', visible: any, force!: () => void
    if (recovery !== 'server-source') {
      // Cold anonymous offline recovery stays in one mounted page/account
      // incarnation while its remembered cache owner changes.
      h.context.sessionError = { status: 503 }; h.context.navigator.onLine = false
      h.getDraft.mockResolvedValueOnce({ title: 'Title A', latexContent: A_SOURCE, savedAt: '2026-10-13T12:00:00Z' })
    }
    function ActualPageContent() {
      const [title, setTitle] = React.useState('Title A')
      const [latexContent, setLatexContent] = React.useState(A_SOURCE)
      const [savedSnapshot, setSavedSnapshot] = React.useState({ title: 'Title A', latex: A_SOURCE })
      const [isLoading, setIsLoading] = React.useState(false)
      const [offlineDraftLoaded, setOfflineDraftLoaded] = React.useState(true)
      const [offlinePdfLoaded, setOfflinePdfLoaded] = React.useState(true)
      const [restoredPdf, setPreviewBlob] = React.useState('old-pdf-a')
      const [, update] = React.useState(0); force = () => update((value: number) => value + 1)
      Object.assign(h.context, { title, setTitle, latexContent, setLatexContent, savedSnapshot, setSavedSnapshot, isLoading, setIsLoading,
        offlineDraftLoaded, setOfflineDraftLoaded, offlinePdfLoaded, setOfflinePdfLoaded, restoredPdf, setPreviewBlob,
        useRef: React.useRef, useState: React.useState, sessionUserId: owner, sessionData: owner ? session(owner) : null, resumeId: id })
      Object.assign(h.context, runInNewContext(identityCode, h.context))
      visible = runInNewContext(renderCode, h.context)
      return null
    }
    const flush = () => renderer.flushSync(() => renderer.updateContainer(React.createElement(ActualPageContent), root, null, null))
    const settleCommit = async () => { await new Promise(resolve => setTimeout(resolve, 25)); renderer.flushSync(() => force()) }
    try {
      flush(); h.startLoad(); await h.settle(); await settleCommit()
      expect(visible.privateEditor).toBe(true); expect(visible.latexContent).toBe(A_SOURCE)
      if (recovery === 'server-source') {
        // Explicit retained-page defense probe; real Next document navigation
        // remounts this component before this scope check is needed.
        id = 'document-b'
      } else h.context.rememberedOfflineOwner = 'owner-b'
      flush(); expect(visible.privateEditor).not.toBe(true)
      if (recovery === 'server-source') {
        h.getResume.mockResolvedValueOnce(document('owner-a', 'Title B', 'Private source B'))
        h.startLoad(); await h.settle()
      } else if (recovery === 'offline-draft') {
        h.getDraft.mockResolvedValueOnce({ title: 'Title B', latexContent: 'Private source B', savedAt: '2026-10-13T12:00:00Z' })
        h.startLoad(); await h.settle()
      } else {
        h.getOfflineCompiledPdf.mockResolvedValueOnce({ title: 'PDF B', pdf: 'pdf-b' })
        expect(await h.pdf()).toBe(true)
      }
      // Matching load has queued state, but it has not committed. An unrelated
      // discrete update must not trust a synchronously updated ownership ref.
      renderer.flushSync(() => force())
      expect(visible.privateEditor).not.toBe(true)
      await settleCommit()
      expect(visible.privateEditor).toBe(true)
      expect(visible.title).toBe(recovery === 'pdf-action' ? 'PDF B' : 'Title B')
      expect(visible.latexContent).toBe(recovery === 'pdf-action' ? '' : 'Private source B')
      expect(visible.savedSnapshot).toEqual({ title: visible.title, latex: visible.latexContent })
      if (recovery === 'pdf-action') expect(visible.pdf).toBe('pdf-b')
    } finally {
      renderer.flushSync(() => renderer.updateContainer(null, root, null, null))
    }
  })
})
