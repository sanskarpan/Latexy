import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

// Exercise the actual page callbacks with controlled admission promises. This
// isolates their account/busy-state contract without claiming a DOM render.
const source = ts.createSourceFile('try/page.tsx', readFileSync(
  new URL('../app/try/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const page = source.statements.find((node): node is ts.FunctionDeclaration =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'TryPage')!
const statements = page.body!.statements
const declarationIndex = (name: string) => statements.findIndex(node => ts.isVariableStatement(node)
  && node.declarationList.declarations.some(declaration => declaration.name.getText(source) === name))
const identityRenderCode = statements.slice(declarationIndex('previewRequestIdentityRef'), declarationIndex('activeJobAtRenderRef'))
  .map(node => node.getText(source)).join('\n')
const accountReset = statements.find(node => ts.isExpressionStatement(node)
  && ts.isCallExpression(node.expression) && node.expression.expression.getText(source) === 'useEffect'
  && node.expression.arguments[0].getText(source).includes('previewAccountRef.current === previewAccountIdentity')) as ts.ExpressionStatement
const resetCallback = (accountReset.expression as ts.CallExpression).arguments[0]

type Trigger = 'manual' | 'automatic' | 'trim'
type Admission = { success: boolean; job_id?: string; message?: string }
const handlers: Record<Trigger, string> = {
  manual: 'runCompile', automatic: 'handleAutoCompile', trim: 'handleTrimToOnePage',
}

function evaluateCode(code: string, context: Record<string, unknown>) {
  const { outputText } = ts.transpileModule(code, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  })
  return runInNewContext(outputText, context)
}

function evaluateCallback(node: ts.Node, context: Record<string, unknown>): (...args: unknown[]) => Promise<unknown> {
  return evaluateCode(`(${node.getText(source)})`, context)
}

function callback(trigger: Trigger, context: Record<string, unknown>) {
  const declaration = statements.filter(ts.isVariableStatement)
    .flatMap(statement => Array.from(statement.declarationList.declarations))
    .find(node => node.name.getText(source) === handlers[trigger])!
  const initializer = declaration.initializer!
  return evaluateCallback(ts.isCallExpression(initializer) ? initializer.arguments[0] : initializer, context)
}

function harness() {
  let identity = 'anonymous:device'
  let busy = false
  let activeJob: string | null = null
  const admissions: Array<{ resolve: (response: Admission) => void; reject: (error: Error) => void }> = []
  const submit = vi.fn(() => new Promise<Admission>((resolve, reject) => admissions.push({ resolve, reject })))
  let previewRequestIdentityRef: { current: unknown } | undefined
  const previewAccountRef = { current: identity }
  const editor = { getValue: () => 'current source', markAutoCompileCompiled: vi.fn() }
  const autoCompileTriggeredRef = { current: false }
  const lastAutoCompileErrorRef = { current: null as string | null }
  const incrementUsage = vi.fn()
  const toast = { success: vi.fn(), error: vi.fn() }
  const clearPdfPreview = vi.fn()
  const context = () => ({
    Error, performance,
    previewRequestIdentityRef, previewAccountRef, previewAccountIdentity: identity,
    isProcessing: false, isSubmitting: busy,
    setIsSubmitting: (value: boolean) => { busy = value },
    setActiveJobId: (value: string | null) => { activeJob = value },
    setCancelledPreviewJobId: vi.fn(), clearPdfPreview,
    editorRef: { current: editor }, latexContent: 'current source', jobDescription: '',
    preRunSnapshotRef: { current: null }, lastRunOptimizeRef: { current: false },
    cleanBaselineRef: { current: '' }, autoCompileTriggeredRef, lastAutoCompileErrorRef,
    trialBlocked: false, effectiveCanRun: true, notifyTrialBlocked: vi.fn(),
    trialStatus: { fingerprint: 'device', incrementUsage },
    resolvedSession: identity.startsWith('anonymous:') ? null : { user: { id: 'new-account' } },
    setMobilePane: vi.fn(), setStagedOptimization: vi.fn(), setOptimizeSnapshot: vi.fn(), setShowOptimizeDiff: vi.fn(),
    apiClient: { compileLatex: submit, optimizeAndCompile: submit },
    recordPreviewAction: vi.fn(), toast, editorMode: 'pdf', TRIM_INSTRUCTION: 'Trim this resume',
    previewErrorMessage: (error: Error) => error.message,
  })
  const renderIdentity = (nextIdentity = identity) => {
    identity = nextIdentity
    previewRequestIdentityRef = evaluateCode(`(() => { ${identityRenderCode}; return previewRequestIdentityRef })()`, {
      ...context(), useRef: (current: unknown) => previewRequestIdentityRef ?? { current },
    })
    return previewRequestIdentityRef!.current
  }
  renderIdentity()
  return {
    admissions, submit, editor, toast, incrementUsage, autoCompileTriggeredRef, lastAutoCompileErrorRef, clearPdfPreview,
    get busy() { return busy }, get activeJob() { return activeJob }, renderIdentity,
    start(trigger: Trigger) {
      return callback(trigger, context())(trigger === 'manual' ? 'compile' : 'current source')
    },
    reset(nextIdentity = identity) {
      renderIdentity(nextIdentity)
      return evaluateCallback(resetCallback, context())()
    },
  }
}

describe('trial preview admission survives an account change', () => {
  it('leaves a same-account pending admission busy', async () => {
    const h = harness()
    const pending = h.start('manual')
    await h.reset()
    expect(h.busy).toBe(true)
    expect(h.clearPdfPreview).not.toHaveBeenCalled()
    h.admissions[0].resolve({ success: true, job_id: 'current-job' })
    await pending
    expect(h.activeJob).toBe('current-job')
    expect(h.busy).toBe(false)
  })

  it('renews the actual request token synchronously for A → B → A but preserves it on ordinary renders', () => {
    const h = harness()
    const firstA = h.renderIdentity()
    expect(h.renderIdentity()).toBe(firstA)
    const b = h.renderIdentity('new-account:device')
    expect(b).not.toBe(firstA)
    const secondA = h.renderIdentity('anonymous:device')
    expect(secondA).not.toBe(firstA)
    expect(secondA).not.toBe(b)
    expect(h.renderIdentity()).toBe(secondA)
    expect(h.clearPdfPreview).not.toHaveBeenCalled()
  })

  for (const trigger of ['manual', 'automatic', 'trim'] as const) {
    for (const roundTrip of [false, true]) {
      for (const outcome of ['success', 'unsuccessful', 'rejected'] as const) {
        it(`ignores a late ${trigger} ${outcome} during a new admission after ${roundTrip ? 'A → B → A' : 'A → B'}`, async () => {
          const h = harness()
          const oldSubmission = h.start(trigger)
          expect(h.busy).toBe(true)
          expect(h.admissions).toHaveLength(1)

          await h.reset('new-account:device')
          expect(h.busy).toBe(false)
          expect(h.activeJob).toBeNull()
          expect(h.clearPdfPreview).toHaveBeenCalledOnce()
          if (roundTrip) {
            await h.reset('anonymous:device')
            expect(h.busy).toBe(false)
            expect(h.clearPdfPreview).toHaveBeenCalledTimes(2)
          }

          // Both manual and automatic admission must be released by the reset.
          const newSubmission = h.start(trigger === 'manual' ? 'automatic' : 'manual')
          expect(h.admissions).toHaveLength(2)
          expect(h.busy).toBe(true)
          const autoTriggeredBeforeResponse = h.autoCompileTriggeredRef.current
          if (outcome === 'rejected') h.admissions[0].reject(new Error('Old account request failed'))
          else h.admissions[0].resolve({ success: outcome === 'success', job_id: 'old-account-job', message: 'Old account response' })
          await oldSubmission

          expect(h.busy).toBe(true)
          expect(h.activeJob).toBeNull()
          expect(h.editor.markAutoCompileCompiled).not.toHaveBeenCalled()
          expect(h.autoCompileTriggeredRef.current).toBe(autoTriggeredBeforeResponse)
          expect(h.lastAutoCompileErrorRef.current).toBeNull()
          expect(h.incrementUsage).not.toHaveBeenCalled()
          expect(h.toast.success).not.toHaveBeenCalled()
          expect(h.toast.error).not.toHaveBeenCalled()
          await h.start('manual')
          expect(h.admissions).toHaveLength(2)

          h.admissions[1].resolve({ success: true, job_id: 'new-account-job' })
          await newSubmission
          expect(h.activeJob).toBe('new-account-job')
          expect(h.busy).toBe(false)
          expect(h.editor.markAutoCompileCompiled).toHaveBeenCalledExactlyOnceWith('current source')
          expect(h.incrementUsage).toHaveBeenCalledTimes(roundTrip ? 1 : 0)
        })
      }
    }

    it(`surfaces a current ${trigger} failure and releases submission state for retry`, async () => {
      const h = harness()
      const pending = h.start(trigger)
      h.admissions[0].reject(new Error('Current request failed'))
      await pending
      expect(h.busy).toBe(false)
      expect(h.toast.error).toHaveBeenCalledExactlyOnceWith('Current request failed')
      expect(h.activeJob).toBeNull()
      const retry = h.start(trigger)
      expect(h.admissions).toHaveLength(2)
      h.admissions[1].resolve({ success: true, job_id: 'retry-job' })
      await retry
      expect(h.activeJob).toBe('retry-job')
      expect(h.busy).toBe(false)
    })
  }
})
