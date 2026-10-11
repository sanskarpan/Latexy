import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowRight } from 'lucide-react'
import { MarketingCTA } from '@/components/marketing/MarketingSections'

export const metadata: Metadata = {
    title: 'Resume Writing Guide & Practical Resources | Latexy',
    description:
        'A practical guide to clearer resume bullets, tailoring to a job, and reviewing your final document. Find Latexy templates and answers before you start.',
    alternates: { canonical: '/resources' },
    openGraph: {
        title: 'Make your next resume draft easier | Latexy',
        description: 'Practical resume writing advice and clear links to the tools that help.',
        url: '/resources',
        type: 'website',
    },
}
const guides = [
    {
        id: 'stronger-bullets',
        title: 'Turn responsibilities into contributions',
        copy: 'Start with an action, explain what you worked on, and add a result you can verify. Specific work is stronger than a string of adjectives.',
        before: 'Responsible for social media.',
        after: 'Planned the weekly content calendar and coordinated product launch posts across three channels.',
        note: 'If you know the outcome, add it. If you don’t, describe the scope honestly.',
    },
    {
        id: 'tailor-to-a-job',
        title: 'Tailor the emphasis, keep the facts',
        copy: 'Read the job description for responsibilities and skills. Move your most relevant experience into view and use familiar terms when they accurately describe your work.',
        before: 'A long list of every task you have done.',
        after: 'A focused summary and a few relevant examples that show how you can contribute to this role.',
        note: 'A missing keyword is a prompt to think, not a reason to claim a skill you don’t have.',
    },
    {
        id: 'final-review',
        title: 'Read it once as a stranger',
        copy: 'Check that your role, dates, and achievements make sense without extra explanation. Preview the final PDF and check contact details, links, spacing, and page breaks.',
        before: 'Relying on a score to decide whether you are ready.',
        after: 'Using feedback alongside your own review of the actual document you will send.',
        note: 'An ATS check can reveal issues. It cannot predict the hiring decision.',
    },
]
export default function ResourcesPage() {
    return (
        <div className="bg-bg text-fg">
            <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 lg:py-24">
                <p className="text-sm font-semibold text-accent-strong">Practical resources</p>
                <h1 className="mt-5 max-w-[19ch] font-display text-[clamp(2.5rem,5.5vw,4.5rem)] font-semibold leading-[1.04] tracking-[-.04em] text-balance">
                    Make your next draft{' '}
                    <span className="text-accent-strong">a little easier.</span>
                </h1>
                <p className="mt-6 max-w-[52ch] text-lg leading-relaxed text-fg-2">
                    You don’t need to learn a new technical language to tell your story. Start with
                    these three writing habits, then put them into practice.
                </p>
                <nav aria-label="Resume guide sections" className="mt-8 flex flex-wrap gap-3">
                    {guides.map((guide, i) => (
                        <a
                            key={guide.id}
                            href={`#${guide.id}`}
                            className="inline-flex min-h-11 items-center rounded-full border border-line px-4 text-sm transition hover:border-accent hover:text-accent-strong"
                        >
                            0{i + 1} · {['Write clearly', 'Tailor honestly', 'Review carefully'][i]}
                        </a>
                    ))}
                </nav>
            </section>
            <section className="border-t border-line">
                <div className="mx-auto max-w-6xl divide-y divide-line px-5 sm:px-8">
                    {guides.map((guide, i) => (
                        <article
                            id={guide.id}
                            key={guide.id}
                            className="grid scroll-mt-24 gap-8 py-12 md:grid-cols-2"
                        >
                            <div>
                                <p className="font-ui text-sm text-accent-strong">0{i + 1}</p>
                                <h2 className="mt-3 font-display text-3xl font-semibold tracking-tight">
                                    {guide.title}
                                </h2>
                                <p className="mt-4 leading-relaxed text-fg-2">{guide.copy}</p>
                                <p className="mt-4 text-sm leading-relaxed text-fg-3">
                                    {guide.note}
                                </p>
                            </div>
                            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
                                <p className="text-sm font-semibold text-fg-3">Start here</p>
                                <p className="mt-2 leading-relaxed text-fg-2">{guide.before}</p>
                                <div className="my-5 h-px bg-line" />
                                <p className="text-sm font-semibold text-accent-strong">
                                    Try this instead
                                </p>
                                <p className="mt-2 leading-relaxed">{guide.after}</p>
                                <p className="mt-4 text-xs text-fg-3">Illustrative example</p>
                            </div>
                        </article>
                    ))}
                </div>
            </section>
            <section className="border-y border-line bg-surface-2">
                <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
                    <h2 className="font-display text-3xl font-semibold tracking-tight">
                        The right next step.
                    </h2>
                    <div className="mt-8 grid gap-6 md:grid-cols-3">
                        {[
                            {
                                title: 'Find a starting layout',
                                text: 'Browse the template gallery and choose a structure that suits your experience.',
                                href: '/templates',
                                label: 'Browse templates',
                            },
                            {
                                title: 'Understand the tools',
                                text: 'See how resume writing, review, cover letters, and preparation fit together.',
                                href: '/platform',
                                label: 'See how it works',
                            },
                            {
                                title: 'Get an answer',
                                text: 'Read the FAQ for account, trial, editing, and document questions.',
                                href: '/faq',
                                label: 'Read the FAQ',
                            },
                        ].map(item => (
                            <article key={item.title} className="border-t border-line pt-5">
                                <h3 className="font-display text-xl font-semibold">{item.title}</h3>
                                <p className="mt-3 leading-relaxed text-fg-2">{item.text}</p>
                                <Link
                                    href={item.href}
                                    className="mt-4 inline-flex min-h-11 items-center gap-2 font-semibold text-accent-strong"
                                >
                                    {item.label}
                                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                                </Link>
                            </article>
                        ))}
                    </div>
                </div>
            </section>
            <section className="mx-auto max-w-6xl px-5 py-16 text-center sm:px-8">
                <h2 className="font-display text-3xl font-semibold tracking-tight">
                    Try it on a real document.
                </h2>
                <p className="mt-4 text-fg-2">
                    Open the sample, make an edit, and preview your résumé.
                </p>
                <div className="mt-7">
                    <MarketingCTA />
                </div>
            </section>
        </div>
    )
}
