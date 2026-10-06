import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const SETTINGS_SOURCE = readFileSync(
  new URL('../app/settings/page.tsx', import.meta.url),
  'utf8',
)

describe('legacy OAuth callback verification', () => {
  it('reports success only after provider status verification succeeds', () => {
    expect(SETTINGS_SOURCE).toContain('setStatus(await loadStatus())')
    expect(SETTINGS_SOURCE).toContain('setSuccess(`${providerName} connected successfully!`)')
    expect(SETTINGS_SOURCE).toContain('the connection could not be verified')
    expect(SETTINGS_SOURCE).toContain('if (verified && window.opener)')
    expect(SETTINGS_SOURCE).not.toContain('getGitHubStatus().then(setGhStatus).catch(() => {})')
    expect(SETTINGS_SOURCE).not.toContain('getZoteroStatus().then(setZotStatus).catch(() => {})')
    expect(SETTINGS_SOURCE).not.toContain('getMendeleyStatus().then(setMenStatus).catch(() => {})')
    expect(SETTINGS_SOURCE).not.toContain('getDropboxStatus().then(setDbxStatus).catch(() => {})')
  })
})
