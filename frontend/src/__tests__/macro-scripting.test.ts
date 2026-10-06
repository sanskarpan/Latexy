import { describe, expect, it } from 'vitest'

import { MacroPlayer } from '@/lib/macros/macro-player'
import { applyMacroScript, MacroScriptStaleDocumentError } from '@/lib/macros/macro-script-runner'
import { isSafeMacroAction, validateMacroActions } from '@/lib/macros/macro-types'
import { matchesShortcut, normalizeShortcut, shouldHandleShortcutEvent } from '@/lib/macros/macro-shortcuts'

type Position = { lineNumber: number; column: number }

function fakeEditor(initial: string, options: { executeResult?: boolean; position?: Position; onCommand?: () => Promise<void> | void } = {}) {
  let value = initial
  let version = 1
  let position = options.position ?? { lineNumber: 1, column: 1 }
  const undo: string[] = []
  const executeEditsCalls: string[] = []

  const makeModel = (modelInitial: string) => {
    let modelValue = modelInitial
    const model = {
      getValue: () => modelValue,
      getAlternativeVersionId: () => version,
      getValueLength: () => modelValue.length,
      getLineCount: () => modelValue.split('\n').length,
      getLineMaxColumn: (line: number) => (modelValue.split('\n')[line - 1] ?? '').length + 1,
      getOffsetAt: (pos: Position) => {
        const lines = modelValue.split('\n')
        return lines.slice(0, pos.lineNumber - 1).reduce((sum, line) => sum + line.length + 1, 0) + pos.column - 1
      },
      getPositionAt: (offset: number): Position => {
        const bounded = Math.max(0, Math.min(offset, modelValue.length))
        const lines = modelValue.slice(0, bounded).split('\n')
        return { lineNumber: lines.length, column: lines[lines.length - 1]!.length + 1 }
      },
      getFullModelRange: () => {
        const lines = modelValue.split('\n')
        return { startLineNumber: 1, startColumn: 1, endLineNumber: lines.length, endColumn: lines[lines.length - 1]!.length + 1 }
      },
      applyEdits: (edits: Array<{ range: { startLineNumber: number; startColumn: number; endLineNumber: number; endColumn: number }; text: string }>) => {
        for (const edit of edits) {
          const start = model.getOffsetAt({ lineNumber: edit.range.startLineNumber, column: edit.range.startColumn })
          const end = model.getOffsetAt({ lineNumber: edit.range.endLineNumber, column: edit.range.endColumn })
          modelValue = modelValue.slice(0, start) + edit.text + modelValue.slice(end)
          value = modelValue
          version += 1
        }
      },
      setValue: (next: string) => {
        modelValue = next
        value = next
        version += 1
      },
    }
    return model
  }

  const model = makeModel(initial)
  let currentModel: typeof model = model
  const editor = {
    getModel: () => currentModel,
    pushUndoStop: () => undo.push(value),
    executeEdits: (_source: string, edits: Array<{ range: any; text: string }>) => {
      executeEditsCalls.push(edits[0]!.text)
      if (options.executeResult === false) return false
      const edit = edits[0]!
      const start = currentModel.getOffsetAt({ lineNumber: edit.range.startLineNumber, column: edit.range.startColumn })
      const end = currentModel.getOffsetAt({ lineNumber: edit.range.endLineNumber, column: edit.range.endColumn })
      const current = currentModel.getValue()
      currentModel.setValue(current.slice(0, start) + edit.text + current.slice(end))
      return true
    },
    getPosition: () => position,
    setPosition: (next: Position) => { position = next },
    setSelection: () => undefined,
    getAction: () => options.onCommand ? { run: options.onCommand } : undefined,
  }
  return {
    editor,
    model,
    undo,
    executeEditsCalls,
    switchModel: (next: string) => { currentModel = makeModel(next) },
    undoOnce: () => { value = undo[0]!; model.setValue(value) },
    read: () => value,
    position: () => position,
  }
}

