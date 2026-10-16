import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PreviewScheduler } from '@/lib/preview-scheduler'
import type { AccountPreferenceRequestContext } from '@/lib/api-client'
import { isCurrentAcceptedPreviewRecovery, isMatchingAcceptedArtifact, resolveCurrentAcceptedPreviewRecovery, shouldSubmitInitialPreview, type AcceptedPreviewRecoveryResponse } from '@/lib/accepted-artifact-recovery'
import { sha256Bytes } from '@/hooks/useArtifactPreview'

const source = ts.createSourceFile('editor/page.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const component = source.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === 'ResumeEditPage') as ts.FunctionDeclaration
const statements = Array.from(component.body!.statements)
function find(predicate: (node: ts.Node) => boolean) {
  const matches: ts.Node[] = []
  function visit(node: ts.Node) { if (predicate(node)) matches.push(node); ts.forEachChild(node, visit) }
  visit(component)
  return matches
}
const fetchResume = (find((node) => ts.isVariableDeclaration(node) && node.name.getText(source) === 'fetchResume')[0] as ts.VariableDeclaration).initializer!
const runCompile = (find((node) => ts.isVariableDeclaration(node) && node.name.getText(source) === 'runCompile')[0] as ts.VariableDeclaration).initializer!
const autoCompileHandler = (find((node) => ts.isVariableDeclaration(node) && node.name.getText(source) === 'handleAutoCompile')[0] as ts.VariableDeclaration).initializer!
const bootstrapEffect = (find((node) => ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect'
  && node.arguments[0]?.getText(source).includes('const request = initialPreviewRequest'))[0] as ts.CallExpression).arguments[0]
const loadEffect = find((node) => ts.isCallExpression(node) && node.expression.getText(source) === 'useEffect'
  && node.arguments[0]?.getText(source).includes('const fetchResume ='))[0] as ts.CallExpression
const loadActive = ((loadEffect.arguments[0] as ts.ArrowFunction).body as ts.Block).statements
  .filter(ts.isVariableStatement).flatMap(statement => [...statement.declarationList.declarations])
  .find(declaration => declaration.name.getText(source) === 'isActive')!.initializer!
const identityStatement = statements.find((node) => ts.isVariableStatement(node)
  && node.declarationList.declarations.some((item) => item.name.getText(source) === 'initialPreviewIdentityRef'))!
const identityIf = statements[statements.indexOf(identityStatement) + 1]
const identityCode = `${identityStatement.getText(source)}\n${identityIf.getText(source)}`

function evaluate(code: string, context: Record<string, unknown>) {
  const js = ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return runInNewContext(js, context)
}
function deferred<T>() {
  let resolve!: (value: T) => void, reject!: (error: Error) => void
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
async function flushRecovery() {
  for (let i = 0; i < 24; i += 1) await Promise.resolve()
  await vi.advanceTimersByTimeAsync(0)
}

type Identity = { ownerId: string | null; resumeId: string; consumed: boolean }
type Admission = { success: boolean; job_id?: string }
type SourceLoadTicket = { ownerId: string | null; resumeId: string; generation: number; sequence: number }
const initialSource = '\\documentclass{article}\n\\begin{document}\nA sufficiently long managed resume source with verified ownership and revision.\n\\end{document}'

function harness() {
  const grants = new Set<string>()
  let generation = 1
  let sourceLoadSequence = 0
  let currentSourceLoad: SourceLoadTicket | null = null
  let identityRef: { current: Identity } | undefined
  const auth = deferred<void>(), response = deferred<Admission>()
  const dispatch = vi.fn()
  const submit = vi.fn(async (body: unknown, context?: AccountPreferenceRequestContext) => {
    await auth.promise
    if (context && !context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch(body)
    return response.promise
  })
  const automatic = vi.fn().mockResolvedValue('automatic-job')
  let scheduler = new PreviewScheduler(automatic, () => Date.now())
  scheduler.update(false, false) // Bootstrap keeps the original c05-only policy.
  const admissions: Promise<string | null>[] = []
  const editor = { setValue: vi.fn(), getValue: vi.fn<() => string | undefined>(() => undefined), markAutoCompileCompiled: vi.fn() }
  const getResume = vi.fn(() => Promise.resolve({ title: 'Owned resume', latex_content: initialSource, metadata: {}, user_id: 'owner-A' }))
  const getLatestAcceptedArtifact = vi.fn()
  const setCompileJobId = vi.fn(), setLastStartedJobKind = vi.fn()
  const finishSourceLoad = vi.fn((ticket: SourceLoadTicket, status: string, kind: string | null = null) => {
    if (ticket !== currentSourceLoad || ticket.ownerId !== context.sessionUserId
      || ticket.resumeId !== context.resumeId || ticket.generation !== generation) return false
    context.sourceLoadStatus = status
    context.sourceLoadKind = kind
    context.sourceLoadReady = status === 'ready'
    return true
  })
  const context: Record<string, unknown> = {
    Error, AbortController, performance, TextEncoder, navigator: { onLine: true }, shouldSubmitInitialPreview,
    useCallback: (callback: (...args: never[]) => unknown) => callback,
    isCurrentAcceptedPreviewRecovery, isMatchingAcceptedArtifact, resolveCurrentAcceptedPreviewRecovery, sha256Bytes,
    resumeContentRevisionRef: { current: null },
    offlinePdfIdentityRef: { current: { ownerId: 'owner-A', resumeId: 'resume-A', generation: 1 } },
    recoveredAcceptedArtifact: null,
    acceptedArtifactRecoveryPendingIdentity: null,
    acceptedArtifactRecoveryRetryIdentity: null,
    acceptedArtifactRecoveryController: new AbortController(),
    acceptedArtifactRecoveryControllerRef: { current: null },
    sessionUserId: 'owner-A', offlinePdfOwnerId: 'owner-A', resumeId: 'resume-A', isLoading: false, sessionLoading: false, initialPreviewRequest: null,
    loadContextRef: { current: null },
    entitlementsLoading: true, entitlementsLoaded: false,
    canEditDocument: true, autoCompileIdentityReady: true, isOnline: true,
    sourceLoadStatus: 'unresolved', sourceLoadKind: null, sourceLoadReady: false, finishSourceLoad,
    ownsSourceLoad: (ticket: SourceLoadTicket) => ticket === currentSourceLoad && ticket.ownerId === context.sessionUserId
      && ticket.resumeId === context.resumeId && ticket.generation === generation,
    can: (key: string) => grants.has(key), canRef: { current: (key: string) => grants.has(key) },
    checkpointRecoverySourceForRead: (_preview: unknown, _identity: unknown, source: string) => source,
    checkpointRecoveryIdentity: null,
    editorMode: 'pdf', latexContent: initialSource, sourceAtRenderRef: { current: initialSource },
    editorRef: { current: editor }, compiler: 'pdflatex', initialPreviewCompilerRef: { current: 'pdflatex' },
    currentCheckpointRecoveryPreview: null, compileJobId: null, aiJobId: null,
    isAnyRunning: false, isSubmitting: false, isAiSubmitting: false,
    isCurrentOfflinePdfIdentity: (owner: string | null, resume: string, expectedGeneration: number) => owner === context.sessionUserId
      && resume === context.resumeId && expectedGeneration === generation,
    setIsSubmitting: (value: boolean) => { context.isSubmitting = value },
    setCompileJobId: (job: string) => { setCompileJobId(job); context.compileJobId = job }, setLastStartedJobKind,
    apiClient: {
      getAuthToken: () => 'owner-token', compileLatex: submit,
      getAcademicCVReport: () => Promise.resolve({}),
      getResume,
      getLatestAcceptedArtifact,
    },
    getDraft: () => Promise.resolve(null),
    isActive: () => true,
    loadedDocumentScopeRef: { current: { ownerId: 'owner-A', resumeId: 'resume-A' } },
    // This harness executes the preview/source loader; the real suggestion
    // authority and lifecycle boundary are exercised in suggestion-owner-scope.
    suggestionLoad: {}, finishSuggestionDocumentLoad: vi.fn(() => true),
    setResumeLoadError: (error: unknown) => { if (error) throw new Error(String(error)) },
    setIsLoading: (value: boolean) => { context.isLoading = value },
  }
  for (const node of find((node) => ts.isIdentifier(node) && /^set[A-Z]/.test(node.text))) {
    const name = (node as ts.Identifier).text
    context[name] ??= vi.fn()
  }
  context.setLatexContent = (value: string) => { context.latexContent = value; (context.sourceAtRenderRef as { current: string }).current = value }
  context.setCompiler = (value: string) => { context.compiler = value }
  context.setInitialPreviewRequest = (request: unknown) => { context.initialPreviewRequest = request }
  context.setRecoveredAcceptedArtifact = (artifact: unknown) => { context.recoveredAcceptedArtifact = artifact }
  context.setAcceptedArtifactRecoveryPendingIdentity = vi.fn((identity: unknown) => { context.acceptedArtifactRecoveryPendingIdentity = identity })
  context.setAcceptedArtifactRecoveryRetryIdentity = vi.fn((identity: unknown) => { context.acceptedArtifactRecoveryRetryIdentity = identity })
  context.blocksAcceptedArtifactRecoveryAdmission = (source: string) => {
    const identity = context.acceptedArtifactRecoveryPendingIdentity ?? context.acceptedArtifactRecoveryRetryIdentity as Record<string, unknown> | null
    return Boolean(identity && (identity as Record<string, unknown>).source === source)
  }
  function renderIdentity(owner = context.sessionUserId as string, resume = context.resumeId as string) {
    context.sessionUserId = owner; context.resumeId = resume
    identityRef = evaluate(`(() => { ${identityCode}; return initialPreviewIdentityRef })()`, {
      ...context, useRef: (current: Identity) => identityRef ?? { current },
    })
    context.initialPreviewIdentityRef = identityRef
    const documentScopeRef = context.loadedDocumentScopeRef as { current: { ownerId: string; resumeId: string } }
    if (documentScopeRef.current.ownerId !== owner || documentScopeRef.current.resumeId !== resume) {
      documentScopeRef.current = { ownerId: owner, resumeId: resume }
    }
    context.documentScope = documentScopeRef.current
    return identityRef!.current
  }
  renderIdentity()
  function exposeQueue() {
    context.queuePreview = {
      submitManual: (source: string, submit: () => Promise<string | null>) => {
        const pending = scheduler.submitManual(source, submit)
        admissions.push(pending)
        return pending
      },
    }
  }
  exposeQueue()
  return {
    context, grants, auth, response, submit, dispatch, automatic, editor, setCompileJobId, setLastStartedJobKind, finishSourceLoad,
    getResume, getLatestAcceptedArtifact,
    get scheduler() { return scheduler }, get identity() { return identityRef!.current },
    effect: () => evaluate(`(${bootstrapEffect.getText(source)})()`, context),
    async load() {
      currentSourceLoad = { ownerId: context.sessionUserId as string | null, resumeId: context.resumeId as string,
        generation, sequence: ++sourceLoadSequence }
      context.sourceLoad = currentSourceLoad
      context.sourceLoadStatus = 'loading'; context.sourceLoadKind = null; context.sourceLoadReady = false
      context.initialPreviewIdentity = identityRef!.current
      context.generationAtStart = generation
      const loadContext: Record<string, unknown> = { ...context, cancelled: false, ownerAtStart: context.sessionUserId }
      ;(loadContext.acceptedArtifactRecoveryControllerRef as { current: AbortController | null }).current =
        loadContext.acceptedArtifactRecoveryController as AbortController
      ;(context.loadContextRef as { current: Record<string, unknown> | null }).current = loadContext
      loadContext.isActive = evaluate(`(${loadActive.getText(source)})`, loadContext)
      await evaluate(`(${fetchResume.getText(source)})()`, loadContext)
    },
    grant() { grants.add('c05'); context.entitlementsLoading = false; context.entitlementsLoaded = true },
    edit(source: string) { (context.setLatexContent as (value: string) => void)(source) },
    switchOwner(owner: string, resume = context.resumeId as string) {
      generation++; renderIdentity(owner, resume)
      currentSourceLoad = null; context.sourceLoadReady = false; context.sourceLoadStatus = 'unresolved'
      scheduler.dispose(); scheduler = new PreviewScheduler(automatic, () => Date.now()); scheduler.update(false, false); exposeQueue()
      context.compileJobId = null; context.aiJobId = null; context.isSubmitting = false
    },
    renderIdentity,
    manual: () => evaluate(`(${runCompile.getText(source)})()`, context),
    auto: (content: string) => (evaluate(`(${autoCompileHandler.getText(source)})`, context) as (content: string) => Promise<unknown>)(content),
    switchCompiler(compiler: string) {
      context.compiler = compiler; (context.initialPreviewCompilerRef as { current: string }).current = compiler
      scheduler.dispose(); scheduler = new PreviewScheduler(automatic, () => Date.now()); scheduler.update(false, false); exposeQueue()
    },
    async settle(value: Admission = { success: true, job_id: 'initial-job' }) {
      auth.resolve(); response.resolve(value); await Promise.all(admissions)
    },
    dispose() { scheduler.dispose() },
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('saved accepted artifact recovery through the actual extracted loader', () => {
  const sourceHash = async () => sha256Bytes(new TextEncoder().encode(initialSource))
  const acceptedArtifact = (hash: string) => ({
    job_id: 'accepted-job', artifact_id: 'b'.repeat(64), document_id: 'resume-A', content_revision: 7,
    source_sha256: hash, branch: 'draft' as const, owner_epoch: 2, compiler: 'pdflatex',
    settings_sha256: 'c'.repeat(64), pdf_sha256: 'd'.repeat(64), pdf_size: 1234, page_count: 1,
    preview_url: '/download/accepted-job/preview/fixture',
  })
  function enableVersionedOwnedResume(h: ReturnType<typeof harness>) {
    h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
      metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
    h.getLatestAcceptedArtifact.mockImplementationOnce(async () => ({
      artifact: null, source_sha256: await sourceHash(), content_revision: 7,
    }))
  }

  it('restores a matching accepted artifact and does not bootstrap another compile', async () => {
    const h = harness(), hash = await sourceHash()
    h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
      metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
    h.getLatestAcceptedArtifact.mockResolvedValueOnce({ artifact: acceptedArtifact(hash), source_sha256: hash, content_revision: 7 })
    await h.load()
    await flushRecovery()
    await vi.waitFor(() => expect(h.context.recoveredAcceptedArtifact).not.toBeNull())
    expect(h.getLatestAcceptedArtifact).toHaveBeenCalledOnce()
    expect(h.context.recoveredAcceptedArtifact).toMatchObject({
      ownerId: 'owner-A', resumeId: 'resume-A', generation: 1, source: initialSource, contentRevision: 7,
      artifact: { job_id: 'accepted-job', type: 'artifact.ready', source_sha256: hash },
    })
    h.grant(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    expect(h.context.initialPreviewRequest).toBeNull()
    h.dispose()
  })

  it('allows one normal bootstrap after an authoritative no-artifact response', async () => {
    const h = harness(); enableVersionedOwnedResume(h)
    await h.load(); await flushRecovery()
    await vi.waitFor(() => expect(h.context.initialPreviewRequest).not.toBeNull())
    h.effect()
    expect(h.getLatestAcceptedArtifact).toHaveBeenCalledOnce()
    expect(h.context.recoveredAcceptedArtifact).toBeNull()
    expect(h.context.initialPreviewRequest).not.toBeNull()
    h.grant(); h.effect()
    expect(h.submit).toHaveBeenCalledOnce()
    await h.settle()
    h.effect(); await vi.advanceTimersByTimeAsync(40_000)
    expect(h.submit).toHaveBeenCalledOnce()
    h.dispose()
  })

  it('keeps source ready but blocks preview admission until accepted-artifact recovery is conclusive', async () => {
    const h = harness(), hash = await sourceHash()
    h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
      metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
    const recovery = deferred<AcceptedPreviewRecoveryResponse>()
    h.getLatestAcceptedArtifact.mockReturnValueOnce(recovery.promise as never)

    await h.load()
    expect(h.context.sourceLoadReady).toBe(true)
    expect(h.context.isLoading).toBe(false)
    expect((h.context.blocksAcceptedArtifactRecoveryAdmission as (source: string) => boolean)(initialSource)).toBe(true)
    expect(h.context.initialPreviewRequest).toBeNull()
    h.grant()
    h.grants.add('c06'); h.grants.add('c01')
    h.effect()
    await h.manual()
    await h.auto(initialSource)
    expect(h.submit).not.toHaveBeenCalled()

    recovery.resolve({ artifact: null, source_sha256: hash, content_revision: 7 })
    await flushRecovery()
    await vi.waitFor(() => expect(h.context.initialPreviewRequest).not.toBeNull())
    expect(h.context.initialPreviewRequest).not.toBeNull()
    h.effect()
    expect(h.submit).toHaveBeenCalledOnce()
    await h.settle()
    h.dispose()
  })

  it('suppresses bootstrap when the recovery read is unavailable', async () => {
    const h = harness()
    h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
      metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
    h.getLatestAcceptedArtifact.mockRejectedValueOnce(new Error('503'))
    await h.load(); await flushRecovery()
    await vi.waitFor(() => expect(h.context.acceptedArtifactRecoveryRetryIdentity).not.toBeNull())
    h.effect(); h.grant(); h.effect()
    expect(h.context.recoveredAcceptedArtifact).toBeNull()
    expect(h.context.initialPreviewRequest).toBeNull()
    expect(h.context.setAcceptedArtifactRecoveryRetryIdentity).toHaveBeenCalledWith(expect.objectContaining({
      ownerId: 'owner-A', resumeId: 'resume-A', generation: 1,
      source: initialSource, contentRevision: 7,
    }))
    expect(h.context.setOfflinePdfError).toHaveBeenCalledWith('Could not check the accepted PDF. Retry to check it again.')
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it('keeps an identity-bound GET retry after the initial recovery request is aborted by cleanup', async () => {
    const h = harness()
    h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
      metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
    const recovery = deferred<AcceptedPreviewRecoveryResponse>()
    h.getLatestAcceptedArtifact.mockReturnValueOnce(recovery.promise as never)
    const loading = h.load()
    for (let i = 0; i < 8 && !h.getLatestAcceptedArtifact.mock.calls.length; i++) await Promise.resolve()
    expect(h.getLatestAcceptedArtifact).toHaveBeenCalledOnce()
    await loading
    expect(h.context.sourceLoadReady).toBe(true)
    expect(h.context.isLoading).toBe(false)
    ;((h.context.loadContextRef as { current: Record<string, unknown> }).current).cancelled = true
    recovery.reject(new DOMException('Aborted', 'AbortError'))
    await flushRecovery()

    expect(h.context.acceptedArtifactRecoveryRetryIdentity).toBeNull()
    expect(h.context.initialPreviewRequest).toBeNull()
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['response-source', 'response-revision', 'artifact-identity'] as const)(
    'does not publish or bootstrap a mismatched %s response', async mismatch => {
      const h = harness(), hash = await sourceHash()
      h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
        metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
      const badArtifact = acceptedArtifact(hash)
      if (mismatch === 'artifact-identity') badArtifact.document_id = 'resume-B'
      h.getLatestAcceptedArtifact.mockResolvedValueOnce({
        artifact: badArtifact,
        source_sha256: mismatch === 'response-source' ? 'e'.repeat(64) : hash,
        content_revision: mismatch === 'response-revision' ? 8 : 7,
      })
      await h.load(); await flushRecovery()
      await vi.waitFor(() => expect(h.context.acceptedArtifactRecoveryRetryIdentity).not.toBeNull())
      h.effect(); h.grant(); h.effect()
      expect(h.context.recoveredAcceptedArtifact).toBeNull()
      expect(h.context.initialPreviewRequest).toBeNull()
      expect(h.submit).not.toHaveBeenCalled()
      h.dispose()
    },
  )

  it.each(['owner', 'revision', 'source'] as const)(
    'drops a late recovery after live %s changes', async change => {
      const h = harness(), hash = await sourceHash()
      h.getResume.mockResolvedValueOnce({ title: 'Owned resume', latex_content: initialSource,
        metadata: {}, user_id: 'owner-A', content_revision: 7 } as never)
      const late = deferred<{ artifact: ReturnType<typeof acceptedArtifact>; source_sha256: string; content_revision: number }>()
      h.getLatestAcceptedArtifact.mockReturnValueOnce(late.promise as never)
      const pending = h.load()
      for (let i = 0; i < 8 && !h.getLatestAcceptedArtifact.mock.calls.length; i++) await Promise.resolve()
      expect(h.getLatestAcceptedArtifact).toHaveBeenCalledOnce()
      await pending
      const context = h.context
      if (change === 'owner') {
        (context.offlinePdfIdentityRef as { current: { ownerId: string | null } }).current.ownerId = 'owner-B'
      } else if (change === 'revision') {
        (context.resumeContentRevisionRef as { current: number | null }).current = 8
      } else {
        h.edit('new source after recovery began')
      }
      late.resolve({ artifact: acceptedArtifact(hash), source_sha256: hash, content_revision: 7 })
      await flushRecovery(); h.grant(); h.effect()
      expect(h.context.recoveredAcceptedArtifact).toBeNull()
      expect(h.context.initialPreviewRequest).toBeNull()
      expect(h.submit).not.toHaveBeenCalled()
      h.dispose()
    },
  )
})

describe('saved initial preview entitlement readiness and admission', () => {
  it('waits for the loaded header title rather than an unrelated structured-mode badge', () => {
    const fixture = readFileSync(new URL('../../e2e/quality/resume-structure-flow.spec.ts', import.meta.url), 'utf8')
    expect(fixture).toContain("page.locator('header').getByText('Structured resume', { exact: true })")
    expect(fixture).not.toContain("page.getByText('Structured resume', { exact: true })")
    expect(fixture).toContain('expect(jobs.size).toBe(0)')
    expect(fixture).toContain('expect(jobs.size).toBe(1)')
  })

  it('loads source before grants and admits exactly once, immediately after c05 resolves without c06', async () => {
    const h = harness()
    await h.load(); h.effect()
    expect(h.context.latexContent).toBe(initialSource)
    expect(h.finishSourceLoad).toHaveBeenCalledExactlyOnceWith(h.context.sourceLoad, 'ready', 'server')
    expect(h.context.sourceLoadReady).toBe(true)
    expect(h.submit).not.toHaveBeenCalled()
    expect(h.identity.consumed).toBe(false)
    h.grant(); h.effect()
    expect(h.submit).toHaveBeenCalledExactlyOnceWith({ latex_content: initialSource, resume_id: 'resume-A', compiler: 'pdflatex' }, expect.objectContaining({ authToken: 'owner-token' }))
    expect(h.dispatch).not.toHaveBeenCalled()
    await h.settle()
    expect(h.dispatch).toHaveBeenCalledOnce()
    expect(h.setCompileJobId).toHaveBeenCalledExactlyOnceWith('initial-job')
    expect(h.editor.markAutoCompileCompiled).toHaveBeenCalledExactlyOnceWith(initialSource)
    expect(h.context.isSubmitting).toBe(false)
    h.effect(); h.grants.delete('c05'); h.effect(); h.grant(); h.effect(); await h.load(); h.effect()
    await vi.advanceTimersByTimeAsync(40_000)
    expect(h.submit).toHaveBeenCalledOnce()
    expect(h.context.latexContent).toBe(initialSource)
    h.dispose()
  })

  it('works when grants arrive before source without changing the resume-load dependencies', async () => {
    const h = harness(); h.grant(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    await h.load(); h.effect(); await h.settle()
    expect(h.submit).toHaveBeenCalledOnce()
    expect(loadEffect.arguments[1].getText(source)).not.toMatch(/\b(can|entitlementsLoaded|entitlementsLoading)\b/)
    expect(loadEffect.arguments[0].getText(source)).not.toContain('apiClient.compileLatex')
    h.dispose()
  })

  it('tags the restored pending local source as offline without admitting preview before grants resolve', async () => {
    const h = harness()
    h.context.getDraft = () => Promise.resolve({ title: 'Local draft', latexContent: initialSource, syncStatus: 'pending', savedAt: new Date().toISOString() })
    await h.load(); h.effect()
    expect(h.context.latexContent).toBe(initialSource)
    expect(h.finishSourceLoad).toHaveBeenCalledExactlyOnceWith(h.context.sourceLoad, 'ready', 'offline')
    expect(h.context.sourceLoadReady).toBe(true); expect(h.context.sourceLoadKind).toBe('offline')
    expect(h.submit).not.toHaveBeenCalled()
    h.grant(); h.effect(); await h.settle(); expect(h.submit).toHaveBeenCalledOnce(); h.dispose()
  })

  it.each(['denied', 'failed'])('consumes a settled %s capability decision without compiling after regrant', async (outcome) => {
    const h = harness(); await h.load()
    h.context.entitlementsLoading = false; h.context.entitlementsLoaded = outcome === 'denied'; h.effect()
    expect(h.identity.consumed).toBe(true)
    h.grant(); h.effect(); await h.load(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['controlled', 'source-buffer', 'empty-source-buffer', 'compiler', 'recovery', 'offline'])('never bootstraps a stale snapshot after %s drift while grants are pending', async (drift) => {
    const h = harness(); await h.load()
    if (drift === 'controlled') h.edit('newer local draft')
    if (drift === 'source-buffer' || drift === 'empty-source-buffer') { h.context.editorMode = 'source'; h.editor.getValue.mockReturnValue(drift === 'source-buffer' ? 'newer buffer' : '') }
    if (drift === 'compiler') h.context.compiler = 'lualatex'
    if (drift === 'recovery') h.context.currentCheckpointRecoveryPreview = { source: 'recovered source' }
    if (drift === 'offline') h.context.isOnline = false
    h.grant(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    h.edit(initialSource); h.context.compiler = 'pdflatex'; h.context.currentCheckpointRecoveryPreview = null; h.context.isOnline = true; h.editor.getValue.mockReturnValue(initialSource); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['A → B', 'A → B → A', 'resume change'])('ignores the old snapshot across %s and gives the new incarnation its own demand', async (change) => {
    const h = harness(); await h.load(); const oldIdentity = h.identity
    if (change === 'resume change') h.switchOwner('owner-A', 'resume-B')
    else { h.switchOwner('owner-B'); if (change === 'A → B → A') h.switchOwner('owner-A') }
    h.grant(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    expect(h.identity).not.toBe(oldIdentity)
    await h.load(); h.effect(); await h.settle()
    expect(h.submit).toHaveBeenCalledOnce()
    h.dispose()
  })

  it('renews the actual render token for A → B → A before any effect can run', async () => {
    const h = harness(); await h.load(); const firstA = h.identity
    expect(h.renderIdentity()).toBe(firstA)
    h.renderIdentity('owner-B'); h.renderIdentity('owner-A'); h.grant(); h.effect()
    expect(h.identity).not.toBe(firstA)
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it.each(['compile', 'AI', 'manual-ACK'])('lets newer %s admission win without another bootstrap after terminal', async (kind) => {
    const h = harness(); await h.load()
    if (kind === 'compile') h.context.compileJobId = 'newer-compile'
    if (kind === 'AI') h.context.aiJobId = 'newer-AI'
    const manualResponse = deferred<string>()
    const manual = vi.fn(() => manualResponse.promise)
    const pending = kind === 'manual-ACK' ? h.scheduler.submitManual(initialSource, manual) : Promise.resolve(null)
    h.grant(); h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    manualResponse.resolve('manual-job'); await pending
    h.scheduler.complete('manual-job'); h.context.compileJobId = null; h.context.aiJobId = null; h.effect()
    expect(h.submit).not.toHaveBeenCalled()
    h.dispose()
  })

  it('keeps bootstrap and manual clicks behind one shared ACK fence', async () => {
    const h = harness(); await h.load(); h.grant(); h.effect()
    const manual = vi.fn().mockResolvedValue('duplicate-job')
    await h.scheduler.submitManual(initialSource, manual)
    expect(manual).not.toHaveBeenCalled()
    await h.settle(); h.scheduler.complete('initial-job'); h.effect()
    expect(h.submit).toHaveBeenCalledOnce()
    h.dispose()
  })

  it('refuses a new-compiler manual click while the old bootstrap ACK is pending, then fences its old dispatch', async () => {
    const h = harness(); await h.load(); h.grant(); h.effect()
    h.switchCompiler('lualatex')
    await h.manual()
    expect(h.submit).toHaveBeenCalledOnce()
    await h.settle()
    expect(h.dispatch).not.toHaveBeenCalled()
    expect(h.setCompileJobId).not.toHaveBeenCalled()
    expect(h.context.isSubmitting).toBe(false)
    h.effect()
    expect(h.submit).toHaveBeenCalledOnce()
    h.dispose()
  })

  it.each(['owner', 'ABA', 'source', 'grant', 'compiler'])('fences actual dispatch after %s changes in the bootstrap auth wait', async (change) => {
    const h = harness(); await h.load(); h.grant(); h.effect()
    if (change === 'owner' || change === 'ABA') { h.switchOwner('owner-B'); if (change === 'ABA') h.switchOwner('owner-A') }
    if (change === 'source') h.edit('newer source')
    if (change === 'grant') h.grants.delete('c05')
    if (change === 'compiler') (h.context.initialPreviewCompilerRef as { current: string }).current = 'lualatex'
    await h.settle()
    expect(h.dispatch).not.toHaveBeenCalled()
    expect(h.setCompileJobId).not.toHaveBeenCalled()
    h.grant(); h.effect()
    expect(h.submit).toHaveBeenCalledOnce()
    h.dispose()
  })

  it.each(['grant', 'compiler'])('tracks an already-admitted owned response after %s change without rewriting newer source', async (change) => {
    const h = harness(); await h.load(); h.grant(); h.effect(); h.auth.resolve()
    await Promise.resolve(); await Promise.resolve()
    expect(h.dispatch).toHaveBeenCalledOnce()
    if (change === 'grant') h.grants.delete('c05')
    if (change === 'compiler') (h.context.initialPreviewCompilerRef as { current: string }).current = 'lualatex'
    h.edit('newer unsaved source'); await h.settle()
    expect(h.setCompileJobId).toHaveBeenCalledExactlyOnceWith('initial-job')
    expect(h.context.latexContent).toBe('newer unsaved source')
    h.dispose()
  })

  it('ignores an old owned response after switching accounts while a new admission stays busy', async () => {
    const h = harness(); await h.load(); h.grant(); h.effect(); h.auth.resolve()
    await Promise.resolve(); await Promise.resolve()
    h.switchOwner('owner-B'); h.context.isSubmitting = true; await h.settle()
    expect(h.setCompileJobId).not.toHaveBeenCalled()
    expect(h.context.isSubmitting).toBe(true)
    h.dispose()
  })

  it.each(['unsuccessful', 'ambiguous'])('does not replay a %s bootstrap admission on refresh', async (outcome) => {
    const h = harness(); await h.load(); h.grant(); h.effect()
    if (outcome === 'ambiguous') { h.response.reject(new Error('Unknown admission')); h.auth.resolve(); await h.settle() }
    else await h.settle({ success: false })
    h.effect(); await h.load(); h.effect(); await vi.advanceTimersByTimeAsync(40_000)
    expect(h.submit).toHaveBeenCalledOnce()
    expect(h.setCompileJobId).not.toHaveBeenCalled()
    h.dispose()
  })
})
