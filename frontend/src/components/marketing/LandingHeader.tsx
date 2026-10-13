'use client'

import Link from 'next/link'
import { BrandLogo } from '@/components/brand/BrandLogo'
import ModeToggle from '@/components/theme/ModeToggle'
import ContrastToggle from '@/components/theme/ContrastToggle'
import { MarketingCTA } from './MarketingSections'
import CapabilityGate from '@/components/CapabilityGate'

export default function LandingHeader({ signedIn }: { signedIn: boolean }) {
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
                <Link href="/pricing">Pricing</Link>
            </nav>
            <div className="lp-header-actions">
                <ContrastToggle />
                <ModeToggle />
                <Link className="lp-account-link" href={signedIn ? '/dashboard' : '/login'}>
                    {signedIn ? 'Dashboard' : 'Sign in'}
                </Link>
                <MarketingCTA />
            </div>
        </header>
    )
}
