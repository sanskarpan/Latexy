'use client'

import Link from 'next/link'
import Image from 'next/image'
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
                        <p className="lp-footer-eyebrow">Your next chapter starts here</p>
                        <h2 id="landing-closing">
                            Make your work
                            <br />
                            <em>worth a second look.</em>
                        </h2>
                        <p>
                            From the first draft to the next opportunity. Give your experience a
                            place to shine.
                        </p>
                        <MarketingCTA />
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
                        <Link href="/" aria-label="Latexy home">
                            <BrandLogo small />
                        </Link>
                        <p>
                            Build a résumé you’re proud to share — with precision for modern
                            applicants.
                        </p>
                    </div>
                    <nav aria-label="Footer navigation" className="lp-footer-links">
                        <div>
                            <h3>Make it yours</h3>
                            <Link href="/platform">Product</Link>
                            <CapabilityGate feature="b04">
                                <Link href="/templates">Templates</Link>
                            </CapabilityGate>
                            {billing && <Link href="/pricing">Pricing</Link>}
                        </div>
                        <div>
                            <h3>Find your way</h3>
                            <Link href="/resources">Resources</Link>
                            <Link href="/faq">Help &amp; FAQs</Link>
                            <Link href="/login">Sign in</Link>
                        </div>
                        <div>
                            <h3>Stay in touch</h3>
                            <Link href="/updates">Product updates</Link>
                            <a href="mailto:support@latexy.com">Contact us</a>
                            <a href="#landing-title">Back to top</a>
                        </div>
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
