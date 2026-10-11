import { readFileSync } from 'node:fs'
import React, { type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CapabilityGate from '@/components/CapabilityGate'
import SourcePdfDivider from '@/components/SourcePdfDivider'
import ATSScoreBadge from '@/components/ATSScoreBadge'

const grants = vi.hoisted(() => new Set<string>())
vi.mock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: (key: string) => grants.has(key) }) }))
const read = (path: string) => ts.createSourceFile(path, readFileSync(new URL(path, import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const page = read('../app/try/page.tsx')
const editor = read('../components/LaTeXEditor.tsx')
const editorPage = read('../app/workspace/[resumeId]/edit/page.tsx')
function find(source: ts.SourceFile, predicate: (node: ts.Node) => boolean) {
  const matches: ts.Node[] = []
  function visit(node: ts.Node) { if (predicate(node)) matches.push(node); ts.forEachChild(node, visit) }
  visit(source)
  return matches
}
function initializer(name: string) {
  const node = find(page, (node) => ts.isVariableDeclaration(node) && node.name.getText(page) === name)[0] as ts.VariableDeclaration
  expect(node?.initializer, name).toBeDefined()
  return node.initializer!
}
function execute(expression: ts.Node, scope: Record<string, unknown>) {
  const js = ts.transpileModule(`const value = (${expression.getText()})`, { compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React } }).outputText
  return new Function(...Object.keys(scope), `${js}; return value`)(...Object.values(scope))
}
function policy(preference = true, extra: Record<string, unknown> = {}) {
  const scope: Record<string, unknown> = {
    can: (key: string) => grants.has(key), autoCompilePreference: preference,
    resolvedSession: null,
    hydrated: true, entitlementsLoaded: true, engineMode: 'source', visualEditorAllowed: grants.has('b10'), editorMode: 'source', pdfOpen: true, split: 50, mobilePane: 'editor', isDesktop: true,
    handleSplitKey: vi.fn(), setSourceSyncLine: vi.fn(), setSourceSyncRequestId: vi.fn(),
    canEditDocument: grants.has('c01'),
    handleExplainError: vi.fn(), setExplainerLine: vi.fn(), setDeepPanelOpen: vi.fn(),
    editorRef: { current: { getValue: () => 'Saved source' } },
    stagedOptimization: null, optimizeSnapshot: null, stream: { changesMade: [] },
    atsDisplay: null, categoryScores: null, deepStream: { deepAnalysis: null }, tool: 'files',
    TOOL_CAPABILITIES: { ai: 'd01', ats: 'd18', import: 'b06', templates: 'b04' }, ...extra,
  }
  for (const name of ['studioAllowed', 'contentEditAllowed', 'compileAllowed', 'studioActionAllowed', 'visualModeAvailable', 'quickAtsAdmission', 'autoCompileAllowed', 'syncAllowed', 'autoCompile', 'shouldFallbackFromDeniedVisualMode', 'toolAvailable']) {
    scope[name] = execute(initializer(name), scope)
  }
  scope.allowedTool = execute(initializer('activeTool'), scope)
  scope.explainErrorAllowed = grants.has('d13') && scope.contentEditAllowed
  scope.optimizeAllowed = grants.has('d01') && scope.contentEditAllowed && Boolean(scope.resolvedSession || scope.studioAllowed)
  scope.trimAllowed = grants.has('c12') && scope.contentEditAllowed && Boolean(scope.resolvedSession || scope.studioAllowed)
  scope.deepAnalysisAllowed = grants.has('d20') && scope.contentEditAllowed && Boolean(scope.resolvedSession || scope.studioAllowed)
  scope.atsAllowed = grants.has('d18')
  scope.hasOptimizationResult = extra.stagedOptimization != null
  scope.hasATSResult = extra.atsDisplay != null || extra.categoryScores != null
  scope.toolLabel = (id: string, label: string) => id === 'ai' && extra.stagedOptimization != null ? 'Optimization result' : label
  return scope
}
function attribute(tag: string, name: string, source = page) {
  const node = find(source, (node) => (ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(source) === tag)[0] as ts.JsxSelfClosingElement
  const property = node.attributes.properties.find((property) => ts.isJsxAttribute(property) && property.name.getText(source) === name) as ts.JsxAttribute
  return (property.initializer as ts.JsxExpression).expression!
}
function guarded(node: ts.Node) {
  for (let parent = node.parent; parent; parent = parent.parent) {
    if (ts.isJsxExpression(parent) && parent.expression && ts.isBinaryExpression(parent.expression)) return parent.expression
  }
  throw new Error('Expected a rendered conditional')
}
const buttons = find(page, (node) => ts.isJsxElement(node) && node.openingElement.tagName.getText(page) === 'button') as ts.JsxElement[]
const atsToolbarButton = buttons.find((button) => button.openingElement.attributes.getText(page).includes("onClick={() => openTool('ats')}"))!
const autoButtons = buttons.filter((node) => node.openingElement.attributes.getText(page).includes('title="Automatically update the PDF after edits"'))
const manual = buttons.find((node) => node.openingElement.attributes.getText(page).includes('aria-label="Update PDF preview"'))!
const divider = find(page, (node) => ts.isJsxSelfClosingElement(node) && node.tagName.getText(page) === 'SourcePdfDivider')[0]
const autoStatus = find(editor, (node) => ts.isJsxExpression(node) && node.expression?.getText(editor).startsWith("can('c06') && onAutoCompile &&") === true)[0] as ts.JsxExpression
const atsStatus = find(editor, (node) => ts.isJsxExpression(node) && node.expression?.getText(editor).startsWith("can('d18') && (atsScore !== undefined || atsScoreLoading)") === true)[0] as ts.JsxExpression
const icon = () => null
function render(expression: ts.Node, scope: Record<string, unknown>) {
  const result = execute(expression, {
    React, CapabilityGate, SourcePdfDivider,
    Zap: icon, Loader2: icon, Play: icon, Link2: icon, Sparkles: icon, Check: icon,
    panelHead: (label: string, action: ReactNode) => React.createElement('header', null, label, action),
    toggleAutoCompile: vi.fn(), runCompile: vi.fn(), isProcessing: false, isSubmitting: false,
    cursorLine: 4, pdfSelection: { line: 4, page: 1, x: 1, y: 1 }, pdfSyncReady: true,
    handleSourceToPdf: vi.fn(), handlePdfToSource: vi.fn(),
    jobUrl: '', setJobUrl: vi.fn(), setScrapedMeta: vi.fn(), isScraping: false, handleScrapeUrl: vi.fn(), scrapedMeta: null,
    jobDescription: '', setJobDescription: vi.fn(), handleTrimToOnePage: vi.fn(),
    showOptimizeDiff: false, setShowOptimizeDiff: vi.fn(), discardStagedOptimization: vi.fn(), applyStagedOptimization: vi.fn(), revertOptimize: vi.fn(),
    ...scope,
  }) as ReactNode
  return renderToStaticMarkup(React.createElement(React.Fragment, null, result))
}
beforeEach(() => { grants.clear() })

describe('Studio composite admission controls', () => {
  it.each(['a09', 'c06'])('hides both responsive Auto buttons, scheduler and status when %s alone is OFF', (denied) => {
    grants.add(denied === 'a09' ? 'c06' : 'a09')
    grants.add('c01'); grants.add('c05')
    const scope = policy(true)
    expect(autoButtons).toHaveLength(2)
    for (const button of autoButtons) expect(render(guarded(button), scope)).toBe('')
    expect(execute(attribute('LaTeXEditor', 'autoCompileEnabled'), scope)).toBe(false)
    const onAutoCompile = execute(attribute('LaTeXEditor', 'onAutoCompile'), { ...scope, handleAutoCompile: vi.fn() })
    expect(onAutoCompile).toBeUndefined()
    expect(render(autoStatus.expression!, { ...scope, onAutoCompile })).toBe('')
  })

  it('restores a stored Auto preference on re-enable without writing it during denial', () => {
    grants.add('a09'); grants.add('c06'); grants.add('c01'); grants.add('c05')
    const before = policy(true)
    for (const button of autoButtons) {
      const html = render(guarded(button), before)
      expect(html).toContain('aria-pressed="true"')
      expect(html).toContain('aria-label="Automatically update the PDF after edits"')
    }
    grants.delete('a09')
    expect(policy(true).autoCompile).toBe(false)
    const writePreference = vi.fn()
    const toggle = execute(initializer('toggleAutoCompile'), { useCallback: (fn: unknown) => fn, resolvedSession: null, canRef: { current: (key: string) => grants.has(key) }, toggleAutoCompilePreference: writePreference })
    toggle()
    expect(writePreference).not.toHaveBeenCalled()
    grants.add('a09')
    expect(policy(true).autoCompile).toBe(true)
    expect(policy(false).autoCompile).toBe(false)
    toggle()
    expect(writePreference).toHaveBeenCalledOnce()
  })

  it('hides the active-status badge for a saved OFF preference while keeping the toggle available', () => {
    grants.add('a09'); grants.add('c06'); grants.add('c01'); grants.add('c05')
    const scope = policy(false)
    for (const button of autoButtons) expect(render(guarded(button), scope)).toContain('aria-pressed="false"')
    const onAutoCompile = execute(attribute('LaTeXEditor', 'onAutoCompile'), { ...scope, handleAutoCompile: vi.fn() })
    expect(render(autoStatus.expression!, { ...scope, onAutoCompile })).toBe('')
  })

  it('preserves authenticated manual compile when A09 is OFF, hiding anonymous admission', () => {
    grants.add('c01'); grants.add('c05')
    const scope = policy()
    expect(render(guarded(manual), { ...scope, resolvedSession: null })).toBe('')
    const authenticated = render(guarded(manual), { ...scope, resolvedSession: { user: { id: 'owner' } }, compileAllowed: true })
    expect(authenticated).toContain('aria-label="Update PDF preview"')
    expect(authenticated).not.toContain('disabled=""')
    expect(execute(attribute('LaTeXEditor', 'onCompile'), { ...scope, resolvedSession: null })).toBeUndefined()
    const runCompile = vi.fn()
    const keyboardCompile = execute(attribute('LaTeXEditor', 'onCompile'), { ...scope, resolvedSession: { user: { id: 'owner' } }, runCompile })
    keyboardCompile()
    expect(runCompile).toHaveBeenCalledWith('compile')
  })

  it.each(['a09', 'c10'])('hides SyncTeX affordances and new data fetch when %s alone is OFF', (denied) => {
    grants.add(denied === 'a09' ? 'c10' : 'a09')
    const scope = policy()
    expect(render(guarded(divider), scope)).toBe('')
    expect(execute(attribute('LaTeXEditor', 'onSyncToPdf'), scope)).toBeUndefined()
    expect(execute(attribute('PDFPreview', 'onSyncToSource'), scope)).toBeUndefined()
    expect(execute(attribute('PDFPreview', 'jobId'), { ...scope, renderedPdfJobId: 'existing-job' })).toBeUndefined()
    expect(execute(attribute('PDFPreview', 'syncEnabled'), scope)).toBe(false)
    expect(execute(attribute('PDFPreview', 'pdfUrl'), { ...scope, pdfUrl: 'blob:existing-pdf' })).toBe('blob:existing-pdf')
    const displayedArtifact = { job_id: 'existing-job', artifact_id: 'existing-artifact' }
    expect(execute(attribute('PDFPreview', 'artifactIdentity'), { ...scope, displayedArtifact, trialStatus: { fingerprint: 'existing-fingerprint' } })).toEqual({ jobId: 'existing-job', artifactId: 'existing-artifact', fingerprint: 'existing-fingerprint' })
    const jumpToSourceLine = vi.fn()
    expect(execute(attribute('PDFPreview', 'onJumpToLine'), { ...scope, jumpToSourceLine })).toBeUndefined()
    grants.add(denied)
    const restored = policy()
    expect(render(guarded(divider), restored)).toContain('aria-label="Source and PDF synchronization"')
    expect(execute(attribute('PDFPreview', 'syncEnabled'), restored)).toBe(true)
  })

  it('keeps authenticated SyncTeX admission when anonymous Studio is OFF, while honoring independent C10 denial', () => {
    grants.add('c10')
    const resolvedSession = { user: { id: 'owner' } }
    const scope = policy(true, { resolvedSession })
    expect(render(guarded(divider), scope)).toContain('aria-label="Source and PDF synchronization"')
    expect(execute(attribute('PDFPreview', 'syncEnabled'), scope)).toBe(true)
    grants.delete('c10')
    const denied = policy(true, { resolvedSession })
    expect(render(guarded(divider), denied)).toBe('')
    expect(execute(attribute('PDFPreview', 'syncEnabled'), denied)).toBe(false)
  })

  it.each(['a09', 'c10'])('blocks a retained source Ctrl-click callback after %s revocation and restores it on regrant', (denied) => {
    grants.add('a09'); grants.add('c10')
    const setCursorLine = vi.fn(), setSourceSyncLine = vi.fn(), setSourceSyncRequestId = vi.fn()
    const onSyncToPdf = execute(attribute('LaTeXEditor', 'onSyncToPdf'), {
      ...policy(), canRef: { current: (key: string) => grants.has(key) },
      setCursorLine, setSourceSyncLine, setSourceSyncRequestId,
    }) as (line: number) => void
    grants.delete(denied)
    onSyncToPdf(4)
    for (const setter of [setCursorLine, setSourceSyncLine, setSourceSyncRequestId]) expect(setter).not.toHaveBeenCalled()
    grants.add(denied)
    onSyncToPdf(4)
    expect(setCursorLine).toHaveBeenCalledWith(4)
    expect(setSourceSyncLine).toHaveBeenCalledWith(4)
    expect(setSourceSyncRequestId).toHaveBeenCalledOnce()
  })

  it('omits Explain Error and new ATS navigation without Studio admission', () => {
    grants.add('d13'); grants.add('d18')
    const scope = policy()
    expect(execute(attribute('LaTeXEditor', 'onExplainError'), scope)).toBeUndefined()
    expect(execute(attribute('LaTeXEditor', 'onATSBadgeClick'), { ...scope, openTool: vi.fn() })).toBeUndefined()
  })

  it('omits the empty ATS status and stale loading state when Studio admission is OFF', () => {
    for (const quickATSLoading of [false, true]) {
      const scope = { ...policy(), quickATSScore: null, quickATSLoading }
      const atsScore = execute(attribute('LaTeXEditor', 'atsScore'), scope)
      const atsScoreLoading = execute(attribute('LaTeXEditor', 'atsScoreLoading'), scope)
      const onATSBadgeClick = execute(attribute('LaTeXEditor', 'onATSBadgeClick'), scope)
      expect(atsScore).toBeUndefined()
      expect(atsScoreLoading).toBeUndefined()
      expect(onATSBadgeClick).toBeUndefined()
      expect(render(atsStatus.expression!, { ...scope, ATSScoreBadge, atsScore, atsScoreLoading, onATSBadgeClick })).toBe('')
    }
  })

  it('hides empty ATS output and anonymous ATS entrypoints when Studio admission is OFF', () => {
    grants.add('d18')
    const scope = { ...policy(true, { tool: 'ats', quickATSScore: null, quickATSLoading: false }) }
    const atsScore = execute(attribute('LaTeXEditor', 'atsScore'), scope)
    const atsScoreLoading = execute(attribute('LaTeXEditor', 'atsScoreLoading'), scope)
    const onATSBadgeClick = execute(attribute('LaTeXEditor', 'onATSBadgeClick'), scope)
    expect(atsScore).toBeUndefined()
    expect(atsScoreLoading).toBeUndefined()
    expect(onATSBadgeClick).toBeUndefined()
    expect(render(atsStatus.expression!, { ...scope, ATSScoreBadge, atsScore, atsScoreLoading, onATSBadgeClick })).toBe('')
    expect(render(guarded(atsToolbarButton), scope)).toBe('')
    expect(scope.allowedTool).toBe('files')

    const returned = policy(true, { tool: 'ats', atsDisplay: 86 })
    expect(returned.allowedTool).toBe('ats')
  })

  it('keeps admitted ATS scores readable after Studio denial, including a genuine zero', () => {
    grants.add('d18')
    for (const savedScore of [0, 85]) {
      const scope = { ...policy(true, { atsDisplay: savedScore }), quickATSScore: savedScore, quickATSLoading: true, openTool: vi.fn() }
      const atsScore = execute(attribute('LaTeXEditor', 'atsScore'), scope)
      const atsScoreLoading = execute(attribute('LaTeXEditor', 'atsScoreLoading'), scope)
      const onATSBadgeClick = execute(attribute('LaTeXEditor', 'onATSBadgeClick'), scope)
      expect(atsScore).toBe(savedScore)
      expect(atsScoreLoading).toBeUndefined()
      const html = render(atsStatus.expression!, { ...scope, ATSScoreBadge, atsScore, atsScoreLoading, onATSBadgeClick })
      expect(html).toContain(`ATS ${savedScore}`)
      expect(html).not.toContain('animate-spin')
      expect(onATSBadgeClick).toBeUndefined()
    }
  })

  it('restores the enabled ATS badge handoff without replacing its live quick-score semantics', () => {
    grants.add('a09'); grants.add('d18'); grants.add('c01')
    const scope = { ...policy(true, { atsDisplay: 85 }), quickATSScore: 92, quickATSLoading: false, openTool: vi.fn() }
    const atsScore = execute(attribute('LaTeXEditor', 'atsScore'), scope)
    const atsScoreLoading = execute(attribute('LaTeXEditor', 'atsScoreLoading'), scope)
    const onATSBadgeClick = execute(attribute('LaTeXEditor', 'onATSBadgeClick'), scope)
    expect(atsScore).toBe(92)
    expect(atsScoreLoading).toBe(false)
    expect(render(atsStatus.expression!, { ...scope, ATSScoreBadge, atsScore, atsScoreLoading, onATSBadgeClick })).toContain('ATS 92')
    expect(execute(attribute('LaTeXEditor', 'atsScoreLoading'), { ...scope, quickATSLoading: true })).toBe(true)
  })

  it('waits for verified entitlements before deriving a source fallback without overwriting the preferred engine mode', () => {
    const fallback = (args: { engineMode: string; visualModeAvailable: boolean; entitlementsLoaded: boolean; hydrated: boolean }) =>
      execute(initializer('shouldFallbackFromDeniedVisualMode'), args)
    expect(fallback({ engineMode: 'pdf', visualModeAvailable: false, entitlementsLoaded: false, hydrated: true })).toBe(false)
    expect(fallback({ engineMode: 'pdf', visualModeAvailable: true, entitlementsLoaded: true, hydrated: true })).toBe(false)
    expect(fallback({ engineMode: 'pdf', visualModeAvailable: false, entitlementsLoaded: true, hydrated: true })).toBe(true)
    expect(fallback({ engineMode: 'source', visualModeAvailable: false, entitlementsLoaded: true, hydrated: true })).toBe(false)
    expect(fallback({ engineMode: 'pdf', visualModeAvailable: false, entitlementsLoaded: true, hydrated: false })).toBe(false)
    expect(execute(initializer('editorMode'), { shouldFallbackFromDeniedVisualMode: true, engineMode: 'pdf' })).toBe('source')
    expect(execute(initializer('editorMode'), { shouldFallbackFromDeniedVisualMode: false, engineMode: 'pdf' })).toBe('pdf')
  })

  it('hides both trim actions and passes composite admission to already-open dialogs', () => {
    for (const key of ['c12', 'd20']) grants.add(key)
    const trimButtons = buttons.filter((button) => button.openingElement.attributes.getText(page).includes('onClick={handleTrimToOnePage}'))
    expect(trimButtons).toHaveLength(2)
    const denied = policy()
    for (const button of trimButtons) expect(render(guarded(button), denied)).toBe('')
    expect(execute(attribute('DeepAnalysisPanel', 'allowNewActions'), denied)).toBe(false)
    grants.add('a09'); grants.add('c01')
    const allowed = policy()
    for (const button of trimButtons) expect(render(guarded(button), allowed)).toContain('<button')
    expect(execute(attribute('DeepAnalysisPanel', 'allowNewActions'), allowed)).toBe(true)
    const insert = vi.fn()
    const onInsert = execute(attribute('ImportProjectsModal', 'onInsert'), { ...allowed, canRef: { current: (key: string) => grants.has(key) }, insertProjectLatex: (_ref: unknown, _current: string, latex: string) => latex, latexContent: 'source', editorRef: { current: null }, setLatexContent: insert, setShowProjectsModal: vi.fn(), toast: { success: vi.fn() } }) as (latex: string) => void
    grants.delete('c01')
    onInsert('imported')
    expect(insert).not.toHaveBeenCalled()
    grants.delete('d20')
    expect(execute(attribute('DeepAnalysisPanel', 'allowNewActions'), policy())).toBe(false)
  })

  it('sanitizes retained deep-analysis industry overrides after independent D19 revocation', async () => {
    let industryAllowed = true
    const deepAnalyzeResume = vi.fn().mockResolvedValue({ success: true, job_id: 'admitted-job' })
    const action = execute(initializer('handleRunDeepAnalysis'), {
      canRef: { current: (key: string) => key !== 'd19' || industryAllowed }, resolvedSession: null,
      editorRef: { current: { getValue: () => 'Saved source' } }, latexContent: '', jobDescription: '',
      trialStatus: { fingerprint: 'synthetic-device' }, apiClient: { deepAnalyzeResume },
      setIsDeepAnalysisRunning: vi.fn(), setDeepAnalysisError: vi.fn(), setDeepAnalysisJobId: vi.fn(), setDeepAnalysisUsesRemaining: vi.fn(),
      toast: { error: vi.fn() },
    })
    await action('tech_saas')
    expect(deepAnalyzeResume).toHaveBeenLastCalledWith(expect.objectContaining({ industry_override: 'tech_saas' }))
    industryAllowed = false
    await action('tech_saas')
    expect(deepAnalyzeResume).toHaveBeenLastCalledWith(expect.objectContaining({ industry_override: undefined }))
  })

  it.each(['handleAutoCompile', 'handleSyncToSource', 'handleSourceToPdf', 'handlePdfToSource', 'handleExplainError', 'handleScrapeUrl', 'handleTrimToOnePage', 'handleRunDeepAnalysis'])('blocks retained %s callbacks before side effects after A09 revocation', async (name) => {
    const action = execute(initializer(name), { useCallback: (fn: unknown) => fn, canRef: { current: (key: string) => key !== 'a09' }, isDesktop: true, editorMode: 'source', jumpToSourceLine: vi.fn(), setSourceSyncLine: vi.fn(), setSourceSyncRequestId: vi.fn(), cursorLine: 4, pdfSyncReady: true, pdfSelection: { line: 4 }, handleSyncToSource: vi.fn(), isProcessing: false, isSubmitting: false, resolvedSession: null, trialStatus: {}, effectiveCanRun: true, jobUrl: 'url', isScraping: false, latexContent: 'source', jobDescription: '', TRIM_INSTRUCTION: '', trialBlocked: false, notifyTrialBlocked: vi.fn(), setExplainerLine: vi.fn() })
    await action('source')
  })
})

describe('shared deep-analysis editor caller', () => {
  it('uses current D20 for dialog admission and sanitizes retained D19 override callbacks', async () => {
    const can = (key: string) => grants.has(key)
    const admission = attribute('DeepAnalysisPanel', 'allowNewActions', editorPage)
    expect(execute(admission, { can, canEditDocument: false })).toBe(false)
    grants.add('d20')
    grants.add('c01')
    expect(execute(admission, { can, canEditDocument: true, contentEditAllowed: true, resolvedSession: null, studioAllowed: true })).toBe(true)
    const declaration = find(editorPage, (node) => ts.isVariableDeclaration(node) && node.name.getText(editorPage) === 'handleOpenDeepAnalysis')[0] as ts.VariableDeclaration
    const deepAnalyzeResume = vi.fn().mockResolvedValue({ success: true, job_id: 'admitted-job' })
    const action = execute(declaration.initializer!, {
      useCallback: (fn: unknown) => fn, canRef: { current: can },
      canEditDocument: true, offlinePdfOwnerId: 'owner', offlinePdfIdentityRef: { current: { generation: 1 } },
      isCurrentOfflinePdfIdentity: () => true, resumeId: 'resume', setDeepPanelOpen: vi.fn(),
      deepAnalysisSubmissionRef: { current: null }, deepAnalysisJobId: null,
      editorRef: { current: { getValue: () => 'Saved source' } }, latexContent: '', jobDescription: '',
      apiClient: { deepAnalyzeResume }, setIsDeepRunning: vi.fn(), setDeepAnalysisError: vi.fn(),
      setDeepAnalysisJobId: vi.fn(), setDeepAnalysisUsesRemaining: vi.fn(), toast: { error: vi.fn() },
    })
    grants.add('d19')
    await action('tech_saas')
    expect(deepAnalyzeResume).toHaveBeenLastCalledWith(expect.objectContaining({ industry_override: 'tech_saas' }))
    grants.delete('d19')
    await action('tech_saas')
    expect(deepAnalyzeResume).toHaveBeenLastCalledWith(expect.objectContaining({ industry_override: undefined }))
    grants.delete('d20')
    await action('tech_saas')
    expect(deepAnalyzeResume).toHaveBeenCalledTimes(2)
    expect(execute(admission, { can, canEditDocument: true, contentEditAllowed: true, resolvedSession: null, studioAllowed: true })).toBe(false)
  })
})

describe('Studio admitted-result recovery', () => {
  it('keeps optimization review/discard and its navigation accessible while hiding every new request', () => {
    grants.add('d03'); grants.add('c01')
    const scope = policy(true, { stagedOptimization: 'Returned AI output', tool: 'ai' })
    expect(scope.allowedTool).toBe('ai')
    expect((scope.toolLabel as (id: string, label: string) => string)('ai', 'AI Optimize')).toBe('Optimization result')
    const html = render(initializer('aiPanel'), scope)
    expect(html).toContain('AI optimization is ready')
    expect(html).toContain('Review changes')
    expect(html).toContain('Discard')
    expect(html).toContain('Apply')
    expect(html).not.toContain('Optimize for this role')
    expect(html).not.toContain('Trim to one page')
    expect(html).not.toContain('type="url"')
    grants.delete('d03')
    const restricted = render(initializer('aiPanel'), scope)
    expect(restricted).not.toContain('Review changes')
    expect(restricted).not.toContain('>Apply<')
    expect(restricted).toContain('Discard')
  })

  it('retains revert for an already-applied result and respects independent d03 denial in stale apply callbacks', () => {
    const scope = policy(true, { optimizeSnapshot: 'Original source', tool: 'ai' })
    expect(render(initializer('aiPanel'), scope)).toContain('Revert to original')
    const apply = execute(initializer('applyStagedOptimization'), { useCallback: (fn: unknown) => fn, canRef: { current: () => false }, latexContent: 'source', stagedOptimization: 'output' })
    expect(apply()).toBe(false)
  })

  it('keeps returned ATS scores readable without offering a new Deep scan', () => {
    const details = { atsDisplay: 85, categoryScores: { content: 95 }, tool: 'ats' }
    const scope: Record<string, unknown> = { ...policy(true, details), CATEGORY_LABELS: {}, isDeepAnalysisRunning: false, quickATSLoading: false, setDeepPanelOpen: vi.fn(), deepAnalysisJobId: 'admitted-job', handleRunDeepAnalysis: vi.fn() }
    expect(scope.allowedTool).toBe('ats')
    const html = render(initializer('atsPanel'), scope)
    expect(html).toContain('85')
    expect(html).toContain('95')
    expect(html).not.toContain('<button')
    const returned = render(initializer('atsPanel'), { ...scope, deepStream: { deepAnalysis: { score: 85 } } })
    expect(returned).toContain('85')
    expect(returned).not.toContain('Deep scan')
    expect(returned).not.toContain('<button')
  })

  it('keeps source/PDF/export inputs unchanged when optional admission is OFF', () => {
    const scope = policy()
    expect(execute(attribute('LaTeXEditor', 'readOnly'), { ...scope, isProcessing: false })).toBe(true)
    expect(execute(attribute('LaTeXEditor', 'value'), { ...scope, latexContent: 'Saved source' })).toBe('Saved source')
    expect(execute(attribute('PDFPreview', 'pdfUrl'), { ...scope, pdfUrl: 'blob:existing-pdf' })).toBe('blob:existing-pdf')
    expect(execute(attribute('ExportDropdown', 'latexContent'), { ...scope, editorRef: { current: null }, latexContent: 'Saved source' })).toBe('Saved source')
  })
})
