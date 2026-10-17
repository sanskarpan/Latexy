'use client'

import Link from 'next/link'
import { IconArrowUpRight, IconArrowRight } from '@tabler/icons-react'
import { BrandLogo } from '@/components/brand/BrandLogo'
import CapabilityGate from '@/components/CapabilityGate'
import { MarketingCTA } from './MarketingSections'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import { reviewFonts } from './review-fonts'

export default function LandingFooter({ year }: { year: number }) {
    const { billing } = useFeatureFlags()
    return (
        <footer className={`lp-footer ${reviewFonts}`}>
            <div className="lp-container">
                <section className="lp-footer-lead lp-closing" aria-labelledby="landing-closing">
                    <div className="lp-footer-message">
                        <p className="rd-eyebrow">Start with what you know</p>
                        <h2 id="landing-closing">
                            Put your experience
                            <br />
                            <span>on the page.</span>
                        </h2>
                        <p>
                            A first draft, a new role, or a document from scratch. Make room for the
                            work you want to do next.
                        </p>
                        <MarketingCTA label="Try the studio" />
                        <Link className="lp-primary-fallback" href="/platform">
                            Explore Latexy <IconArrowRight size={15} aria-hidden="true" />
                        </Link>
                    </div>
                    <a className="rd-footer-back" href="#landing-title" aria-label="Back to top">
                        <IconArrowUpRight size={36} stroke={1} aria-hidden="true" />
                    </a>
                </section>
                <div className="lp-footer-directory">
                    <div className="lp-footer-brand">
                        <h3>The document studio</h3>
                        <p>
                            Résumés, applications, and LaTeX documents — from a first draft to a
                            finished PDF.
                        </p>
                    </div>
                    <nav aria-label="Footer navigation" className="lp-footer-links">
                        <div>
                            <h3>Product</h3>
                            <Link href="/platform">Product</Link>
                            <CapabilityGate feature="b04">
                                <Link href="/templates">Templates</Link>
                            </CapabilityGate>
                            {billing && <Link href="/pricing">Pricing</Link>}
                        </div>
                        <div>
                            <h3>Help</h3>
                            <Link href="/resources">Resources</Link>
                            <Link href="/faq">Help &amp; FAQs</Link>
                            <Link href="/login">Sign in</Link>
                        </div>
                        <div>
                            <h3>Company</h3>
                            <Link href="/updates">Product updates</Link>
                            <a href="mailto:support@latexy.com">Contact us</a>
                            <a className="lp-footer-top-link" href="#landing-title">
                                Back to top <IconArrowUpRight size={14} aria-hidden="true" />
                            </a>
                        </div>
                    </nav>
                </div>
                <Link className="lp-footer-signature" href="/" aria-label="Latexy home">
                    <BrandLogo />
                </Link>
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
