import { afterEach, describe, expect, it, vi } from 'vitest'

import { GET } from '../app/api/auth/providers/route'
import {
  getConfiguredSocialProviders,
  getSocialProviderAvailability,
} from '../lib/social-provider-config'

afterEach(() => {
  vi.unstubAllEnvs()
})

describe('runtime social provider availability', () => {
  type CredentialEnv = Partial<Record<
    'GOOGLE_CLIENT_ID' | 'GOOGLE_CLIENT_SECRET' | 'GITHUB_CLIENT_ID' | 'GITHUB_CLIENT_SECRET',
    string
  >>
  const credentialCases: Array<[CredentialEnv, { google: boolean; github: boolean }]> = [
    [{}, { google: false, github: false }],
    [{ GOOGLE_CLIENT_ID: 'google-id' }, { google: false, github: false }],
    [{ GOOGLE_CLIENT_SECRET: 'google-secret' }, { google: false, github: false }],
    [{ GOOGLE_CLIENT_ID: '  ', GOOGLE_CLIENT_SECRET: 'google-secret' }, { google: false, github: false }],
    [{ GOOGLE_CLIENT_ID: 'google-id', GOOGLE_CLIENT_SECRET: '  ' }, { google: false, github: false }],
    [
      { GOOGLE_CLIENT_ID: 'google-id', GOOGLE_CLIENT_SECRET: 'google-secret' },
      { google: true, github: false },
    ],
    [
      { GITHUB_CLIENT_ID: 'github-id', GITHUB_CLIENT_SECRET: 'github-secret' },
      { google: false, github: true },
    ],
  ]

  it.each(credentialCases)('requires both credentials for each provider: %#', (env, expected) => {
    vi.stubEnv('GOOGLE_CLIENT_ID', env.GOOGLE_CLIENT_ID ?? '')
    vi.stubEnv('GOOGLE_CLIENT_SECRET', env.GOOGLE_CLIENT_SECRET ?? '')
    vi.stubEnv('GITHUB_CLIENT_ID', env.GITHUB_CLIENT_ID ?? '')
    vi.stubEnv('GITHUB_CLIENT_SECRET', env.GITHUB_CLIENT_SECRET ?? '')

    expect(getSocialProviderAvailability()).toEqual(expected)
  })

  it('trims credentials for configuration but never exposes them in the public projection', async () => {
    vi.stubEnv('GOOGLE_CLIENT_ID', '  google-id  ')
    vi.stubEnv('GOOGLE_CLIENT_SECRET', '  google-secret  ')

    expect(getConfiguredSocialProviders()).toEqual({
      google: { clientId: 'google-id', clientSecret: 'google-secret' },
    })

    const body = await GET().json()
    expect(body).toMatchObject({ google: true, github: false })
    expect(GET().headers.get('cache-control')).toBe('no-store')
    expect(Object.keys(body).sort()).toEqual(['github', 'google', 'oidc'])
    expect(JSON.stringify(body)).not.toContain('google-id')
    expect(JSON.stringify(body)).not.toContain('google-secret')
    expect(body).not.toHaveProperty('clientId')
    expect(body).not.toHaveProperty('clientSecret')
  })

  it('keeps the endpoint fail-closed when credentials are missing or only partial', async () => {
    vi.stubEnv('GOOGLE_CLIENT_ID', 'google-id')
    vi.stubEnv('GOOGLE_CLIENT_SECRET', '')
    vi.stubEnv('GITHUB_CLIENT_ID', '')
    vi.stubEnv('GITHUB_CLIENT_SECRET', 'github-secret')

    expect(await GET().json()).toMatchObject({ google: false, github: false })
  })
})

type VNode = { type: unknown; props: Record<string, unknown> }
type FormKind = 'signin' | 'signup'

const ButtonMock = (props: Record<string, unknown>) => ({ type: 'button', props })
const InputMock = (props: Record<string, unknown>) => ({ type: 'input', props })

function textContent(node: unknown): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (!node || typeof node !== 'object') return ''
  const vnode = node as VNode
  const children = vnode.props?.children
  return Array.isArray(children)
    ? children.map(textContent).join('')
    : textContent(children)
}

