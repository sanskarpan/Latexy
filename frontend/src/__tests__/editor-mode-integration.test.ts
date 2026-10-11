import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PreviewScheduler } from '@/lib/preview-scheduler'

const pages = {
  guest: readFileSync(new URL('../app/try/page.tsx', import.meta.url), 'utf8'),
  saved: readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8'),
}

// Run the actual page callbacks. These tests cover state and admission ownership;
// the browser suites remain responsible for DOM, selection and focus behavior.
function callback(page: keyof typeof pages, name: string, context: Record<string, unknown>) {
  const ast = ts.createSourceFile('page.tsx', pages[page], ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name && node.initializer && ts.isCallExpression(node.initializer)) {
      expression = node.initializer.arguments[0].getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(expression).not.toBe('')
  const js = ts.transpileModule(`const callback = ${expression}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return runInNewContext(`${js}\ncallback`, context) as (value: string) => void
}

function modeHarness(page: keyof typeof pages, preferred = 'pdf', effective = preferred, supported = true) {
  const features = new Set(['a09', 'b10', 'c01'])
  const context = {
    canRef: { current: (key: string) => features.has(key) }, resolvedSession: null,
    preferredEditorMode: preferred, editorMode: effective, engineSupported: supported,
    latexContent: 'unsaved original source', resumeId: 'owned-document',
    editorRef: { current: { getValue: vi.fn<() => string | undefined>(() => 'latest source buffer') } },
    setLatexContent: vi.fn(), setRightTab: vi.fn(), setEditorMode: vi.fn(),
    localStorage: { setItem: vi.fn() },
  }
  return { context, deny: (key: string) => features.delete(key), toggle: callback(page, 'handleToggleEditorMode', context) }
}

afterEach(() => vi.useRealTimers())

describe('integrated editor view changes preserve work and preferences', () => {
  for (const page of ['guest', 'saved'] as const) {
    it(`${page}: switching from Resume to Source does not rewrite the document`, () => {
      const { context, toggle } = modeHarness(page)
      toggle('source')
      expect(context.setLatexContent).not.toHaveBeenCalled()
      expect(context.editorRef.current.getValue).not.toHaveBeenCalled()
      expect(context.setEditorMode).toHaveBeenCalledExactlyOnceWith('source')
      expect(context.localStorage.setItem).toHaveBeenCalledWith(page === 'guest' ? 'latexy_try_editor_mode' : 'latexy_editor_mode_owned-document', 'source')
    })

    it(`${page}: leaving Source captures the latest buffer without serializing it`, () => {
      const { context, toggle } = modeHarness(page, 'source')
      toggle('pdf')
      expect(context.setLatexContent).toHaveBeenCalledExactlyOnceWith('latest source buffer')
      expect(context.setEditorMode).toHaveBeenCalledExactlyOnceWith('pdf')
    })

    it(`${page}: a not-yet-mounted source wrapper cannot erase the draft`, () => {
      const { context, toggle } = modeHarness(page, 'source')
      context.editorRef.current.getValue.mockReturnValue(undefined)
      toggle('pdf')
      expect(context.setLatexContent).not.toHaveBeenCalled()
    })

    it(`${page}: leaving Source preserves a genuinely empty current buffer`, () => {
      const { context, toggle } = modeHarness(page, 'source')
      context.editorRef.current.getValue.mockReturnValue('')
      toggle('pdf')
      expect(context.setLatexContent).toHaveBeenCalledExactlyOnceWith('')
    })

    it.each(['b10', 'c01'])(`${page}: a retained view-change callback rejects revoked %s without rewriting source or preference`, (feature) => {
      const { context, deny, toggle } = modeHarness(page, 'source')
      deny(feature)
      toggle('pdf')
      expect(context.setLatexContent).not.toHaveBeenCalled()
      expect(context.setEditorMode).not.toHaveBeenCalled()
      expect(context.localStorage.setItem).not.toHaveBeenCalled()
    })

    it(`${page}: unsupported Resume mode never overwrites the saved preference or draft`, () => {
      const { context, toggle } = modeHarness(page, 'source', 'source', false)
      toggle('pdf')
      expect(context.setEditorMode).not.toHaveBeenCalled()
      expect(context.localStorage.setItem).not.toHaveBeenCalled()
      expect(context.setLatexContent).not.toHaveBeenCalled()
    })

    it(`${page}: an explicit Source choice while temporarily in fallback is persisted`, () => {
      const { context, toggle } = modeHarness(page, 'pdf', 'source', false)
      toggle('source')
      expect(context.setEditorMode).toHaveBeenCalledExactlyOnceWith('source')
      expect(context.localStorage.setItem).toHaveBeenCalledTimes(1)
    })
  }

  it('leaving legacy Visual preserves the controlled document, ignoring any stale source handle', () => {
    const { context, toggle } = modeHarness('saved', 'wysiwyg')
    toggle('source')
    expect(context.setLatexContent).not.toHaveBeenCalled()
    expect(context.editorRef.current.getValue).not.toHaveBeenCalled()
    expect(context.setEditorMode).toHaveBeenCalledExactlyOnceWith('source')
  })

  it('uses only one preview queue per page', () => {
    for (const source of Object.values(pages)) {
      expect(source.match(/const queuePreview = usePreviewScheduler\(/g)).toHaveLength(1)
      expect(source).not.toContain('createAutoCompileScheduler')
    }
  })

  it('replaces a queued source edit with the latest Visual edit after a mode switch', async () => {
    vi.useFakeTimers()
    const submit = vi.fn().mockResolvedValue('latest-job')
    const scheduler = new PreviewScheduler(submit, () => Date.now())
    scheduler.update(true, false)
    scheduler.request('queued source revision')
    const { context, toggle } = modeHarness('saved', 'source')
    toggle('wysiwyg')
    const changed = callback('saved', 'handleVisualChange', {
      canEditDocument: true, autoCompile: true, setLatexContent: context.setLatexContent,
      queuePreview: (source: string) => scheduler.request(source),
    })
    changed('latest Visual revision')
    await vi.advanceTimersByTimeAsync(5_000)
    expect(context.setLatexContent).toHaveBeenLastCalledWith('latest Visual revision')
    expect(submit).toHaveBeenCalledTimes(1)
    expect(submit.mock.calls[0][0]).toBe('latest Visual revision')
    scheduler.dispose()
  })

  it('keeps read-only Visual edits from mutating state or submitting a preview', () => {
    const setLatexContent = vi.fn(), queuePreview = vi.fn()
    callback('saved', 'handleVisualChange', { canEditDocument: false, autoCompile: true, setLatexContent, queuePreview })('changed')
    expect(setLatexContent).not.toHaveBeenCalled()
    expect(queuePreview).not.toHaveBeenCalled()
  })

  it('preserves Visual edits without submitting when automatic previews are off', () => {
    const setLatexContent = vi.fn(), queuePreview = vi.fn()
    callback('saved', 'handleVisualChange', { canEditDocument: true, autoCompile: false, setLatexContent, queuePreview })('changed')
    expect(setLatexContent).toHaveBeenCalledExactlyOnceWith('changed')
    expect(queuePreview).not.toHaveBeenCalled()
  })
})

describe('legacy Visual preserves side-panel actions', () => {
  const ast = ts.createSourceFile('page.tsx', pages.saved, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  function evaluate(expression: string, context: Record<string, unknown>) {
    const js = ts.transpileModule(`const result = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
    return runInNewContext(`${js}\nresult`, { ...context })
  }
  it('keeps deep-linked Comments visible and available in the More menu in legacy Visual', () => {
    const expressions: Record<string, string> = {}
    let menuFilter = ''
    function visit(node: ts.Node) {
      if (ts.isVariableDeclaration(node) && ['visualPanels', 'visibleRightTab'].includes(node.name.getText(ast))) {
        expressions[node.name.getText(ast)] = node.initializer!.getText(ast)
      }
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'filter') {
        const filter = node.arguments[0]?.getText(ast) ?? ''
        if (filter.includes('visualPanels.includes(id)') && filter.includes("id === 'comments'")) menuFilter = filter
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
    const visualPanels = evaluate(expressions.visualPanels, {})
    const context = { RIGHT_TAB_CAPABILITIES: {}, can: () => true, aiRecoveryAvailable: false, visualPanels, editorMode: 'wysiwyg', rightTab: 'comments' }
    expect(evaluate(expressions.visibleRightTab, context)).toBe('comments')
    expect(menuFilter).not.toBe('')
    expect(evaluate(menuFilter, context)({ id: 'comments' })).toBe(true)
    expect(evaluate(expressions.visibleRightTab, { ...context, rightTab: 'logs' })).toBe('preview')
  })
})


describe('engine mode capability visibility', () => {
  it.each(['b10', 'c01'])('temporarily derives Source on saved %s denial and restores the preferred view on regrant', (denied) => {
    const ast = ts.createSourceFile('editor/page.tsx', pages.saved, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    const expressions: Record<string, string> = {}
    function visit(node: ts.Node) {
      if (ts.isVariableDeclaration(node) && node.initializer && ['shouldFallbackFromDeniedVisualMode', 'editorMode'].includes(node.name.getText(ast))) {
        expressions[node.name.getText(ast)] = node.initializer.getText(ast)
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
    expect(expressions.shouldFallbackFromDeniedVisualMode).not.toBeUndefined()
    expect(expressions.editorMode).not.toBeUndefined()
    const grants = new Set(['b10', 'c01'])
    for (const preferred of ['pdf', 'wysiwyg', 'source']) {
      const effectiveMode = (entitlementsLoaded = true) => {
        const scope = { can: (key: string) => grants.has(key), entitlementsLoaded, engineMode: preferred }
        const shouldFallbackFromDeniedVisualMode = runInNewContext(expressions.shouldFallbackFromDeniedVisualMode, scope)
        return runInNewContext(expressions.editorMode, { ...scope, shouldFallbackFromDeniedVisualMode })
      }
      expect(effectiveMode()).toBe(preferred)
      grants.delete(denied)
      expect(effectiveMode(false)).toBe(preferred)
      expect(effectiveMode()).toBe('source')
      grants.add(denied)
      expect(effectiveMode()).toBe(preferred)
    }
    expect(pages.saved).not.toMatch(/setEditorMode\('source'\)/)
  })

  it.each(['b10', 'c01'])('hides the saved Resume mode control when %s is off, retaining Source', (denied) => {
    const ast = ts.createSourceFile('editor/page.tsx', pages.saved, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    let condition = ''
    let disabled = ''
    function visit(node: ts.Node) {
      if (ts.isJsxElement(node) && node.openingElement.tagName.getText(ast) === 'button'
        && node.openingElement.attributes.getText(ast).includes("onClick={() => handleToggleEditorMode('pdf')}")) {
        expect(ts.isBinaryExpression(node.parent)).toBe(true)
        condition = (node.parent as ts.BinaryExpression).left.getText(ast)
        const attribute = node.openingElement.attributes.properties.find((item) => ts.isJsxAttribute(item) && item.name.getText(ast) === 'disabled') as ts.JsxAttribute
        disabled = ((attribute.initializer as ts.JsxExpression).expression!).getText(ast)
      }
      ts.forEachChild(node, visit)
    }
    visit(ast)
    expect(condition).not.toBe('')
    const can = (key: string) => key !== denied
    expect(runInNewContext(condition, { can })).toBe(false)
    expect(runInNewContext(condition, { can: () => true })).toBe(true)
    expect(runInNewContext(disabled, { engineSupported: false })).toBe(true)
    expect(runInNewContext(disabled, { engineSupported: true })).toBe(false)
    expect(pages.saved).toContain("onClick={() => handleToggleEditorMode('source')}")
  })

  it('hides the guest Resume control on composite visual denial and keeps explicit Source recovery', () => {
    const ast = ts.createSourceFile('try/page.tsx', pages.guest, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
    let expression = ''
    function visit(node: ts.Node) {
      if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'filter'
        && node.expression.expression.getText(ast).includes("['pdf', 'source']")) expression = node.arguments[0].getText(ast)
      ts.forEachChild(node, visit)
    }
    visit(ast)
    expect(expression).not.toBe('')
    const denied = runInNewContext(expression, { visualModeAvailable: false }) as (mode: string) => boolean
    expect(['pdf', 'source'].filter(denied)).toEqual(['source'])
    const granted = runInNewContext(expression, { visualModeAvailable: true }) as (mode: string) => boolean
    expect(['pdf', 'source'].filter(granted)).toEqual(['pdf', 'source'])
  })
})
