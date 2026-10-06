import { describe, expect, it } from 'vitest'
import { EDITOR_KEYBINDING_MODES, parseEditorKeybindingMode } from '@/lib/editor-keybindings'

describe('editor keybinding modes', () => {
  it('keeps the three supported modes stable', () => {
    expect(EDITOR_KEYBINDING_MODES).toEqual(['standard', 'vim', 'emacs'])
  })

  it('falls back safely when persisted state is missing or invalid', () => {
    expect(parseEditorKeybindingMode(null)).toBe('standard')
    expect(parseEditorKeybindingMode('vscode')).toBe('standard')
    expect(parseEditorKeybindingMode('vim')).toBe('vim')
    expect(parseEditorKeybindingMode('emacs')).toBe('emacs')
  })
})
