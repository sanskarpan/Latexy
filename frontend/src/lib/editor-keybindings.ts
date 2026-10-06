import type { editor } from 'monaco-editor'

export const EDITOR_KEYBINDING_MODES = ['standard', 'vim', 'emacs'] as const
export type EditorKeybindingMode = typeof EDITOR_KEYBINDING_MODES[number]

export function parseEditorKeybindingMode(value: string | null): EditorKeybindingMode {
  return EDITOR_KEYBINDING_MODES.includes(value as EditorKeybindingMode)
    ? value as EditorKeybindingMode
    : 'standard'
}

export interface EditorKeybindingAdapter {
  dispose(): void
}

const noOpAdapter: EditorKeybindingAdapter = { dispose() {} }

export async function activateEditorKeybindings(
  mode: EditorKeybindingMode,
  editorInstance: editor.IStandaloneCodeEditor,
  statusNode: HTMLElement | null,
): Promise<EditorKeybindingAdapter> {
  if (mode === 'standard') {
    if (statusNode) statusNode.textContent = 'STANDARD'
    return noOpAdapter
  }

  if (mode === 'vim') {
    const { initVimMode } = await import('monaco-vim')
    return initVimMode(editorInstance, statusNode)
  }

  const { EmacsExtension } = await import('monaco-emacs')
  const emacs = new EmacsExtension(editorInstance)
  const subscriptions = [
    emacs.onDidMarkChange((isMarked: boolean) => {
      if (statusNode) statusNode.textContent = isMarked ? 'EMACS · MARK SET' : 'EMACS'
    }),
    emacs.onDidChangeKey((key: string) => {
      if (statusNode) statusNode.textContent = key ? `EMACS · ${key}` : 'EMACS'
    }),
  ]
  emacs.start()
  if (statusNode) statusNode.textContent = 'EMACS'
  return {
    dispose() {
      subscriptions.forEach((subscription) => subscription.dispose())
      emacs.dispose()
    },
  }
}
