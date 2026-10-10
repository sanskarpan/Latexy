import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Check, FileText, Sparkles } from 'lucide-react'
import ResumeStory from '@/components/marketing/ResumeStory'
import { siteUrl } from '@/lib/site-url'
import {
    MarketingCTA,
    MarketingFAQ,
    MarketingSectionHeading,
} from '@/components/marketing/MarketingSections'

// Public ownership proof supplied by the approved Google Search Console setup.
// Keep this homepage-only; it is not an OAuth credential or a user permission.

export const metadata: Metadata = {
    title: 'Latexy | AI Resume Builder, Made for You',
    description:
        'Build a polished resume, tailor it to a job, and review every AI suggestion. Try Latexy without an account, with visual editing and professional PDF output.',
    alternates: { canonical: '/' },
    openGraph: {
        title: 'Your experience. A stronger resume. | Latexy',
        description:
            'Build, tailor, and review your resume in one place. You stay in control of every change.',
        url: '/',
        type: 'website',
    },
    verification: {
        google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs',
    },
}
const faq = [
    {
        question: 'Do I need to know LaTeX to use Latexy?',
        answer: 'No. Start in the visual resume editor and work with your words. The source editor is available when you want more control over a layout.',
    },
    {
        question: 'Can I try it without creating an account?',
        answer: 'Yes. The guest studio lets you explore a sample, edit it, and create a PDF without signing up. Guest usage is limited. Create an account to save resumes and continue in your workspace.',
    },
    {
        question: 'Will AI change my resume without asking?',
        answer: 'AI suggestions are presented for review. You choose which changes to accept, edit, or reject. Check every suggestion against your real experience before using it.',
    },
    {
        question: 'Does an ATS score guarantee an interview?',
        answer: 'No. Resume checks can highlight readability, structure, and keyword issues. They are useful feedback, not a hiring decision or a guarantee that every applicant tracking system will read a document identically.',
    },
]
export default function LandingPage() {
    return (
        <div className="bg-bg text-fg">
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify({
                        '@context': 'https://schema.org',
                        '@type': 'SoftwareApplication',
                        name: 'Latexy',
                        url: siteUrl(),
                        applicationCategory: 'BusinessApplication',
                        operatingSystem: 'Web',
                        description:
                            'A resume builder with visual editing, AI suggestions for review, job-specific tailoring, and PDF output.',
                    }),
                }}
            />
            <section className="mx-auto grid max-w-6xl gap-12 px-5 py-14 sm:px-8 lg:grid-cols-[.95fr_1.05fr] lg:items-center lg:py-16">
                <div className="motion-safe:animate-[fade-in-up_.6s_ease-out_both]">
                    <p className="inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1.5 text-sm text-fg-2">
                        <Sparkles className="h-4 w-4 text-accent-strong" aria-hidden="true" />
                        Your next chapter starts here
                    </p>
                    <h1 className="mt-6 font-display text-[clamp(2.75rem,5vw,3.75rem)] font-semibold leading-[1.02] tracking-[-.045em] text-balance">
                        Your experience.
                        <br />
                        <span className="text-accent-strong">A stronger résumé.</span>
                    </h1>
                    <p className="mt-6 max-w-[42ch] text-lg leading-relaxed text-fg-2">
                        Turn what you’ve done into a résumé you’re proud to send. Build visually,
                        tailor it to the job, and choose every AI suggestion.
                    </p>
                    <div className="mt-8 flex flex-wrap gap-3">
                        <MarketingCTA />
                        <Link
                            href="/templates"
                            className="inline-flex min-h-12 items-center gap-2 rounded-[var(--radius-md)] border border-line-2 px-5 font-semibold transition hover:border-accent hover:text-accent-strong"
                        >
                            Explore templates
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        </Link>
                    </div>
                    <p className="mt-4 text-sm text-fg-3">
                        Try without an account · No card needed · Limited guest usage
                    </p>
                </div>
                <ResumeStory />
            </section>
            <div className="border-y border-line bg-surface-2">
                <div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-4 px-5 py-5 text-sm text-fg-2 sm:px-8">
                    {[
                        'Visual editing, no code required',
                        'AI changes you approve',
                        'Professional PDF output',
                    ].map(text => (
                        <span key={text} className="flex items-center gap-2">
                            <Check className="h-4 w-4 text-accent-strong" aria-hidden="true" />
                            {text}
                        </span>
                    ))}
                </div>
            </div>
            <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
                <MarketingSectionHeading
                    eyebrow="From a first draft to ready to send"
                    title="A little guidance. A lot more confidence."
                    copy="Start with what you have. Improve the parts that matter. Keep your own voice."
                />
                <div className="mt-10 grid gap-8 md:grid-cols-3">
                    {[
                        {
                            icon: FileText,
                            title: 'Make it yours',
                            text: 'Explore a sample or choose a template. Edit your experience in a visual document, with a source editor available for advanced layouts.',
                        },
                        {
                            icon: Sparkles,
                            title: 'Bring the job into focus',
                            text: 'Add a job description to find relevant keywords and get suggestions for clearer, more specific writing. Use only the skills and results you can back up.',
                        },
                        {
                            icon: Check,
                            title: 'Review. Then send.',
                            text: 'Accept the changes you like, leave the rest unchanged, and preview your PDF. Check structure and readability before your next application.',
                        },
                    ].map((item, i) => (
                        <article key={item.title} className="border-t border-line pt-6">
                            <div className="flex items-center justify-between">
                                <item.icon
                                    className="h-6 w-6 text-accent-strong"
                                    strokeWidth={1.5}
                                    aria-hidden="true"
                                />
                                <span className="font-ui text-sm text-fg-3">0{i + 1}</span>
                            </div>
                            <h3 className="mt-5 font-display text-2xl font-semibold tracking-tight">
                                {item.title}
                            </h3>
                            <p className="mt-3 leading-relaxed text-fg-2">{item.text}</p>
                        </article>
                    ))}
                </div>
            </section>
            <section className="border-y border-line bg-surface">
                <div className="mx-auto grid max-w-6xl gap-10 px-5 py-16 sm:px-8 md:grid-cols-2 md:items-center">
                    <div>
                        <p className="text-sm font-semibold text-accent-strong">
                            Your story stays yours
                        </p>
                        <h2 className="mt-4 font-display text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
                            Better words.
                            <br />
                            Still your experience.
                        </h2>
                        <p className="mt-5 max-w-[44ch] leading-relaxed text-fg-2">
                            AI should help you explain your work, not invent it. Review suggestions
                            one by one and decide what belongs on the page.
                        </p>
                        <Link
                            href="/platform"
                            className="mt-6 inline-flex min-h-11 items-center gap-2 font-semibold text-accent-strong"
                        >
                            See how Latexy helps
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        </Link>
                    </div>
                    <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-6 sm:p-8">
                        <p className="text-lg leading-relaxed">
                            “I know what I did. I just need help explaining why it matters.”
                        </p>
                        <p className="mt-4 leading-relaxed text-fg-2">
                            Get help with achievement bullets, summaries, and job-specific wording.
                            See the suggestion before you make it part of your résumé.
                        </p>
                        <p className="mt-5 text-sm text-fg-3">Illustrative job seeker scenario</p>
                    </div>
                </div>
            </section>
            <section className="mx-auto max-w-6xl px-5 py-20 sm:px-8">
                <MarketingSectionHeading
                    eyebrow="Beyond the document"
                    title="Keep your next move in one place."
                    copy="Your saved workspace brings resumes, cover letters, interview practice, and application tracking together."
                />
                <div className="mt-8 grid gap-4 sm:grid-cols-2">
                    {[
                        [
                            'Resumes for different roles',
                            'Keep versions so you can adapt your story for each opportunity.',
                        ],
                        [
                            'Cover letters that connect',
                            'Create a draft from your resume and the role, then make it sound like you.',
                        ],
                        [
                            'Practice before the interview',
                            'Use text-based interview practice and feedback to prepare your answers.',
                        ],
                        [
                            'Applications you can follow',
                            'Track opportunities, stages, and notes in your workspace.',
                        ],
                    ].map(([title, text]) => (
                        <div
                            key={title}
                            className="rounded-[var(--radius-md)] border border-line p-6"
                        >
                            <h3 className="font-display text-xl font-semibold">{title}</h3>
                            <p className="mt-2 leading-relaxed text-fg-2">{text}</p>
                        </div>
                    ))}
                </div>
                <p className="mt-5 text-sm text-fg-3">
                    A saved workspace requires an account. Feature availability depends on your
                    plan.
                </p>
            </section>
            <MarketingFAQ items={faq} />
            <section className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-8">
                <h2 className="font-display text-4xl font-semibold tracking-tight sm:text-5xl">
                    Make your next application
                    <br />
                    <span className="text-accent-strong">feel like a step forward.</span>
                </h2>
                <p className="mx-auto mt-5 max-w-[45ch] leading-relaxed text-fg-2">
                    Open a sample and make your first edit. Your experience is the starting point.
                </p>
                <div className="mt-7">
                    <MarketingCTA />
                </div>
            </section>
        </div>
    )
}
