import type { Metadata } from 'next'
import Link from 'next/link'
import DocumentGallery from '@/components/marketing/DocumentGallery'
import LandingExperience from '@/components/marketing/LandingExperience'
import { MarketingCTA } from '@/components/marketing/MarketingSections'
import { siteUrl } from '@/lib/site-url'
import './landing.css'

const description =
    'Build a professional resume without code. Review ATS feedback, tailor your resume to each job, track applications, and compile LaTeX documents with Latexy.'
export const metadata: Metadata = {
    title: 'Latexy | Resume Builder, ATS Feedback & LaTeX Studio',
    description,
    alternates: { canonical: '/' },
    openGraph: {
        title: 'Your next chapter, well written. | Latexy',
        description,
        url: '/',
        type: 'website',
    },
    twitter: {
        card: 'summary_large_image',
        title: 'Your next chapter, well written. | Latexy',
        description,
    },
    // Existing public Search Console ownership proof.
    verification: { google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs' },
}
const faq = [
    {
        question: 'Do I need to know LaTeX to use Latexy?',
        answer: 'No. Use familiar fields in the guided builder, or edit visually in the studio. The LaTeX source editor is available when you want detailed control.',
    },
    {
        question: 'Can I try without creating an account?',
        answer: 'Yes. Try the guest studio, edit a sample résumé, and export a PDF with limited guest usage. A saved workspace and the guided builder require an account. Feature availability depends on your plan.',
    },
    {
        question: 'Will AI change my résumé without asking?',
        answer: 'You review suggestions and choose what to accept, edit, or keep. Check that every suggestion accurately reflects your real experience.',
    },
    {
        question: 'Does an ATS score guarantee an interview?',
        answer: 'No. ATS feedback helps you examine structure, readability, and keywords. It is guidance, not a hiring decision or a guarantee of compatibility with every applicant tracking system.',
    },
    {
        question: 'Can I compile documents other than résumés?',
        answer: 'Yes. Use the LaTeX studio for papers, reports, and other LaTeX documents. Choose pdfLaTeX, XeLaTeX, or LuaLaTeX, inspect compilation logs, and preview the PDF.',
    },
]
const structuredData = {
    '@context': 'https://schema.org',
    '@graph': [
        {
            '@type': 'SoftwareApplication',
            name: 'Latexy',
            url: siteUrl(),
            applicationCategory: 'BusinessApplication',
            operatingSystem: 'Web',
            description,
        },
        {
            '@type': 'FAQPage',
            mainEntity: faq.map(item => ({
                '@type': 'Question',
                name: item.question,
                acceptedAnswer: { '@type': 'Answer', text: item.answer },
            })),
        },
    ],
}
export default function LandingPage() {
    return (
        <div className="lp-page">
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify(structuredData).replace(/</g, '\\u003c'),
                }}
            />
            <section className="lp-hero lp-container" aria-labelledby="landing-title">
                <h1 id="landing-title">
                    Your next
                    <br />
                    chapter, <em>well written.</em>
                </h1>
                <div className="lp-hero-copy">
                    <p>
                        Build a résumé without code. Refine it with useful feedback. Keep your
                        applications moving.
                    </p>
                    <div className="lp-hero-actions">
                        <MarketingCTA />
                        <Link className="lp-secondary-button" href="/templates">
                            Explore templates
                        </Link>
                    </div>
                    <p className="lp-trial-note">
                        Try the studio without an account · No card needed · Limited guest usage
                    </p>
                </div>
            </section>
            <DocumentGallery />
            <LandingExperience />
            <section className="lp-faq lp-container" aria-labelledby="landing-faq">
                <h2 id="landing-faq">Before you start</h2>
                <div>
                    {faq.map(item => (
                        <details key={item.question}>
                            <summary>{item.question}</summary>
                            <p>{item.answer}</p>
                        </details>
                    ))}
                </div>
            </section>
            <section className="lp-closing lp-container" aria-labelledby="landing-closing">
                <h2 id="landing-closing">Start with what you know.</h2>
                <p>Open a sample, make it yours, and see where it takes you.</p>
                <MarketingCTA />
            </section>
        </div>
    )
}
