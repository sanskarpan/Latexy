'use client'

import Link from 'next/link'
import Image from 'next/image'
import { IconArrowUpRight, IconArrowRight } from '@tabler/icons-react'
import { BrandLogo } from '@/components/brand/BrandLogo'
import CapabilityGate from '@/components/CapabilityGate'
import { MarketingCTA } from './MarketingSections'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'

export default function LandingFooter({ year }: { year: number }) {
    const { billing } = useFeatureFlags()
    return (
        <footer className="lp-footer">
            <div className="lp-container">
                <section className="lp-footer-lead lp-closing" aria-labelledby="landing-closing">
                    <div className="lp-footer-message">
                        <p className="lp-footer-eyebrow">Start with what you know</p>
                        <h2 id="landing-closing">
                            You have the experience.
                            <br />
                            <em>Put it on the page.</em>
                        </h2>
                        <p>
                            Choose a layout, add your experience, and make a résumé you are ready to
                            send.
                        </p>
                        <MarketingCTA />
                        <Link className="lp-primary-fallback" href="/platform">
                            Explore Latexy <IconArrowRight size={15} aria-hidden="true" />
                        </Link>
                    </div>
                    <div className="lp-footer-art" aria-hidden="true">
                        <Image
                            src="/marketing/footer-papers.webp"
                            width={1536}
                            height={1024}
                            alt=""
                            sizes="(max-width: 700px) 100vw, 650px"
                        />
                    </div>
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
