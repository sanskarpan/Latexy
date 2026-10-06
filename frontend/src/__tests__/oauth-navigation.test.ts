import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

import { safeOAuthAuthorizationUrl } from '../lib/oauth-navigation'

const GITHUB = { hostname: 'github.com', pathname: '/login/oauth/authorize' }

describe('safeOAuthAuthorizationUrl', () => {
  it('accepts the exact HTTPS provider endpoint', () => {
    expect(
      safeOAuthAuthorizationUrl('https://github.com/login/oauth/authorize?state=opaque', GITHUB),
    ).toBe('https://github.com/login/oauth/authorize?state=opaque')
  })

  it.each([
    'http://github.com/login/oauth/authorize?state=opaque',
    'https://evil.example/login/oauth/authorize?state=opaque',
    'https://user:secret@github.com/login/oauth/authorize?state=opaque',
    'https://github.com:444/login/oauth/authorize?state=opaque',
    'https://github.com/login/oauth/authorize/evil?state=opaque',
    'javascript:alert(1)',
  ])('rejects an unsafe authorization URL: %s', (value) => {
    expect(safeOAuthAuthorizationUrl(value, GITHUB)).toBeNull()
  })

  it('guards every API-provided OAuth navigation sink', () => {
    const settings = readFileSync(new URL('../app/settings/page.tsx', import.meta.url), 'utf8')
    const projectImport = readFileSync(
      new URL('../components/ImportProjectsModal.tsx', import.meta.url),
      'utf8',
    )

    expect(settings.match(/safeOAuthAuthorizationUrl\(rawAuthorizationUrl/g)).toHaveLength(5)
    expect(projectImport).toContain('safeOAuthAuthorizationUrl(rawAuthorizationUrl')
  })

  it('accepts each OAuth popup completion message only from its live popup', () => {
    const references = readFileSync(
      new URL('../components/ReferencesPanel.tsx', import.meta.url),
      'utf8',
    )

    expect(references).toContain('event.source === popup')
    expect(references.match(/oauthPopup\.current = null/g)).toHaveLength(2)
  })
})
