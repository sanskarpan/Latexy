import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (file: string) => readFileSync(new URL(`../../e2e/${file}`, import.meta.url), 'utf8')
const editor = source('editor-compile-sync.spec.ts')
const providers = source('settings-provider-action-owner-isolation.spec.ts')
const preferences = source('settings-preferences-owner-race.spec.ts')

describe('editor and Settings capability fixture contracts', () => {
  it('grants only auto-compile and SyncTeX for editor success scenarios', () => {
    const match = editor.match(/path === '\/config\/entitlements'[^\n]+features: \{([^}]+)\}/)
    expect(match).not.toBeNull()
    const grants = Object.fromEntries([...match![1].matchAll(/(\w+):\s*(true|false)/g)].map(([, key, enabled]) => [key, enabled === 'true']))
    expect(grants).toEqual({ c06: true, c10: true })
    expect(editor).toContain("unknown.push(`${route.request().method()} ${path}`)")
    expect(editor).toContain('return route.abort()')
  })
  it('denies Settings grants by default and enables Drive only for the explicit ON case', () => {
    expect(preferences).toMatch(/url\.pathname === '\/config\/entitlements'[\s\S]*?body: JSON\.stringify\(\{ features: \{\} \}\)/)
    expect(providers).toMatch(/url\.pathname === '\/config\/entitlements'[^\n]+features: \{ g06: options\.allowDrive === true \}/)
    expect(providers.match(/allowDrive: true/g)).toHaveLength(1)
    expect(preferences).not.toContain("['/config/feature-flags', '/config/entitlements']")
  })
  it('requires OFF connection controls to disappear while disconnect recovery remains', () => {
    const lines = providers.split('\n')
    const visible = lines.filter((line) => line.includes('Connect Google Drive') && line.includes('.toBeVisible()'))
    const hidden = lines.filter((line) => line.includes('Connect Google Drive') && line.includes('.toHaveCount(0)'))
    expect(visible).toHaveLength(1)
    expect(hidden.length).toBeGreaterThanOrEqual(3)
    expect(providers).toContain("name: 'Connect Google Drive', exact: true })).toBeEnabled()")
    expect(providers).not.toMatch(/Connect Google Drive[^\n]+\.toBeDisabled\(\)/)
    expect(providers).toContain("name: 'Disconnect Google Drive', exact: true")
    expect(providers).toContain("expect(fixture.disconnectOwners).toEqual(['a'])")
    expect(providers).toContain("expect(fixture.githubCompletions).toEqual(['a'])")
  })
})
