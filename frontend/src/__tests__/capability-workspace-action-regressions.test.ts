import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { installFindCapabilityActions, OPTIONAL_FIND_ACTIONS } from '@/lib/editor-find-capability'

function read(relative: string) {
  return ts.createSourceFile(relative, readFileSync(new URL(relative, import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
}
const optimize = read('../app/workspace/[resumeId]/optimize/page.tsx')
const coverLetter = read('../app/workspace/[resumeId]/cover-letter/page.tsx')
const tryPage = read('../app/try/page.tsx')
const editorPage = read('../app/workspace/[resumeId]/edit/page.tsx')
const builderPage = read('../app/workspace/builder/[resumeId]/page.tsx')
const newBuilderPage = read('../app/workspace/builder/new/page.tsx')
const newResumePage = read('../app/workspace/new/page.tsx')
const workspacePage = read('../app/workspace/page.tsx')
const templateCard = read('../components/TemplateCard.tsx')
const elementHistory = read('../components/ElementVersionHistoryPanel.tsx')

// Execute the real handler body, rather than testing a parallel policy copy.
function action(source: ts.SourceFile, name: string, context: Record<string, unknown> = {}) {
  let expression: ts.Expression | undefined
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name && node.initializer) {
      expression = ts.isCallExpression(node.initializer) && node.initializer.expression.getText(source) === 'useCallback'
        ? node.initializer.arguments[0] : node.initializer
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  expect(expression, name).toBeDefined()
  const scope = { canRef: { current: () => false }, ...context }
  const js = ts.transpileModule(`const action = ${expression!.getText(source)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return new Function(...Object.keys(scope), `${js}\nreturn action`)(...Object.values(scope)) as (...args: unknown[]) => Promise<unknown>
}

describe('workspace optional-action regressions', () => {
  it('tracks an owned admitted optimization after revocation but blocks applying its source', async () => {
    let resolveAdmission!: (value: { success: boolean; job_id: string }) => void
    const optimizeAndCompile = vi.fn(() => new Promise(resolve => { resolveAdmission = resolve }))
    const can = vi.fn(() => true)
    const setAiJobId = vi.fn()
    const handler = action(editorPage, 'runAiOptimize', {
      canRef: { current: can }, offlinePdfOwnerId: 'owner-a', resumeId: 'resume-a',
      offlinePdfIdentityRef: { current: { generation: 1 } }, isCurrentOfflinePdfIdentity: () => true,
      editorRef: { current: { getValue: () => 'source' } }, latexContent: 'source',
      aiBaselineRef: { current: null }, setStagedAiLatex: vi.fn(), setCompareData: vi.fn(),
      setIsAiSubmitting: vi.fn(), apiClient: { optimizeAndCompile }, jobDescription: '',
      optLevel: 'balanced', targetSections: [], customInstructions: '', model: 'gpt-4o-mini',
      compiler: 'pdflatex', userInitiatedJobRef: { current: false }, setAiJobId,
      setLastStartedJobKind: vi.fn(), toast: { success: vi.fn(), error: vi.fn() }, editorMode: 'source',
    })
    const submission = handler()
    can.mockReturnValue(false)
    resolveAdmission({ success: true, job_id: 'admitted-job' })
    await submission
    expect(setAiJobId).toHaveBeenCalledExactlyOnceWith('admitted-job')
    const apply = action(editorPage, 'applyOptimizationCandidate', { canRef: { current: can } })
    expect(apply('proposed source', false)).toBe(false)
  })

  it('blocks blank/import/template creation when either core creation grant is off and hides the CTA', async () => {
    const createResume = vi.fn()
    await action(newResumePage, 'handleCreate', {
      canRef: { current: (feature: string) => feature !== 'c01' },
      apiClient: { createResume },
    })()
    expect(createResume).not.toHaveBeenCalled()
    await action(newResumePage, 'handleCreate', {
      canRef: { current: (feature: string) => feature !== 'b01' },
      apiClient: { createResume },
    })()
    expect(createResume).not.toHaveBeenCalled()
    expect(newResumePage.getFullText()).toContain("can('b01') &&\n    can('c01')")
    expect(templateCard.getFullText()).toContain('{allowUse && onSelect && <button')
  })

  it('blocks guided builder resume creation when source edit or new-resume creation is disabled', async () => {
    const createBuilderResume = vi.fn()
    for (const denied of ['b01', 'c01']) {
      await action(newBuilderPage, 'handleCreate', {
        canRef: { current: (feature: string) => feature !== denied },
        apiClient: { createBuilderResume },
      })()
    }
    expect(createBuilderResume).not.toHaveBeenCalled()
    expect(newBuilderPage.getFullText()).toContain("!canRef.current('b01') || !canRef.current('c01') || !canRef.current('b08')")
  })

  it('blocks workspace fork before API access unless fork, creation, and content editing are granted', async () => {
    const forkResume = vi.fn()
    await action(workspacePage, 'handleFork', {
      canRef: { current: (feature: string) => feature !== 'c01' },
      apiClient: { forkResume },
    })('resume-id', 'Copy')
    expect(forkResume).not.toHaveBeenCalled()
    expect(workspacePage.getFullText()).toContain("!canRef.current('b11') || !canRef.current('b01') || !canRef.current('c01')")
  })

  it.each([
    ['runOptimization', 'd01'],
    ['runOptimization', 'd18'],
    ['runOptimization', 'c01'],
    ['runOptimization', 'c05'],
    ['handleIndustryOverride', 'd19'],
    ['handleLocaleOverride', 'd19'],
    ['handleCreateVariant', 'b11'],
    ['handleCreateVariant', 'b01'],
    ['handleCreateVariant', 'c01'],
    ['handleExplainError', 'd13'],
    ['handleTrimToOnePage', 'c12'],
    ['handleScrapeUrl', 'e11'],
    ['handleAutoCompile', 'c06'],
    ['handleApplyReviewedChanges', 'd03'],
  ])('blocks %s when %s alone is denied, before state or network access', async (name, denied) => {
    const can = vi.fn((feature: string) => feature !== denied)
    await action(optimize, name, { canRef: { current: can } })('test')
    expect(can).toHaveBeenCalledWith(denied)
  })

  it('blocks builder reattachment and file import separately from the b08 route', async () => {
    const updateBuilderResume = vi.fn().mockResolvedValue({
      template_family: 'classic', resume: { structured_version: 2, latex_content: 'updated source' },
    })
    let c01 = false
    let b08 = true
    const confirm = vi.fn(() => true)
    const setSaving = vi.fn()
    const canRef = { current: (feature: string) => feature === 'c01' ? c01 : feature === 'b08' ? b08 : false }
    const common = {
      canRef,
      isCurrentRequest: () => true,
      window: { confirm },
      editRevision: { current: 1 },
      saveRequestId: { current: 0 },
      setSaving,
      ensureCompatible: vi.fn(async () => undefined),
      apiClient: { updateBuilderResume },
      resumeId: 'resume-id', title: 'Title', selectedTemplateId: 'template-id', structured: {},
      setTemplateFamily: vi.fn(), savedVersionRef: { current: 1 },
      savedBuilderRef: { current: null }, savedLatexRef: { current: 'old source' },
      setBuilderStatus: vi.fn(), dirtyRef: { current: true }, setDirty: vi.fn(),
      setSaveError: vi.fn(), toast: { success: vi.fn(), error: vi.fn() },
      mountedRef: { current: true },
    }
    await action(builderPage, 'forceReattach', common)()
    expect(confirm).not.toHaveBeenCalled()
    expect(updateBuilderResume).not.toHaveBeenCalled()

    c01 = true
    b08 = false
    await action(builderPage, 'forceReattach', common)()
    expect(confirm).not.toHaveBeenCalled()
    expect(updateBuilderResume).not.toHaveBeenCalled()

    c01 = true
    b08 = true
    await action(builderPage, 'forceReattach', common)()
    expect(updateBuilderResume).toHaveBeenCalledOnce()
    expect(updateBuilderResume).toHaveBeenCalledWith('resume-id', expect.objectContaining({ force_reattach: true }))

    updateBuilderResume.mockClear()
    let finishCompatibility!: () => void
    const pendingCompatibility = new Promise<void>((resolve) => { finishCompatibility = resolve })
    const staleAction = action(builderPage, 'forceReattach', {
      ...common,
      ensureCompatible: () => pendingCompatibility,
    })()
    await Promise.resolve()
    c01 = false
    finishCompatibility()
    await staleAction
    expect(updateBuilderResume).not.toHaveBeenCalled()

    expect(builderPage.getFullText()).toContain("const contentEditAllowed = can('c01')")
    expect(builderPage.getFullText()).toContain('{contentEditAllowed && can(\'b08\') && <button type="button" onClick={() => void forceReattach()}')
    await action(newBuilderPage, 'handleSeedUpload', { isCurrentRequest: () => true })({ name: 'resume.pdf' })
    const error = vi.fn()
    await action(newBuilderPage, 'handleSeedUpload', {
      canRef: { current: (feature: string) => feature !== 'b07' },
      isCurrentRequest: () => true,
      toast: { error },
    })({ name: 'resume.json', type: 'application/json' })
    expect(error).toHaveBeenCalledOnce()
  })

  it('blocks new element snapshots but preserves stored-history recovery', async () => {
    await action(elementHistory, 'saveSnapshot')()
    const source = elementHistory.getFullText()
    const restore = source.slice(source.indexOf('const actOnVersion'), source.indexOf('const loadOlder'))
    expect(restore).toContain('restoreResumeElementVersion')
    expect(restore).not.toContain('canRef.current')
  })

  it('keeps sibling writing tools independently reachable', () => {
    const editor = read('../components/LaTeXEditor.tsx').getFullText()
    expect(editor).toContain("['d06', 'd07', 'd10'].some(can) ? onWritingAssistantAction : undefined")
    expect(editor).toContain('monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => onCompileRef.current?.()')
    expect(editor).toContain('monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => onSaveRef.current?.()')
    expect(editorPage.getFullText()).toContain("canEditDocument && ['d06', 'd07', 'd10'].some(can) && <WritingAssistantWidget")
  })

  it('blocks cover-letter generation and automatic compilation while retaining admitted manual compilation', async () => {
    await action(coverLetter, 'runGeneration')()
    await action(coverLetter, 'handleAutoCompile')('source')
    const compileLatex = vi.fn().mockResolvedValue({ success: true, job_id: 'compile-job' })
    const compile = action(coverLetter, 'compileCurrentContent', {
      canRef: { current: (feature: string) => feature === 'c05' || feature === 'c06' },
      isProcessing: false,
      isSubmitting: false,
      editorRef: { current: { getValue: () => 'source'.repeat(20), markAutoCompileCompiled: vi.fn() } },
      apiClient: { compileLatex },
      setIsSubmitting: vi.fn(),
      setActiveJobId: vi.fn(),
      toast: { error: vi.fn() },
      isCurrentPage: () => true,
      resumeId: 'resume-id',
      sessionUserId: 'user-id',
      activeCoverLetterId: 'cover-letter-id',
    })
    await compile()
    expect(compileLatex).toHaveBeenCalledOnce()
    expect(coverLetter.getFullText()).toContain("disabled={!can('e01') || isProcessing || isSubmitting || !jobDescription.trim()}")
    expect(coverLetter.getFullText()).toContain("autoCompileEnabled={can('c05') && can('c06') && autoCompile}")
    expect(coverLetter.getFullText()).toContain("onCompile={can('c05') ? compileCurrentContent : undefined}")
  })

  it('blocks an anonymous manual compile when anonymous studio is off', async () => {
    await action(tryPage, 'runCompile', { resolvedSession: null })('compile')
    await action(tryPage, 'runCompile', { resolvedSession: null })('combined')
  })

  it('retains authenticated manual compile in the trial editor when a09 is off', async () => {
    await action(tryPage, 'runCompile', { resolvedSession: { user: { id: 'owner' } }, isProcessing: true })('compile')
  })

  it('uses core compilation for explicit editor commands independently of c06', async () => {
    const compileContent = vi.fn()
    await action(optimize, 'handleEditorCompile', { editorRef: { current: { getValue: () => 'source' } }, compileContent })()
    expect(compileContent).toHaveBeenCalledWith('source')
  })

  it('admits optimizer variants only while fork, resume creation, and source editing are enabled', async () => {
    const forkResume = vi.fn().mockResolvedValue({ id: 'variant-id' })
    const setForkPopoverOpen = vi.fn()
    const setForkTitleInput = vi.fn()
    const push = vi.fn()
    await action(optimize, 'handleCreateVariant', {
      canRef: { current: (feature: string) => ['b11', 'b01', 'c01'].includes(feature) },
      isForkingResume: false, setIsForkingResume: vi.fn(), setForkPopoverOpen, setForkTitleInput,
      forkTitleInput: 'Copy', resumeId: 'resume-id', apiClient: { forkResume },
      router: { push }, toast: { error: vi.fn() },
    })()
    expect(forkResume).toHaveBeenCalledOnce()
    expect(setForkPopoverOpen).toHaveBeenCalledWith(false)
    expect(push).toHaveBeenCalledWith('/workspace/variant-id/edit')
    expect(optimize.getFullText()).toContain("!canRef.current('b11') || !canRef.current('b01') || !canRef.current('c01')")
    expect(optimize.getFullText()).toContain("{can('b11') && can('b01') && can('c01') && <>")
  })

  it('requires ATS, optimization, source-edit, and compilation grants for optimizer admission', async () => {
    await action(optimize, 'runOptimization', {
      canRef: { current: (feature: string) => feature !== 'd18' },
    })()
    expect(optimize.getFullText()).toContain("!canRef.current('d01') || !canRef.current('d18') || !canRef.current('c01') || !canRef.current('c05')")
    expect(optimize.getFullText()).toContain("can('d01') && can('d18') && can('c01') && can('c05')")
  })

  it.each([false, true])('routes a newly created linked variant using the current b12 grant (%s)', async (linkedModeAllowed) => {
    let allowed = true
    const push = vi.fn()
    const forkResume = vi.fn(async () => {
      // Model a refresh completing while the create request is in flight.
      allowed = linkedModeAllowed
      return { id: 'new-variant', content_source: 'builder_variant' }
    })
    await action(editorPage, 'handleCreateVariant', {
      canRef: { current: (key: string) => key === 'b12' ? allowed : true },
      isForkingResume: false, setIsForkingResume: vi.fn(), isDirtyRef: { current: false },
      resumeId: 'resume', forkTitleInput: '', apiClient: { forkResume },
      setForkPopoverOpen: vi.fn(), setForkTitleInput: vi.fn(), router: { push },
      toast: { error: vi.fn() },
    })()
    expect(forkResume).toHaveBeenCalledOnce()
    expect(push).toHaveBeenCalledWith(linkedModeAllowed ? '/workspace/variant/new-variant' : '/workspace/new-variant/edit')
  })

  it('rechecks fork permission after awaiting a source save and keeps Cancel reachable', async () => {
    let allowed = true
    const forkResume = vi.fn()
    await action(editorPage, 'handleCreateVariant', {
      canRef: { current: () => allowed }, isForkingResume: false, setIsForkingResume: vi.fn(),
      isDirtyRef: { current: true }, editorRef: { current: { getValue: () => 'latest source' } },
      latexContent: '', resumeId: 'resume', title: 'Title', savedSnapshot: { latex: 'previous' },
      apiClient: { updateResume: async () => { allowed = false }, forkResume },
      setSavedSnapshot: vi.fn(), setLastSavedAt: vi.fn(),
    })()
    expect(forkResume).not.toHaveBeenCalled()
    expect(editorPage.getFullText()).not.toContain('<CapabilityGate feature="b11"><button onClick={() => setForkPopoverOpen(false)}')
  })
})

describe('Monaco native find capability actions', () => {
  function harness() {
    let allowed = false
    const context = { set: vi.fn(), reset: vi.fn() }
    const run = vi.fn().mockResolvedValue(undefined)
    const descriptors = new Map<string, { precondition: string; run: (editor: unknown, ...args: unknown[]) => unknown }>()
    const disposals: ReturnType<typeof vi.fn>[] = []
    const editor = {
      createContextKey: vi.fn(() => context),
      getAction: vi.fn((id: string) => ({ id, label: id, run })),
      addAction: vi.fn((descriptor) => { descriptors.set(descriptor.id, descriptor); const dispose = vi.fn(); disposals.push(dispose); return { dispose } }),
    }
    const installed = installFindCapabilityActions(editor as never, () => allowed)
    return { installed, editor, context, descriptors, disposals, run, setAllowed: (next: boolean) => { allowed = next } }
  }

  it('guards palette and programmatic find actions, including already-open menus during revocation', async () => {
    const h = harness()
    expect(h.descriptors.size).toBe(OPTIONAL_FIND_ACTIONS.length)
    for (const descriptor of h.descriptors.values()) {
      expect(descriptor.precondition).toBe('latexyFindAllowed')
      await descriptor.run(h.editor)
    }
    expect(h.run).not.toHaveBeenCalled()
    h.setAllowed(true); h.installed.update()
    expect(h.context.set).toHaveBeenLastCalledWith(true)
    const find = h.descriptors.get('editor.actions.findWithArgs')!
    await find.run(h.editor, { searchString: 'safe' })
    expect(h.run).toHaveBeenCalledWith({ searchString: 'safe' })
    h.setAllowed(false)
    await find.run(h.editor, { searchString: 'denied' })
    expect(h.run).toHaveBeenCalledTimes(1)
    h.installed.update(); expect(h.context.set).toHaveBeenLastCalledWith(false)
  })

  it('keeps editor instances isolated and unregisters only its own actions', async () => {
    const a = harness(); const b = harness()
    a.setAllowed(true); a.installed.update()
    await a.descriptors.get('actions.find')!.run(a.editor)
    await b.descriptors.get('actions.find')!.run(b.editor)
    expect(a.run).toHaveBeenCalledOnce(); expect(b.run).not.toHaveBeenCalled()
    a.installed.dispose()
    expect(a.disposals.every((dispose) => dispose.mock.calls.length === 1)).toBe(true)
    expect(b.disposals.every((dispose) => dispose.mock.calls.length === 0)).toBe(true)
  })
})

describe('ATS report optional effects', () => {
  const report = read('../components/ATSScoreCard.tsx')
  function effect(needle: string, scope: Record<string, unknown>) {
    let expression = ''
    function visit(node: ts.Node) {
      if (ts.isCallExpression(node) && node.expression.getText(report) === 'useEffect' && node.arguments[0]?.getText(report).includes(needle)) expression = node.arguments[0].getText(report)
      ts.forEachChild(node, visit)
    }
    visit(report)
    expect(expression, needle).toBeTruthy()
    const js = ts.transpileModule(`const effect = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
    return new Function(...Object.keys(scope), `${js}; return effect`)(...Object.values(scope)) as () => (() => void) | undefined
  }

  it('does not fetch benchmarking or profile choices when their independent grants are off', () => {
    const apiClient = { getBenchmark: vi.fn(), getIndustryProfiles: vi.fn(), getATSLocaleProfiles: vi.fn() }
    const setBenchmark = vi.fn(); const setBenchmarkLoading = vi.fn()
    effect('getBenchmark', { benchmarkAllowed: false, score: 80, setBenchmark, setBenchmarkLoading, apiClient })()
    effect('getIndustryProfiles', { profilesAllowed: false, onIndustryOverride: vi.fn(), apiClient })()
    effect('getATSLocaleProfiles', { profilesAllowed: false, onLocaleOverride: vi.fn(), apiClient })()
    expect(apiClient.getBenchmark).not.toHaveBeenCalled()
    expect(apiClient.getIndustryProfiles).not.toHaveBeenCalled()
    expect(apiClient.getATSLocaleProfiles).not.toHaveBeenCalled()
    expect(setBenchmark).toHaveBeenCalledWith(null)
  })

  it('ignores a benchmark response arriving after grant revocation cleans up the effect', async () => {
    let resolve!: (value: unknown) => void
    const pending = new Promise((done) => { resolve = done })
    const setBenchmark = vi.fn(); const setBenchmarkLoading = vi.fn()
    const cleanup = effect('getBenchmark', {
      benchmarkAllowed: true, score: 80, industryKey: 'tech', setBenchmark, setBenchmarkLoading,
      apiClient: { getBenchmark: () => pending },
    })()
    cleanup?.()
    resolve({ percentile: 90 }); await pending; await Promise.resolve(); await Promise.resolve()
    expect(setBenchmark).toHaveBeenCalledTimes(1)
    expect(setBenchmark).toHaveBeenCalledWith(null)
  })
})
