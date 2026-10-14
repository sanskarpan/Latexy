'use client'

import Link from 'next/link'
import { BrandLogo } from '@/components/brand/BrandLogo'
import ModeToggle from '@/components/theme/ModeToggle'
import ContrastToggle from '@/components/theme/ContrastToggle'
import { MarketingCTA } from './MarketingSections'
import CapabilityGate from '@/components/CapabilityGate'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import type { ReactNode, RefObject } from 'react'

export default function LandingHeader({
    signedIn,
    menuOpen,
    menuTriggerRef,
    menuLabel,
    menuText,
    onMenuToggle,
    mobileNavigation,
}: {
    signedIn: boolean
    menuOpen: boolean
    menuTriggerRef: RefObject<HTMLButtonElement>
    menuLabel: string
    menuText: string
    onMenuToggle: () => void
    mobileNavigation: ReactNode
}) {
    const { billing } = useFeatureFlags()
    return (
        <header className="lp-header">
            <Link href="/" aria-label="Latexy home">
                <BrandLogo small />
            </Link>
            <nav aria-label="Main navigation" className="lp-navigation">
                <Link href="/platform">Product</Link>
                <CapabilityGate feature="b04">
                    <Link href="/templates">Templates</Link>
                </CapabilityGate>
                <Link href="/resources">Resources</Link>
                {billing && <Link href="/pricing">Pricing</Link>}
            </nav>
            <div className="lp-header-actions">
                <ContrastToggle className="lp-header-control" />
                <ModeToggle className="lp-header-control" />
                <Link
                    className="lp-account-link lp-header-control"
                    href={signedIn ? '/dashboard' : '/login'}
                >
                    {signedIn ? 'Dashboard' : 'Sign in'}
                </Link>
                <MarketingCTA />
                <button
                    ref={menuTriggerRef}
                    type="button"
                    className="lp-menu-trigger lp-header-control"
                    aria-label={menuLabel}
                    aria-expanded={menuOpen}
                    onClick={onMenuToggle}
                >
                    {menuText}
                </button>
            </div>
            <div className="lp-mobile-navigation">{mobileNavigation}</div>
        </header>
    )
}
