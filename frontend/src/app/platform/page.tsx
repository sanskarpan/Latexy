import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight, Check, FileText, MessageSquare, Layers, Briefcase, Code2 } from 'lucide-react'
import { MarketingCTA, MarketingSectionHeading } from '@/components/marketing/MarketingSections'

export const metadata: Metadata = {
    title: 'How Latexy Works | Resumes, Cover Letters & Interview Practice',
    description:
        'Write a resume visually, review AI suggestions, tailor it to a job, and prepare your next application with cover letters, interview practice, and tracking.',
    alternates: { canonical: '/platform' },
    openGraph: {
        title: 'A calmer way to prepare your next application | Latexy',
        description: 'From your first draft to interview practice. Explore what Latexy can do.',
        url: '/platform',
        type: 'website',
    },
}
const capabilities = [
    {
        icon: FileText,
        title: 'Build a résumé that reads well',
        copy: 'Start visually, choose a professional template, and focus on your experience. Preview the PDF before you download it.',
        availability: 'Start in the guest studio',
    },
    {
        icon: Check,
        title: 'Improve it with clear feedback',
        copy: 'Check structure, readability, and keywords. Use feedback to find useful improvements instead of chasing a number.',
        availability: 'Resume checks in the studio',
    },
    {
        icon: Layers,
        title: 'Keep a version for each opportunity',
        copy: 'Save your resumes and create variations for different roles. Your original is there when you need to come back to it.',
        availability: 'In your saved workspace',
    },
    {
        icon: FileText,
        title: 'Write the letter that goes with it',
        copy: 'Create a cover letter draft from your resume and a job description. Review the details and make the introduction personal.',
        availability: 'In your saved workspace',
    },
    {
        icon: MessageSquare,
        title: 'Practise explaining your experience',
        copy: 'Prepare with text-based interview questions and feedback on your answers. Build confidence before the real conversation.',
        availability: 'In your saved workspace',
    },
    {
        icon: Briefcase,
        title: 'Keep track of where you applied',
        copy: 'Organise opportunities, application stages, and notes. See your next step without juggling another spreadsheet.',
        availability: 'In your saved workspace',
    },
]
export default function PlatformPage() {
    return (
        <div className="bg-bg text-fg">
            <section className="mx-auto grid max-w-6xl gap-12 px-5 py-16 sm:px-8 lg:grid-cols-[1.1fr_.9fr] lg:items-center lg:py-24">
                <div>
                    <p className="text-sm font-semibold text-accent-strong">How Latexy helps</p>
                    <h1 className="mt-5 font-display text-[clamp(2.5rem,5.5vw,4.5rem)] font-semibold leading-[1.04] tracking-[-.04em] text-balance">
                        A calmer way to prepare your{' '}
                        <span className="text-accent-strong">next application.</span>
                    </h1>
                    <p className="mt-6 max-w-[48ch] text-lg leading-relaxed text-fg-2">
                        Your résumé is the beginning. Bring your writing, role-specific versions,
                        cover letters, and preparation into one workspace.
                    </p>
                    <div className="mt-8">
                        <MarketingCTA />
                    </div>
                    <p className="mt-4 text-sm text-fg-3">
                        Try the studio without an account. Sign up to save your work.
                    </p>
                </div>
                <ol className="divide-y divide-line rounded-[var(--radius-lg)] border border-line bg-surface px-6 shadow-[var(--shadow-2)]">
                    {[
                        ['Your experience', 'Start with the work you’ve done.'],
                        [
                            'A specific opportunity',
                            'Focus your story on what matters for the role.',
                        ],
                        ['Your decisions', 'Review the suggestions and keep your voice.'],
                        ['Ready for the next step', 'Preview your document and prepare to apply.'],
                    ].map(([title, text], i) => (
                        <li key={title} className="flex gap-4 py-6">
                            <span className="font-ui text-sm text-accent-strong">0{i + 1}</span>
                            <div>
                                <h2 className="font-display text-xl font-semibold">{title}</h2>
                                <p className="mt-1 text-sm text-fg-2">{text}</p>
                            </div>
                        </li>
                    ))}
                </ol>
            </section>
            <section className="border-y border-line bg-surface-2">
                <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
                    <MarketingSectionHeading
                        eyebrow="A useful toolkit, one step at a time"
                        title="Choose what helps you move forward."
                        copy="Start with the résumé. Explore the rest when you need it."
                    />
                    <div className="mt-10 grid gap-x-10 gap-y-8 md:grid-cols-2">
                        {capabilities.map(item => (
                            <article key={item.title} className="border-t border-line pt-6">
                                <item.icon
                                    className="h-6 w-6 text-accent-strong"
                                    strokeWidth={1.5}
                                    aria-hidden="true"
                                />
                                <h3 className="mt-4 font-display text-2xl font-semibold tracking-tight">
                                    {item.title}
                                </h3>
                                <p className="mt-3 leading-relaxed text-fg-2">{item.copy}</p>
                                <p className="mt-4 text-sm text-fg-3">{item.availability}</p>
                            </article>
                        ))}
                    </div>
                    <p className="mt-8 text-sm text-fg-3">
                        Saved workspace features require an account. Usage and availability depend
                        on your plan. Resume scores are guidance, not interview guarantees.
                    </p>
                </div>
            </section>
            <section className="mx-auto grid max-w-6xl gap-8 px-5 py-20 sm:px-8 md:grid-cols-2">
                <div>
                    <Code2 className="h-6 w-6 text-accent-strong" aria-hidden="true" />
                    <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight">
                        Simple to start.
                        <br />
                        Room to go deeper.
                    </h2>
                    <p className="mt-5 leading-relaxed text-fg-2">
                        Work visually when you want to focus on your words. Switch to the LaTeX
                        source editor when you need detailed layout control. The technical tools are
                        there when you want them.
                    </p>
                </div>
                <div className="border-l-2 border-accent pl-6">
                    <h3 className="font-display text-xl font-semibold">
                        For people who like more control
                    </h3>
                    <p className="mt-3 leading-relaxed text-fg-2">
                        Use custom templates, connect a supported AI provider with your own key, or
                        explore the developer tools. Start with a simple document and build from
                        there.
                    </p>
                    <div className="mt-5 flex flex-wrap gap-5">
                        <Link
                            href="/templates"
                            className="inline-flex min-h-11 items-center gap-2 font-semibold text-accent-strong"
                        >
                            Explore templates
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        </Link>
                        <Link
                            href="/developer"
                            className="inline-flex min-h-11 items-center gap-2 font-semibold text-accent-strong"
                        >
                            Developer tools
                            <ArrowRight className="h-4 w-4" aria-hidden="true" />
                        </Link>
                    </div>
                </div>
            </section>
            <section className="border-t border-line">
                <div className="mx-auto max-w-6xl px-5 py-16 text-center sm:px-8">
                    <h2 className="font-display text-3xl font-semibold tracking-tight sm:text-4xl">
                        Start with one good edit.
                    </h2>
                    <p className="mt-4 text-fg-2">Open the sample and see how it feels.</p>
                    <div className="mt-7">
                        <MarketingCTA />
                    </div>
                </div>
            </section>
        </div>
    )
}
