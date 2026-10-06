import { afterEach, describe, expect, it, vi } from 'vitest'
import { applyLatexEditorSyncHighlight, createEditorParentValueGuard, installLatexEditorRuntimeBindings } from '@/components/LaTeXEditor'

afterEach(() => {
  vi.useRealTimers()
})

type Listener = (event: any) => void

function makeEditor() {
  const listeners = {
    mouse: [] as Listener[],
    content: [] as Listener[],
    cursor: [] as Listener[],
  }
  const model = { id: 'model-a' }
  const disposables: Array<{ dispose: () => void }> = []
  const editor = {
    getModel: () => model,
    getValue: () => 'current-source',
    onMouseDown: (listener: Listener) => {
      listeners.mouse.push(listener)
      const disposable = { dispose: () => { listeners.mouse = listeners.mouse.filter(item => item !== listener) } }
      disposables.push(disposable)
      return disposable
    },
    onDidChangeModelContent: (listener: Listener) => {
      listeners.content.push(listener)
      const disposable = { dispose: () => { listeners.content = listeners.content.filter(item => item !== listener) } }
      disposables.push(disposable)
      return disposable
    },
    onDidChangeCursorPosition: (listener: Listener) => {
      listeners.cursor.push(listener)
      const disposable = { dispose: () => { listeners.cursor = listeners.cursor.filter(item => item !== listener) } }
      disposables.push(disposable)
      return disposable
    },
  }
  return { editor, model, listeners, disposables }
}

describe('LaTeX editor runtime bindings', () => {
  it('ignores a stale controlled-parent echo until the local Monaco value is acknowledged', () => {
    const guard = createEditorParentValueGuard('A')
    guard.recordLocalValue('A-local-1')
    guard.recordLocalValue('A-local-2')

    // A delayed render can repeat the old parent value while Monaco already
    // contains the user's edit. It must not call model.setValue('A').
    expect(guard.shouldApplyParentValue('A-local-2', 'A')).toBe(false)

    // Even if an earlier local echo arrives before the newest one, it must not
    // overwrite the newer Monaco value.
    guard.observeParentValue('A-local-1')
    expect(guard.shouldApplyParentValue('A-local-2', 'A-local-1')).toBe(false)

    guard.observeParentValue('A-local-2')
    expect(guard.shouldApplyParentValue('A-local-2', 'A-local-2')).toBe(false)

    // An effect closure from the previous render must not apply its old prop
    // after a newer parent render has already been observed.
    guard.observeParentValue('newer-parent')
    expect(guard.shouldApplyParentValue('A-local-2', 'older-parent')).toBe(false)

    // A genuinely new external REST value is observed as a parent transition,
    // so it is still allowed to replace the local model before Y.js binds.
    guard.observeParentValue('REST-authoritative')
    expect(guard.shouldApplyParentValue('A-local-2', 'REST-authoritative')).toBe(true)
    guard.clear()
  })

  it('installs after mount, honors live props, repeats modifier sync, and disposes every listener', () => {
    const { editor, model, listeners } = makeEditor()
    const notifyContent = vi.fn()
    const onSyncToPdf = vi.fn()
    const onCursorChange = vi.fn()
    let readOnly = false
    let collabReadOnly = false
    const dispose = installLatexEditorRuntimeBindings({
      editor,
      mountedModel: model,
      scheduler: { notifyContent },
      getReadOnly: () => readOnly,
      getCollabReadOnly: () => collabReadOnly,
      onSyncToPdf,
      onCursorChange,
    })

    listeners.mouse.forEach(listener => listener({ event: { ctrlKey: true }, target: { position: { lineNumber: 7 } } }))
    listeners.mouse.forEach(listener => listener({ event: { metaKey: true }, target: { position: { lineNumber: 7 } } }))
    listeners.mouse.forEach(listener => listener({ event: {}, target: { position: { lineNumber: 7 } } }))
    expect(onSyncToPdf).toHaveBeenNthCalledWith(1, 7)
    expect(onSyncToPdf).toHaveBeenNthCalledWith(2, 7)
    expect(onSyncToPdf).toHaveBeenCalledTimes(2)

    listeners.content.forEach(listener => listener({ isFlush: true }))
    expect(notifyContent).not.toHaveBeenCalled()
    listeners.content.forEach(listener => listener({ isFlush: false }))
    expect(notifyContent).toHaveBeenCalledTimes(1)
    readOnly = true
    listeners.content.forEach(listener => listener({ isFlush: false }))
    collabReadOnly = true
    readOnly = false
    listeners.content.forEach(listener => listener({ isFlush: false }))
    expect(notifyContent).toHaveBeenCalledTimes(1)

    listeners.cursor.forEach(listener => listener({ position: { lineNumber: 3 } }))
    expect(onCursorChange).toHaveBeenCalledWith(3)
    dispose()
    listeners.mouse.forEach(listener => listener({ event: { ctrlKey: true }, target: { position: { lineNumber: 8 } } }))
    listeners.content.forEach(listener => listener({ isFlush: false }))
    expect(onSyncToPdf).toHaveBeenCalledTimes(2)
    expect(notifyContent).toHaveBeenCalledTimes(1)
  })

  it('rejects invalid lines and cleans a highlight when the model is replaced or unmounted', () => {
    vi.useFakeTimers()
    const modelADecorations = vi.fn()
    const modelA = { getLineCount: () => 3, deltaDecorations: modelADecorations }
    let currentModel: unknown = modelA
    const editor = {
      getModel: () => currentModel,
      revealLineInCenter: vi.fn(),
      setPosition: vi.fn(),
      deltaDecorations: vi.fn(() => ['sync-decoration']),
    }
    const monaco = {
      Range: class { constructor(..._args: unknown[]) {} },
      editor: { OverviewRulerLane: { Full: 1 } },
    }

    expect(applyLatexEditorSyncHighlight({
      editor,
      monaco,
      model: modelA,
      line: 0,
    })).toBeUndefined()
    expect(editor.revealLineInCenter).not.toHaveBeenCalled()

    const cleanup = applyLatexEditorSyncHighlight({
      editor,
      monaco,
      model: modelA,
      line: 2,
    })
    expect(editor.revealLineInCenter).toHaveBeenCalledWith(2)
    expect(editor.setPosition).toHaveBeenCalledWith({ lineNumber: 2, column: 1 })
    currentModel = { getLineCount: () => 4 }
    cleanup?.()
    vi.advanceTimersByTime(2_000)
    expect(modelADecorations).toHaveBeenCalledWith(['sync-decoration'], [])

    const modelBDecorations = vi.fn()
    const modelB = { getLineCount: () => 4, deltaDecorations: modelBDecorations }
    currentModel = modelB
    const cleanupCurrent = applyLatexEditorSyncHighlight({
      editor,
      monaco,
      model: modelB,
      line: 1,
    })
    cleanupCurrent?.()
    expect(modelBDecorations).toHaveBeenCalledWith(['sync-decoration'], [])
    expect(editor.deltaDecorations).toHaveBeenCalledTimes(2)
  })
})
