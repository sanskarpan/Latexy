import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const settings = ts.createSourceFile('settings.tsx', readFileSync(new URL('../app/settings/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const editor = ts.createSourceFile('edit.tsx', readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function action(source: ts.SourceFile, name: string, context: Record<string, unknown> = {}) {
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) expression = node.getText(source)
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name && node.initializer) expression = node.initializer.getText(source)
    ts.forEachChild(node, visit)
  }
  visit(source)
  expect(expression, name).toBeTruthy()
  const can = vi.fn(() => false)
  const scope = { can, canRef: { current: can }, ghSyncEnabled: false, dbxSyncEnabled: false, ...context }
  const js = ts.transpileModule(`const action = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return new Function(...Object.keys(scope), `${js}\nreturn action`)(...Object.values(scope)) as () => Promise<void> | void
}

describe('OAuth and sync capability controls', () => {
  it.each(['GitHub', 'Zotero', 'Mendeley', 'Dropbox', 'GoogleDrive'])('blocks connecting %s before any state/network changes', async (provider) => {
    await action(settings, `handleConnect${provider}`)()
  })
  it.each(['handleToggleGitHubSync', 'handlePushToGitHub', 'handlePullFromGitHub', 'doPullFromGitHub', 'handleToggleDropboxSync', 'handlePushToDropbox', 'handlePullFromDropbox', 'doPullFromDropbox'])('blocks %s after revocation, including already-open confirmations', async (name) => {
    await action(editor, name)()
  })
  it('does not gate provider disconnect handlers', () => {
    for (const name of ['GitHub', 'Zotero', 'Mendeley', 'Dropbox', 'GoogleDrive']) {
      let body = ''
      function visit(node: ts.Node) {
        if (ts.isFunctionDeclaration(node) && node.name?.text === `handleDisconnect${name}`) body = node.getText(settings)
        ts.forEachChild(node, visit)
      }
      visit(settings)
      expect(body).toBeTruthy()
      expect(body).not.toContain('can(')
    }
  })
  it('requires a current grant at the confirm dialog and again after an awaited source save', () => {
    const source = editor.getFullText()
    expect(source).toContain("confirmDisabled={confirmPull === 'dropbox' ? !can('g05') : !can('g01')}")
    expect(source).toContain("if (!canRef.current('g01')) return\n      const result = await apiClient.pushToGitHub")
    expect(source).toContain("if (!canRef.current('g05')) return\n      const result = await apiClient.pushToDropbox")
  })
})
