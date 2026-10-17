import type { Metadata } from 'next'
import Link from 'next/link'
import { IconArrowRight as ArrowRight, IconMinus, IconPlus } from '@tabler/icons-react'
import CapabilityGate from '@/components/CapabilityGate'
import ReviewDesk from '@/components/marketing/ReviewDesk'
import ReviewJourney from '@/components/marketing/ReviewJourney'
import LandingMotion from '@/components/marketing/LandingMotion'
import { MarketingCTA } from '@/components/marketing/MarketingSections'
import { reviewFonts } from '@/components/marketing/review-fonts'
import { IconFileText, IconFolder } from '@tabler/icons-react'
import { siteUrl } from '@/lib/site-url'
import './landing-review.css'

// Public copy and samples are identical for every visitor. Prerender the
// homepage to deliver its copy and samples in the server's HTML response;
// account state and effective feature access still resolve in client gates.
export const dynamic = 'force-static'

const description =
    'Build a professional resume without code. Review ATS feedback, tailor your resume to each job, track applications, and compile LaTeX documents with Latexy.'
export const metadata: Metadata = {
    title: 'Latexy | Resume Builder, ATS Feedback & LaTeX Studio',
    description,
    alternates: { canonical: '/' },
    openGraph: {
        title: 'Latexy | Resume Builder, ATS Feedback & LaTeX Studio',
        description,
        url: '/',
        type: 'website',
    },
    twitter: {
        card: 'summary_large_image',
        title: 'Latexy | Resume Builder, ATS Feedback & LaTeX Studio',
        description,
    },
    // Existing public Search Console ownership proof.
    verification: { google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs' },
}
const faq = [
    {
        question: 'Can I use Latexy for documents other than résumés?',
        answer: 'Yes. The LaTeX studio also supports papers, reports, and other LaTeX documents. Edit the source, choose pdfLaTeX, XeLaTeX, or LuaLaTeX, and compile a PDF.',
    },
    {
        question: 'Do I need to know LaTeX to use Latexy?',
        answer: 'No. Use familiar fields in the guided builder, or edit visually in the studio. The LaTeX source editor is available when you want detailed control.',
    },
    {
        question: 'Can I try Latexy without creating an account?',
        answer: 'Yes. Try the guest studio and edit a sample résumé with limited guest usage. Professional PDF output is available in the studio. A saved workspace and the guided builder require an account. Feature availability depends on your plan.',
    },
    {
        question: 'Will AI change my résumé without asking me?',
        answer: 'You review suggestions and choose what to accept, edit, or keep. Check that every suggestion accurately reflects your real experience.',
    },
    {
        question: 'Does an ATS score guarantee an interview?',
        answer: 'No. ATS feedback helps you examine structure, readability, and keywords. It is guidance, not a hiring decision or a guarantee of compatibility with every applicant tracking system.',
    },
]
export default function LandingPage() {
    const applicationSchema = {
        '@context': 'https://schema.org',
        '@type': 'SoftwareApplication',
        name: 'Latexy',
        url: siteUrl(),
        applicationCategory: 'BusinessApplication',
        operatingSystem: 'Web',
        description,
    }
    const faqSchema = {
        '@context': 'https://schema.org',
        '@type': 'FAQPage',
        mainEntity: faq.map(item => ({
            '@type': 'Question',
            name: item.question,
            acceptedAnswer: { '@type': 'Answer', text: item.answer },
        })),
    }
    return (
        <div className={`lp-page rd-landing ${reviewFonts}`}>
            <LandingMotion />
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify(applicationSchema).replace(/</g, '\\u003c'),
                }}
            />
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify(faqSchema).replace(/</g, '\\u003c'),
                }}
            />
            <section className="rd-hero lp-container" aria-labelledby="landing-title">
                <div className="rd-hero-copy">
                    <p className="rd-eyebrow">Resume builder &amp; LaTeX studio</p>
                    <h1 id="landing-title">
                        Build a résumé.
                        <br />
                        <span>Keep it yours.</span>
                    </h1>
                    <p className="rd-hero-description">
                        Build a résumé without code. Check its structure, tailor it to the job, and
                        export a LaTeX PDF.
                    </p>
                    <div className="lp-hero-actions">
                        <MarketingCTA label="Try the studio" />
                        <Link className="lp-primary-fallback" href="/platform">
                            Explore Latexy <ArrowRight size={15} aria-hidden="true" />
                        </Link>
                        <CapabilityGate feature="b04">
                            <Link className="lp-secondary-button" href="/templates">
                                Explore templates
                                <ArrowRight size={15} aria-hidden="true" />
                            </Link>
                        </CapabilityGate>
                    </div>
                    <p className="rd-trial-note">Limited guest usage. Sign in to save your work.</p>
                </div>
                <ReviewDesk />
            </section>
            <section className="rd-overview lp-container" aria-labelledby="landing-next-steps">
                <div>
                    <p className="rd-eyebrow">Beyond the first draft</p>
                    <h2 id="landing-next-steps">
                        Keep the next{' '}
                        <br />
                        steps in view.
                    </h2>
                </div>
                <a href="#resume-feedback">
                    <IconFileText size={24} stroke={1.5} aria-hidden="true" />
                    <h3>Review your résumé</h3>
                    <p>Check its structure and role match, then decide what to improve.</p>
                    <span>
                        Explore feedback <ArrowRight size={15} aria-hidden="true" />
                    </span>
                </a>
                <a href="#applications">
                    <IconFolder size={24} stroke={1.5} aria-hidden="true" />
                    <h3>Organise your applications</h3>
                    <p>Keep versions, cover letters, and application stages together as you go.</p>
                    <span>
                        Keep track <ArrowRight size={15} aria-hidden="true" />
                    </span>
                </a>
            </section>
            <ReviewJourney />
            <section className="lp-faq lp-container" aria-labelledby="landing-faq">
                <h2 id="landing-faq">Before you start</h2>
                <div>
                    {faq.map(item => (
                        <details key={item.question}>
                            <summary>
                                {item.question}
                                <IconPlus className="lp-faq-plus" size={13} aria-hidden="true" />
                                <IconMinus className="lp-faq-minus" size={13} aria-hidden="true" />
                            </summary>
                            <p>{item.answer}</p>
                        </details>
                    ))}
                </div>
            </section>
        </div>
    )
}
