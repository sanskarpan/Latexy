import { afterEach, describe, expect, it, vi } from 'vitest'

type VNode = { type: unknown; props: Record<string, unknown> }

function nodes(value: unknown): VNode[] {
  if (Array.isArray(value)) return value.flatMap(nodes)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as VNode
  return [node, ...nodes(node.props.children)]
}

async function renderNavigation(billing: boolean | undefined) {
  vi.resetModules()
  vi.doMock('react/jsx-runtime', () => ({
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/link', () => ({ default: 'link' }))
  vi.doMock('next/image', () => ({ default: 'image' }))
  vi.doMock('@/contexts/FeatureFlagsContext', () => ({
    useFeatureFlags: () => ({ billing }),
  }))
  vi.doMock('@/components/brand/BrandLogo', () => ({ BrandLogo: 'logo' }))
  vi.doMock('@/components/theme/ModeToggle', () => ({ default: 'mode-toggle' }))
  vi.doMock('@/components/theme/ContrastToggle', () => ({ default: 'contrast-toggle' }))
  vi.doMock('@/components/CapabilityGate', () => ({ default: 'capability-gate' }))
  vi.doMock('@/components/marketing/MarketingSections', () => ({ MarketingCTA: 'marketing-cta' }))
  vi.doMock('@/components/marketing/review-fonts', () => ({ reviewFonts: 'review-fonts' }))

  const { default: LandingHeader } = await import('@/components/marketing/LandingHeader')
  const { default: LandingFooter } = await import('@/components/marketing/LandingFooter')
  const header = LandingHeader({
    signedIn: false,
    menuOpen: false,
    menuTriggerRef: { current: null },
    menuLabel: 'Open menu',
    menuText: 'Menu',
    onMenuToggle: () => undefined,
    mobileNavigation: null,
  })
  const footer = LandingFooter({ year: 2026 })
  const hrefs = (tree: unknown) => nodes(tree)
    .filter(node => node.type === 'link')
    .map(node => node.props.href)
  return { header: hrefs(header), footer: hrefs(footer) }
}

afterEach(() => {
  for (const name of [
    'react/jsx-runtime', 'next/link', 'next/image',
    '@/contexts/FeatureFlagsContext', '@/components/brand/BrandLogo',
    '@/components/theme/ModeToggle', '@/components/theme/ContrastToggle',
    '@/components/CapabilityGate', '@/components/marketing/MarketingSections',
    '@/components/marketing/review-fonts',
  ]) vi.doUnmock(name)
  vi.resetModules()
})

describe('landing billing navigation', () => {
  it.each([false, undefined])('hides pricing until billing is explicitly enabled (%s)', async billing => {
    const { header, footer } = await renderNavigation(billing)
    expect(header).not.toContain('/pricing')
    expect(footer).not.toContain('/pricing')
    expect(header).toContain('/platform')
    expect(footer).toContain('/platform')
  })

  it('shows pricing in both navigation areas when billing is enabled', async () => {
    const { header, footer } = await renderNavigation(true)
    expect(header).toContain('/pricing')
    expect(footer).toContain('/pricing')
  })
})