function findButton(node: unknown, label: string): VNode | null {
  if (!node || typeof node !== 'object') return null
  const vnode = node as VNode
  if ((vnode.type === 'button' || vnode.type === ButtonMock) && textContent(node).includes(label)) {
    return vnode
  }
  const children = vnode.props?.children
  if (Array.isArray(children)) {
    for (const child of children) {
      const found = findButton(child, label)
      if (found) return found
    }
  } else {
    return findButton(children, label)
  }
  return null
}

type FormHarness = {
  render: () => VNode
  runEffects: () => void
  cleanup: () => void
  fetch: ReturnType<typeof vi.fn>
  social: ReturnType<typeof vi.fn>
}

async function loadFormHarness(kind: FormKind, redirect = '/workspace'): Promise<FormHarness> {
  vi.resetModules()
  let hookIndex = 0
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  let effects: Array<() => void | (() => void)> = []
  const cleanups: Array<() => void> = []
  const fetchMock = vi.fn()
  const social = vi.fn()
  const email = vi.fn()
  const passkey = vi.fn()

  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('window', { location: { href: '' } })
  vi.doMock('react', () => ({
    useEffect: (effect: () => void | (() => void)) => { effects.push(effect) },
    useRef: (initial: unknown) => {
      const index = hookIndex++
      refs[index] ??= { current: initial }
      return refs[index]
    },
    useState: (initial: unknown) => {
      const index = hookIndex++
      if (!(index in states)) {
        states[index] = typeof initial === 'function'
          ? (initial as () => unknown)()
          : initial
      }
      return [states[index], (value: unknown) => {
        states[index] = typeof value === 'function'
          ? (value as (previous: unknown) => unknown)(states[index])
          : value
      }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    Fragment: 'Fragment',
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  vi.doMock('lucide-react', () => ({ Eye: 'Eye', EyeOff: 'EyeOff' }))
  vi.doMock('@/components/ui/button', () => ({ Button: ButtonMock }))
  vi.doMock('@/components/ui/input', () => ({ Input: InputMock }))
  vi.doMock('@/components/brand/BrandLogo', () => ({ BrandLogo: 'BrandLogo' }))
  vi.doMock('@/components/I18nProvider', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
  vi.doMock('@/lib/passkey-security', () => ({ supportsPasskeys: () => false }))
  vi.doMock('@/lib/auth-client', () => ({
    authClient: {
      signIn: { social, oauth2: vi.fn(), passkey },
    },
    signIn: { email, social: vi.fn(), passkey },
    signUp: { email, social },
  }))

  const formModule = kind === 'signin'
    ? await import('../components/auth/SignInForm')
    : await import('../components/auth/SignUpForm')
  const Component = formModule.default
  const render = () => {
    hookIndex = 0
    effects = []
    return Component({ redirect }) as unknown as VNode
  }
  const runEffects = () => {
    const registered = effects
    effects = []
    for (const effect of registered) {
      const cleanup = effect()
      if (cleanup) cleanups.push(cleanup)
    }
  }

  return {
    render,
    runEffects,
    cleanup: () => { while (cleanups.length) cleanups.pop()?.() },
    fetch: fetchMock,
    social,
  }
}

async function settle() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
}

afterEach(() => {
  vi.unstubAllGlobals()
  for (const moduleName of [
    'react', 'react/jsx-runtime', 'next/link', 'lucide-react',
    '@/components/ui/button', '@/components/ui/input', '@/components/brand/BrandLogo',
    '@/components/I18nProvider', '@/lib/passkey-security', '@/lib/auth-client',
  ]) vi.doUnmock(moduleName)
  vi.resetModules()
})

describe('auth forms consume runtime provider state', () => {
  it.each([
    ['signin', ''], ['signin', 'false'], ['signup', ''], ['signup', 'false'],
  ] as const)('shows Google only after a real provider response without a build flag (%s, %s)', async (kind, flag) => {
    const harness = await loadFormHarness(kind)
    let resolveProviders!: (value: unknown) => void
    harness.fetch.mockReturnValue(new Promise((resolve) => { resolveProviders = resolve }))
    vi.stubEnv('NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED', flag)

    harness.render()
    harness.runEffects()
    expect(findButton(harness.render(), 'Google')).toBeNull()

    resolveProviders({ ok: true, json: () => Promise.resolve({ google: true, github: false }) })
    await settle()
    expect(findButton(harness.render(), 'Google')).not.toBeNull()
    expect(harness.fetch).toHaveBeenCalledWith('/api/auth/providers', expect.objectContaining({
      cache: 'no-store',
      signal: expect.any(AbortSignal),
    }))
    harness.cleanup()
  })

  it.each(['signin', 'signup'] as const)('keeps email usable for non-OK, malformed, and rejected provider responses (%s)', async (kind) => {
    for (const response of [
      { ok: false, json: () => Promise.resolve({ google: true }) },
      { ok: true, json: () => Promise.resolve({ google: 'true', github: false }) },
      { ok: true, json: () => Promise.reject(new Error('invalid JSON')) },
    ]) {
      const harness = await loadFormHarness(kind)
      vi.stubEnv('NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED', 'true')
      harness.fetch.mockResolvedValue(response)
      harness.render()
      harness.runEffects()
      await settle()

      expect(findButton(harness.render(), 'Google')).toBeNull()
      const emailButton = findButton(harness.render(), kind === 'signin' ? 'auth.signIn' : 'auth.signUp')
      expect(emailButton).not.toBeNull()
      expect(emailButton?.props.disabled).not.toBe(true)
      harness.cleanup()
      vi.resetModules()
    }

    const harness = await loadFormHarness(kind)
    vi.stubEnv('NEXT_PUBLIC_OAUTH_GOOGLE_ENABLED', 'true')
    harness.fetch.mockRejectedValue(new Error('network unavailable'))
    harness.render()
    harness.runEffects()
    await settle()
    expect(findButton(harness.render(), 'Google')).toBeNull()
    const emailButton = findButton(harness.render(), kind === 'signin' ? 'auth.signIn' : 'auth.signUp')
    expect(emailButton?.props.disabled).not.toBe(true)
    harness.cleanup()
  })

  it.each(['signin', 'signup'] as const)('ignores a late provider response after abort (%s)', async (kind) => {
    const harness = await loadFormHarness(kind)
    let resolveProviders!: (value: unknown) => void
    harness.fetch.mockReturnValue(new Promise((resolve) => { resolveProviders = resolve }))
    harness.render()
    harness.runEffects()
    harness.cleanup()
    resolveProviders({ ok: true, json: () => Promise.resolve({ google: true, github: false }) })
    await settle()
    expect(findButton(harness.render(), 'Google')).toBeNull()
  })

  it.each(['signin', 'signup'] as const)('starts Google OAuth and recovers from a failed handshake (%s)', async (kind) => {
    const harness = await loadFormHarness(kind)
    harness.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ google: true, github: false }) })
    harness.social.mockResolvedValue({ error: { message: 'provider unavailable' }, data: null })
    harness.render()
    harness.runEffects()
    await settle()

    const google = findButton(harness.render(), 'Google')
    expect(google).not.toBeNull()
    await (google?.props.onClick as () => Promise<void>)()
    const afterFailure = findButton(harness.render(), 'Google')
    expect(harness.social).toHaveBeenCalledWith({
      provider: 'google',
      callbackURL: '/workspace',
      errorCallbackURL: `/${kind === 'signin' ? 'login' : 'signup'}?redirect=%2Fworkspace`,
    })
    expect(afterFailure?.props.disabled).not.toBe(true)
    harness.cleanup()
  })

  it.each(['signin', 'signup'] as const)('passes only safe callback destinations to Google OAuth (%s)', async (kind) => {
    for (const [redirect, expected] of [
      ['/workspace/new?draft=1', '/workspace/new?draft=1'],
      ['https://evil.example/callback', '/workspace'],
    ] as const) {
      const harness = await loadFormHarness(kind, redirect)
      harness.fetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ google: true, github: false }) })
      harness.social.mockResolvedValue({ data: { url: 'https://accounts.google.com/o/oauth2/auth' } })
      harness.render()
      harness.runEffects()
      await settle()
      const google = findButton(harness.render(), 'Google')
      expect(google).not.toBeNull()
      await (google?.props.onClick as () => Promise<void>)()
      expect(harness.social).toHaveBeenCalledWith({
        provider: 'google',
        callbackURL: expected,
        errorCallbackURL: `/${kind === 'signin' ? 'login' : 'signup'}?redirect=${encodeURIComponent(expected)}`,
      })
      harness.cleanup()
    }
  })
})
