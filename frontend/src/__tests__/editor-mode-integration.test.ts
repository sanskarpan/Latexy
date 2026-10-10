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
  const context = {
    preferredEditorMode: preferred, editorMode: effective, engineSupported: supported,
    latexContent: 'unsaved original source', resumeId: 'owned-document',
    editorRef: { current: { getValue: vi.fn(() => 'latest source buffer') } },
    setLatexContent: vi.fn(), setRightTab: vi.fn(), setEditorMode: vi.fn(),
    localStorage: { setItem: vi.fn() },
  }
  return { context, toggle: callback(page, 'handleToggleEditorMode', context) }
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
      context.editorRef.current.getValue.mockReturnValue('')
      toggle('pdf')
      expect(context.setLatexContent).toHaveBeenCalledExactlyOnceWith('unsaved original source')
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
    const context = { visualPanels, editorMode: 'wysiwyg', rightTab: 'comments' }
    expect(evaluate(expressions.visibleRightTab, context)).toBe('comments')
    expect(menuFilter).not.toBe('')
    expect(evaluate(menuFilter, context)({ id: 'comments' })).toBe(true)
    expect(evaluate(expressions.visibleRightTab, { ...context, rightTab: 'logs' })).toBe('preview')
  })
})
