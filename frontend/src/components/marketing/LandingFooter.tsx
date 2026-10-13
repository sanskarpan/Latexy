import Link from 'next/link'
import { BrandLogo } from '@/components/brand/BrandLogo'
import CapabilityGate from '@/components/CapabilityGate'
import { MarketingCTA } from './MarketingSections'

export default function LandingFooter({ year }: { year: number }) {
    return (
        <footer className="lp-footer">
            <div className="lp-container">
                <div className="lp-footer-row">
                    <Link href="/" aria-label="Latexy home">
                        <BrandLogo small />
                    </Link>
                    <p>Build a résumé you’re proud to share.</p>
                    <nav aria-label="Footer navigation">
                        <Link href="/platform">Product</Link>
                        <CapabilityGate feature="b04">
                            <Link href="/templates">Templates</Link>
                        </CapabilityGate>
                        <Link href="/resources">Resources</Link>
                        <Link href="/pricing">Pricing</Link>
                        <MarketingCTA />
                    </nav>
                </div>
                <div className="lp-footer-row">
                    <p>© {year} Latexy. All rights reserved.</p>
                    <nav aria-label="Legal navigation">
                        <Link href="/privacy">Privacy</Link>
                        <Link href="/terms">Terms</Link>
                        <Link href="/accessibility">Accessibility</Link>
                        <a href="mailto:support@latexy.com">Contact</a>
                    </nav>
                </div>
            </div>
        </footer>
    )
}
