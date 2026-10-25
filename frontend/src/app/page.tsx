import type { Metadata } from 'next'
import Link from 'next/link'
import { IconArrowRight as ArrowRight, IconMinus, IconPlus } from '@tabler/icons-react'
import ReviewDesk from '@/components/marketing/ReviewDesk'
import {
    TypesetWorkflow,
    TypesetReview,
    TypesetVersions,
    TypesetSource,
} from '@/components/marketing/TypesetStudio'
import LandingMotion from '@/components/marketing/LandingMotion'
import { MarketingCTA } from '@/components/marketing/MarketingSections'
import { reviewFonts } from '@/components/marketing/review-fonts'
import { siteUrl } from '@/lib/site-url'
import './landing-review.css'
import './landing-typeset.css'

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
        answer: 'When guest studio access is available, you can edit a sample résumé with limited usage. PDF generation depends on the features currently enabled. A saved workspace and the guided builder require an account.',
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
        <div className={`lp-page rd-landing ts-landing ${reviewFonts}`}>
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
                    <p className="rd-eyebrow">Résumés, reimagined in LaTeX</p>
                    <h1 id="landing-title">
                        A better résumé
                        <br /> is a <span>stronger you.</span>
                    </h1>
                    <p className="rd-hero-description">
                        A focused résumé and LaTeX studio. Write, review your words, tailor for each
                        opportunity, and prepare a document you’re proud to send.
                    </p>
                    <div className="lp-hero-actions">
                        <MarketingCTA label="Start your résumé" />
                        <Link className="ts-text-link" href="#resume-feedback">
                            Explore the sample <ArrowRight size={16} aria-hidden="true" />
                        </Link>
                    </div>
                    <p className="rd-trial-note">
                        A workspace for thoughtful documents. Studio access depends on availability.
                    </p>
                </div>
                <ReviewDesk />
            </section>
            <TypesetWorkflow />
            <TypesetReview />
            <TypesetVersions />
            <TypesetSource />
            <section className="lp-faq lp-container" aria-labelledby="landing-faq">
                <div>
                    <p className="rd-eyebrow">Common questions</p>
                    <h2 id="landing-faq">Before you start.</h2>
                    <p className="ts-section-description">
                        A few quick answers to help you get oriented with Latexy.
                    </p>
                </div>
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
