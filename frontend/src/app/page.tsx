import type { Metadata } from 'next'
import Link from 'next/link'
import { IconArrowRight as ArrowRight, IconMinus, IconPlus } from '@tabler/icons-react'
import CapabilityGate from '@/components/CapabilityGate'
import DocumentGallery from '@/components/marketing/DocumentGallery'
import LandingExperience from '@/components/marketing/LandingExperience'
import LandingMotion from '@/components/marketing/LandingMotion'
import { MarketingCTA } from '@/components/marketing/MarketingSections'
import { siteUrl } from '@/lib/site-url'
import './landing.css'
import './landing-type.css'
import './landing-mobile.css'
import './landing-glass.css'
import './landing-editorial.css'

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
        <div className="lp-page">
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
            <div className="lp-opening lp-container">
            <section className="lp-hero" aria-labelledby="landing-title">
                <div className="lp-hero-heading">
                    <p className="lp-hero-eyebrow"><span>Latexy / 01</span> Your work, well presented</p>
                    <h1 id="landing-title">
                        A résumé in
                        <br />
                        <span>your own words.</span>
                    </h1>
                </div>
                <div className="lp-hero-copy">
                    <p>
                        Start with guided fields or LaTeX. Review the structure, tailor a version
                        for each role, and export a PDF you can stand behind.
                    </p>
                    <div className="lp-hero-actions">
                        <MarketingCTA />
                        <Link className="lp-primary-fallback" href="/platform">
                            Explore Latexy <ArrowRight size={15} aria-hidden="true" />
                        </Link>
                        <CapabilityGate feature="b04">
                            <Link className="lp-secondary-button" href="/templates">
                                Explore templates
                                <ArrowRight size={15} aria-hidden="true" />
                            </Link>
                        </CapabilityGate>
                        <Link className="lp-secondary-button lp-secondary-fallback" href="#product">
                            See it in action <ArrowRight size={15} aria-hidden="true" />
                        </Link>
                    </div>
                    <p className="lp-trial-note">
                        Try the guest studio. No account or card needed. Usage limits apply.
                    </p>
                </div>
            </section>
            <DocumentGallery />
            </div>
            <LandingExperience />
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