describe('deterministic macro execution', () => {
  it('applies one undoable edit and preserves the pre-script snapshot', async () => {
    const target = fakeEditor('old')
    await applyMacroScript(target.editor as never, async (document) => ({ document: document.replace('old', 'new'), operation_count: 1 }))
    expect(target.read()).toBe('new')
    expect(target.undo).toEqual(['old', 'new'])
    target.undoOnce()
    expect(target.read()).toBe('old')
  })

  it('does not apply a result if the document model changes in flight', async () => {
    const target = fakeEditor('old')
    await expect(applyMacroScript(target.editor as never, async () => {
      target.switchModel('a different document')
      return { document: 'unsafe overwrite', operation_count: 1 }
    })).rejects.toBeInstanceOf(MacroScriptStaleDocumentError)
    expect(target.read()).toBe('old')
    expect(target.executeEditsCalls).toHaveLength(0)
  })

  it('does not claim success when Monaco rejects the edit', async () => {
    const target = fakeEditor('old', { executeResult: false })
    await expect(applyMacroScript(target.editor as never, async () => ({ document: 'new', operation_count: 1 })))
      .rejects.toThrow('could not be applied')
    expect(target.read()).toBe('old')
  })

  it('rejects malformed or oversized server responses', async () => {
    const target = fakeEditor('old')
    await expect(applyMacroScript(target.editor as never, async () => ({ document: 'new', operation_count: 129 })))
      .rejects.toThrow('invalid result')
    await expect(applyMacroScript(target.editor as never, async () => ({ document: 'x'.repeat(500_001), operation_count: 1 })))
      .rejects.toThrow('invalid result')
  })

  it('keeps multiline inserts and replace-all playback undoable', async () => {
    const inserted = fakeEditor('a', { position: { lineNumber: 1, column: 2 } })
    await new MacroPlayer().play({ id: 'm', name: 'insert', actions: [{ type: 'insert', text: 'x\ny' }] }, inserted.editor as never)
    expect(inserted.read()).toBe('ax\ny')
    expect(inserted.position()).toEqual({ lineNumber: 2, column: 2 })

    const replaced = fakeEditor('a a')
    await new MacroPlayer().play({ id: 'm', name: 'replace', actions: [{ type: 'replace', search: 'a', replacement: 'b', all: true }] }, replaced.editor as never)
    expect(replaced.read()).toBe('b b')
    replaced.undoOnce()
    expect(replaced.read()).toBe('a a')

    const grouped = fakeEditor('')
    await new MacroPlayer().play({ id: 'm', name: 'grouped', actions: [
      { type: 'insert', text: 'a' },
      { type: 'insert', text: 'b' },
    ] }, grouped.editor as never)
    expect(grouped.read()).toBe('ab')
    grouped.undoOnce()
    expect(grouped.read()).toBe('')
  })

  it('stops recorded playback when an awaited command switches models', async () => {
    let target: ReturnType<typeof fakeEditor>
    target = fakeEditor('', { onCommand: async () => { target.switchModel('another document') } })
    await expect(new MacroPlayer().play({
      id: 'm',
      name: 'switching',
      actions: [
        { type: 'command', monacoCommand: 'editor.action.formatDocument' },
        { type: 'insert', text: 'must not cross documents' },
      ],
    }, target.editor as never)).rejects.toThrow(/document changed/i)
    expect(target.read()).toBe('')
  })

  it('rejects unsafe legacy actions and oversized action JSON before Monaco', async () => {
    expect(isSafeMacroAction({ type: 'insert', text: 'x', extra: true })).toBe(false)
    expect(isSafeMacroAction({ type: 'command', monacoCommand: 'editor.action.openSettings' })).toBe(false)
    expect(() => validateMacroActions([{ type: 'command', monacoCommand: 'editor.action.openSettings' }])).toThrow()
    expect(() => validateMacroActions(Array.from({ length: 128 }, () => ({ type: 'insert', text: 'x'.repeat(1_000) })))).toThrow(/size limit/)
    const player = new MacroPlayer()
    await expect(player.play({ id: 'm', name: 'bad', actions: [{ type: 'insert', text: 'x', extra: true } as never] }, fakeEditor('').editor as never)).rejects.toThrow('unsafe')
  })
})

describe('macro shortcut lifecycle and safety', () => {
  function event(overrides: Partial<KeyboardEvent> = {}): KeyboardEvent {
    return {
      key: 'q', code: 'KeyQ', ctrlKey: true, metaKey: false, altKey: false, shiftKey: false,
      repeat: false, isComposing: false, target: null,
      preventDefault: () => undefined, stopPropagation: () => undefined,
      ...overrides,
    } as KeyboardEvent
  }

  it('canonicalizes modifiers and rejects duplicates, malformed keys, and reserved commands', () => {
    expect(normalizeShortcut('SHIFT + CTRL + Q')).toBe('ctrl+shift+q')
    expect(normalizeShortcut('ctrl+ctrl+q')).toBeNull()
    expect(normalizeShortcut('ctrl+not-a-key')).toBeNull()
    expect(normalizeShortcut('ctrl+s')).toBeNull()
    expect(normalizeShortcut('ctrl+shift+p')).toBeNull()
  })

  it('matches both Ctrl and Cmd without firing while typing or composing', () => {
    expect(matchesShortcut(event(), 'ctrl+q')).toBe(true)
    expect(matchesShortcut(event({ ctrlKey: false, metaKey: true }), 'ctrl+q')).toBe(true)
    expect(matchesShortcut(event({ key: '@', code: 'Digit2', shiftKey: true }), 'ctrl+shift+2')).toBe(true)
    expect(matchesShortcut(event({ repeat: true }), 'ctrl+q')).toBe(false)
    expect(matchesShortcut(event({ isComposing: true }), 'ctrl+q')).toBe(false)
  })

  it('does not steal shortcuts from ordinary controls or contenteditable widgets', () => {
    expect(shouldHandleShortcutEvent(event({ target: { tagName: 'INPUT' } as unknown as EventTarget }))).toBe(false)
    expect(shouldHandleShortcutEvent(event({ target: { tagName: 'TEXTAREA', classList: { contains: () => false } } as unknown as EventTarget }))).toBe(false)
    expect(shouldHandleShortcutEvent(event({ target: { isContentEditable: true } as unknown as EventTarget }))).toBe(false)
    expect(shouldHandleShortcutEvent(event({ target: { tagName: 'TEXTAREA', classList: { contains: (name: string) => name === 'inputarea' } } as unknown as EventTarget }))).toBe(true)
  })
})
