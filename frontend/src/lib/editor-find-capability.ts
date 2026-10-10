import type { editor } from 'monaco-editor'

// Monaco's command palette uses editor actions directly, so intercepting only
// Ctrl/Cmd+F and +H leaves Find with Selection / F1 Find available.
export const OPTIONAL_FIND_ACTIONS = [
  'actions.find',
  'actions.findWithSelection',
  'editor.actions.findWithArgs',
  'editor.action.nextMatchFindAction',
  'editor.action.previousMatchFindAction',
  'editor.action.goToMatchFindAction',
  'editor.action.nextSelectionMatchFindAction',
  'editor.action.previousSelectionMatchFindAction',
  'editor.action.startFindReplaceAction',
  'editor.action.replaceOne',
  'editor.action.replaceAll',
  'editor.action.selectAllMatches',
] as const

export function installFindCapabilityActions(
  instance: editor.IStandaloneCodeEditor,
  allowed: () => boolean,
) {
  const context = instance.createContextKey('latexyFindAllowed', allowed())
  const registrations = OPTIONAL_FIND_ACTIONS.flatMap((id) => {
    const original = instance.getAction(id)
    if (!original) return []
    return [instance.addAction({
      id,
      label: original.label,
      precondition: 'latexyFindAllowed',
      run: (_editor, ...args) => {
        if (allowed()) return original.run(args[0])
      },
    })]
  })
  return {
    update() { context.set(allowed()) },
    dispose() {
      registrations.forEach((registration) => registration.dispose())
      context.reset()
    },
  }
}
