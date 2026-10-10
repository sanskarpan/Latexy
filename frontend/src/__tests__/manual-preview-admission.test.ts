import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { PreviewScheduler } from '@/lib/preview-scheduler'

const pages = {
  guest: readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8'),
  saved: readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8'),
}

// Execute the real page callbacks with an actual scheduler and controlled ACKs.
// DOM and focus behavior are covered by the browser suites, not this harness.
function callback(page: keyof typeof pages, name: string, context: Record<string, unknown>) {
  const ast = ts.createSourceFile('page.tsx', pages[page], ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name && node.initializer) {
      expression = (ts.isCallExpression(node.initializer) ? node.initializer.arguments[0] : node.initializer).getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(expression).not.toBe('')
  const js = ts.transpileModule(`const callback = ${expression}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return runInNewContext(`${js}\ncallback`, context) as (value?: string) => Promise<string | null | undefined>
}

type Admission = { success: boolean; job_id?: string; message?: string }
function harness(page: keyof typeof pages) {
  let content = 'A', busy = false, jobId: string | null = null
  const admissions: Array<{ resolve: (value: Admission) => void; reject: (error: Error) => void }> = []
  const submit = vi.fn(() => new Promise<Admission>((resolve, reject) => admissions.push({ resolve, reject })))
  const editor = { getValue: () => content, markAutoCompileCompiled: vi.fn() }
  const incrementUsage = vi.fn(), recordPreviewAction = vi.fn()
  const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() }
  const identityRef = { current: {} }
  const autoCompileTriggeredRef = { current: false }
  const lastAutoCompileErrorRef = { current: null as string | null }
  let owner = 'owner-A', generation = 1
  let scheduler: PreviewScheduler
  const context = () => ({
    Error, performance, navigator: { onLine: true },
    queuePreview: { submitManual: scheduler.submitManual.bind(scheduler) },
    previewRequestIdentityRef: identityRef,
    offlinePdfOwnerId: owner, offlinePdfIdentityRef: { current: { generation } },
    isCurrentOfflinePdfIdentity: (expectedOwner: string, _resume: string, expectedGeneration: number) => expectedOwner === owner && expectedGeneration === generation,
    isProcessing: false, isAnyRunning: false, isSubmitting: busy,
    setIsSubmitting: (value: boolean) => { busy = value },
    setActiveJobId: (value: string) => { jobId = value }, setCompileJobId: (value: string) => { jobId = value },
    editorRef: { current: editor }, latexContent: content, jobDescription: '',
    preRunSnapshotRef: { current: null }, lastRunOptimizeRef: { current: false },
    cleanBaselineRef: { current: '' }, autoCompileTriggeredRef, lastAutoCompileErrorRef,
    trialBlocked: false, effectiveCanRun: true, notifyTrialBlocked: vi.fn(),
    trialStatus: { fingerprint: 'device', incrementUsage }, resolvedSession: null,
    setMobilePane: vi.fn(), setStagedOptimization: vi.fn(), setOptimizeSnapshot: vi.fn(), setShowOptimizeDiff: vi.fn(),
    apiClient: { compileLatex: submit, optimizeAndCompile: submit },
    recordPreviewAction, toast, editorMode: 'pdf', previewErrorMessage: (error: Error) => error.message,
    canEditDocument: true, isLoading: false, isOnline: true, autoCompileIdentityReady: true,
    resumeId: 'document', compiler: 'lualatex', userInitiatedJobRef: { current: false },
    setLastStartedJobKind: vi.fn(), setRightTab: vi.fn(),
  })
  function createScheduler() {
    const next = new PreviewScheduler(async source => await callback(page, 'handleAutoCompile', context())(source) ?? null, () => Date.now())
    next.update(true, false)
    return next
  }
  scheduler = createScheduler()
  return {
    admissions, submit, editor, incrementUsage, recordPreviewAction, toast,
    get scheduler() { return scheduler }, get busy() { return busy }, get jobId() { return jobId },
    edit(value: string) { content = value; scheduler.request(value) },
    changeBuffer(value: string) { content = value },
    manualCallback: () => callback(page, 'runCompile', context()),
    manual: () => callback(page, 'runCompile', context())('compile'),
    changeOwner(nextOwner: string) {
      owner = nextOwner; generation++; identityRef.current = {}; busy = false; jobId = null
      scheduler.dispose(); scheduler = createScheduler()
    },
  }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

for (const page of ['guest', 'saved'] as const) {
  describe(`${page} manual preview admission`, () => {
    it('consumes the same pending auto revision without another paid compile after terminal', async () => {
      const h = harness(page)
      h.edit('A')
      const pending = h.manual()
      expect(h.submit).toHaveBeenCalledOnce()
      h.admissions[0].resolve({ success: true, job_id: 'manual-job' }); await pending
      expect(h.jobId).toBe('manual-job')
      expect(h.recordPreviewAction).toHaveBeenCalledExactlyOnceWith('manual-job', expect.any(Number))
      h.scheduler.complete('manual-job')
      await vi.advanceTimersByTimeAsync(30_000)
      expect(h.submit).toHaveBeenCalledOnce()
      expect(h.editor.markAutoCompileCompiled).toHaveBeenCalledExactlyOnceWith('A')
      expect(h.incrementUsage).toHaveBeenCalledTimes(page === 'guest' ? 1 : 0)
      h.scheduler.dispose()
    })

    it('does not replay a stale notification when the manual click captures a newer editor buffer', async () => {
      const h = harness(page)
      h.edit('A')
      h.changeBuffer('B') // Monaco has changed before its debounced notification.
      const pending = h.manual()
      expect(h.submit.mock.calls[0]).toEqual([expect.objectContaining({ latex_content: 'B' })])
      h.admissions[0].resolve({ success: true, job_id: 'manual-job' }); await pending
      h.scheduler.complete('manual-job')
      await vi.advanceTimersByTimeAsync(30_000)
      expect(h.submit).toHaveBeenCalledOnce()
      h.scheduler.dispose()
    })

    it('submits only the newest later edit after the manual job finishes', async () => {
      const h = harness(page)
      h.edit('A'); const pending = h.manual()
      h.edit('B')
      h.admissions[0].resolve({ success: true, job_id: 'manual-job' }); await pending
      h.edit('C')
      await vi.advanceTimersByTimeAsync(20_000)
      expect(h.submit).toHaveBeenCalledOnce()
      h.scheduler.complete('manual-job')
      await vi.advanceTimersByTimeAsync(0)
      expect(h.submit).toHaveBeenCalledTimes(2)
      expect(h.submit.mock.calls[1]).toEqual([expect.objectContaining({ latex_content: 'C' })])
      h.admissions[1].resolve({ success: true, job_id: 'newest-job' })
      await vi.advanceTimersByTimeAsync(0)
      h.scheduler.complete('newest-job')
      await vi.advanceTimersByTimeAsync(20_000)
      expect(h.submit).toHaveBeenCalledTimes(2)
      expect(h.incrementUsage).toHaveBeenCalledTimes(page === 'guest' ? 2 : 0)
      h.scheduler.dispose()
    })

    it('fences repeated clicks from the same render before React can publish busy state', async () => {
      const h = harness(page)
      h.edit('A')
      const click = h.manualCallback()
      const first = click('compile'), second = click('compile')
      expect(h.submit).toHaveBeenCalledOnce()
      await vi.advanceTimersByTimeAsync(20_000)
      expect(h.submit).toHaveBeenCalledOnce()
      h.admissions[0].resolve({ success: true, job_id: 'manual-job' })
      await Promise.all([first, second])
      h.scheduler.dispose()
    })

    it('fences a stale manual click when automatic admission won the race', async () => {
      const h = harness(page)
      const click = h.manualCallback()
      h.edit('A')
      await vi.advanceTimersByTimeAsync(5_000)
      await click('compile')
      expect(h.submit).toHaveBeenCalledOnce()
      h.admissions[0].resolve({ success: true, job_id: 'auto-job' })
      await vi.advanceTimersByTimeAsync(0)
      h.scheduler.dispose()
    })

    for (const outcome of ['unsuccessful', 'ambiguous'] as const) {
      it(`does not turn a ${outcome} manual admission into an automatic paid retry`, async () => {
        const h = harness(page)
        h.edit('A'); const pending = h.manual()
        if (outcome === 'ambiguous') h.admissions[0].reject(new Error('ACK lost'))
        else h.admissions[0].resolve({ success: false, message: 'Rejected' })
        await pending
        h.edit('A')
        await vi.advanceTimersByTimeAsync(30_000)
        expect(h.submit).toHaveBeenCalledOnce()
        expect(h.busy).toBe(false)
        expect(h.toast.error).toHaveBeenCalledOnce()
        expect(h.incrementUsage).not.toHaveBeenCalled()
        h.scheduler.dispose()
      })
    }

    it('ignores the old admission after an owner round trip and preserves the new busy state', async () => {
      const h = harness(page)
      h.edit('A'); const old = h.manual()
      h.changeOwner('owner-B'); h.changeOwner('owner-A')
      h.edit('new account draft'); const current = h.manual()
      h.admissions[0].resolve({ success: true, job_id: 'old-job' }); await old
      expect(h.jobId).toBeNull()
      expect(h.busy).toBe(true)
      expect(h.editor.markAutoCompileCompiled).not.toHaveBeenCalled()
      expect(h.incrementUsage).not.toHaveBeenCalled()
      h.admissions[1].resolve({ success: true, job_id: 'current-job' }); await current
      expect(h.jobId).toBe('current-job')
      expect(h.busy).toBe(false)
      h.scheduler.complete('current-job')
      await vi.advanceTimersByTimeAsync(30_000)
      expect(h.submit).toHaveBeenCalledTimes(2)
      h.scheduler.dispose()
    })
  })
}
