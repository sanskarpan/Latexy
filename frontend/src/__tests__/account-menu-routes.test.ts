import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const HEADER = readFileSync(
  new URL('../components/GlobalHeader.tsx', import.meta.url),
  'utf8',
)

describe('account-menu route reachability', () => {
  it('routes settings to the settings page and labels BYOK separately', () => {
    expect(HEADER).toContain('href="/settings"')
    expect(HEADER).toContain('>Settings</Link>')
    expect(HEADER).toContain('href="/byok"')
    expect(HEADER).toContain('>AI Providers</Link>')
    expect(HEADER).not.toContain('href="/byok" role="menuitem" tabIndex={-1} className={menuLink} onClick={() => setIsUserMenuOpen(false)}>Settings</Link>')
  })
})
