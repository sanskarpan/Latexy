import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const settingsText = readFileSync(new URL('../app/settings/page.tsx', import.meta.url), 'utf8')
const normalizedSettingsText = settingsText.replace(/\s+/g, ' ')
const settings = ts.createSourceFile('settings.tsx', settingsText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function loadVisibilityPredicate() {
  let declaration = ''
  function visit(node: ts.Node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === 'shouldShowIntegrationCard') {
      declaration = node.getText(settings)
    }
    ts.forEachChild(node, visit)
  }
  visit(settings)
  expect(declaration).toBeTruthy()
  const compiled = ts.transpileModule(declaration, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return new Function(`${compiled}\nreturn shouldShowIntegrationCard`)() as (state: {
    canConnect: boolean
    isLoading: boolean
    isConnected: boolean
    hasRecoveryState: boolean
  }) => boolean
}

describe('Settings integration card admission', () => {
  const shouldShow = loadVisibilityPredicate()

  it('hides denied disconnected cards during loading when no owner state or recovery is known', () => {
    expect(shouldShow({ canConnect: false, isLoading: true, isConnected: false, hasRecoveryState: false })).toBe(false)
  })

  it('scopes status visibility to user ID so token refresh keeps same-owner state but account changes reset it', () => {
    expect(settingsText).toContain('const statusOwnerId = sessionData.user?.id ?? null')
    expect(settingsText).toContain('integrationStatusOwnerIdRef.current !== statusOwnerId')
    expect(settingsText).toContain('integrationStatusOwnerMatches && ghStatus.connected')
    expect(settingsText).toContain('integrationStatusOwnerMatches && gdriveStatus.connected')
  })

  it.each([
    ['existing connection remains visible', { canConnect: false, isLoading: false, isConnected: true, hasRecoveryState: false }],
    ['an admitted success or error recovery remains visible', { canConnect: false, isLoading: false, isConnected: false, hasRecoveryState: true }],
    ['new connection admission remains visible', { canConnect: true, isLoading: false, isConnected: false, hasRecoveryState: false }],
  ] as const)('keeps a card visible when %s', (_label, state) => {
    expect(shouldShow(state)).toBe(true)
  })

  it.each([
    ['GitHub', 'g01', 'ghLoading', 'ghStatus.connected', "ghSuccess || ghError || ghConnecting || ghDisconnecting || (ghLoading && searchParams.get('github') === 'connected')", 'github', 'ghSuccess', 'ghError'],
    ['Zotero', 'g07', 'zotLoading', 'zotStatus.connected', "zotSuccess || zotError || zotConnecting || zotDisconnecting || (zotLoading && searchParams.get('zotero') === 'connected')", 'zotero', 'zotSuccess', 'zotError'],
    ['Mendeley', 'g08', 'menLoading', 'menStatus.connected', "menSuccess || menError || menConnecting || menDisconnecting || (menLoading && searchParams.get('mendeley') === 'connected')", 'mendeley', 'menSuccess', 'menError'],
    ['Dropbox', 'g05', 'dbxLoading', 'dbxStatus.connected', "dbxSuccess || dbxError || dbxConnecting || dbxDisconnecting || (dbxLoading && searchParams.get('dropbox') === 'connected')", 'dropbox', 'dbxSuccess', 'dbxError'],
    ['Google Drive', 'g06', 'gdriveLoading', 'gdriveStatus.connected', 'gdriveSuccess || gdriveError || gdriveConnecting || gdriveDisconnecting || gdriveRetrying', 'google_drive', 'gdriveSuccess', 'gdriveError'],
  ] as const)('wires %s card visibility to its grant, current owner, and recovery state', (_name, key, loading, connected, recovery, provider, success, error) => {
    const ownerScopedRecovery = provider === 'google_drive'
      ? `integrationStatusOwnerMatches && Boolean(${recovery})`
      : `(integrationStatusOwnerMatches && Boolean(${recovery})) || (Boolean(providerActionOwnerId) && legacyOwnedNoticeRef.current.${provider}.ownerId === providerActionOwnerId && Boolean(${success} || ${error}))`
    const wiring = `shouldShowIntegrationCard({ canConnect: integrationStatusOwnerMatches && can('${key}'), isLoading: integrationStatusOwnerMatches && ${loading}, isConnected: integrationStatusOwnerMatches && ${connected}, hasRecoveryState: ${ownerScopedRecovery}, }) &&`
    expect(normalizedSettingsText).toContain(wiring)
  })

  it('gates the replay card and rechecks its action at click time', () => {
    expect(settingsText).toContain("if (!canRef.current('a06')) return")
    expect(settingsText).toMatch(/can\('a06'\)\s*&&\s*<div[^>]*>[\s\S]*?<h2[^>]*>Getting Started<\/h2>/)
  })

  it('hides the personal dictionary panel without c16', () => {
    expect(settingsText).toMatch(/can\('c16'\)\s*&&\s*<div[^>]*>[\s\S]*?<PersonalDictionarySettings\s*\/>/)
  })
})
