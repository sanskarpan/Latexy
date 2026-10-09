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
  it('uses valid denied maps for both Settings owner-race fixtures', () => {
    for (const fixture of [providers, preferences]) {
      expect(fixture).toMatch(/url\.pathname === '\/config\/entitlements'[\s\S]*?body: JSON\.stringify\(\{ features: \{\} \}\)/)
    }
    expect(preferences).not.toContain("['/config/feature-flags', '/config/entitlements']")
  })
  it('checks that visible new-connection controls remain disabled instead of granting OAuth access', () => {
    const lines = providers.split('\n')
    const visible = lines.filter((line) => line.includes('Connect Google Drive') && line.includes('.toBeVisible()'))
    const disabled = lines.filter((line) => line.includes('Connect Google Drive') && line.includes('.toBeDisabled()'))
    expect(visible.length).toBe(3)
    expect(disabled.length).toBe(visible.length)
    for (const line of disabled) expect(line).toContain('Unavailable')
    expect(providers).toContain("name: 'Disconnect Google Drive', exact: true")
  })
})
