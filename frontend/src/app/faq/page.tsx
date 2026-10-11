import type { Metadata } from 'next'
import Link from 'next/link'
import { MarketingCTA } from '@/components/marketing/MarketingSections'

export const metadata: Metadata = {
    title: 'Resume Builder Questions, Answered | Latexy FAQ',
    description:
        'Find out how to start a resume without code, try Latexy as a guest, review AI suggestions, understand resume scores, and save your work.',
    alternates: { canonical: '/faq' },
    openGraph: {
        title: 'A few answers before your first edit | Latexy',
        description:
            'Clear answers about visual editing, the guest trial, AI suggestions, resume checks, and saving your work.',
        url: '/faq',
        type: 'website',
    },
}

const faqs = [
    {
        question: 'Do I need to know LaTeX or write code?',
        answer: 'No. Choose Visual mode to edit your words directly in a document. Source mode is an optional LaTeX editor for more detailed layout control. Some custom layouts may need Source mode; Latexy will tell you when visual editing is not supported.',
    },
    {
        question: 'What can I try without an account?',
        answer: 'The guest studio lets you explore a sample, edit it, and create a PDF without signing up or entering a card. Guest usage is limited. Create an account to save resumes and continue working in your workspace.',
    },
    {
        question: 'Can I start with a template?',
        answer: 'Yes. Browse the template gallery to find a layout. Templates vary in style and structure; choose one that makes your experience easy to read. Custom templates may require the source editor.',
    },
    {
        question: 'Will AI change my resume automatically?',
        answer: 'AI suggestions are presented for review. You can accept, edit, or reject them. Check the wording and facts before applying a suggestion, and include only experience, skills, and results you can honestly support.',
    },
    {
        question: 'How do I tailor my resume to a job?',
        answer: 'Add the job description in the studio to get relevant writing suggestions and keyword feedback. Focus on the experience that matters for the role while keeping your facts accurate. Tailoring changes the emphasis, not your history.',
    },
    {
        question: 'What does the resume score mean?',
        answer: 'The score combines checks such as structure, readability, text extraction, and keyword coverage. It helps you find things to improve. It does not reproduce an employer’s applicant tracking system or predict whether you will get an interview.',
    },
    {
        question: 'Can I keep different resumes for different roles?',
        answer: 'Yes. A signed-in workspace lets you save resumes and create variations. You can also work on cover letters, practise interviews through text, and track applications. Usage and feature availability depend on your plan.',
    },
    {
        question: 'Can I use my own AI provider key?',
        answer: 'Yes. Supported providers can be connected through the bring-your-own-key settings in your account. You can start with the available guest experience without setting up a provider key.',
    },
]

export default function FAQPage() {
    return (
        <div className="bg-bg text-fg">
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify({
                        '@context': 'https://schema.org',
                        '@type': 'FAQPage',
                        mainEntity: faqs.map(item => ({
                            '@type': 'Question',
                            name: item.question,
                            acceptedAnswer: { '@type': 'Answer', text: item.answer },
                        })),
                    }).replace(/</g, '\\u003c'),
                }}
            />
            <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 lg:py-20">
                <p className="text-sm font-semibold text-accent-strong">
                    Frequently asked questions
                </p>
                <h1 className="mt-5 max-w-[20ch] font-display text-[clamp(2.5rem,5vw,3.75rem)] font-semibold leading-[1.04] tracking-[-.04em] text-balance">
                    A few answers before{' '}
                    <span className="text-accent-strong">your first edit.</span>
                </h1>
                <p className="mt-6 max-w-[48ch] text-lg leading-relaxed text-fg-2">
                    What you need to get started, understand the suggestions, and keep your work
                    moving.
                </p>
            </section>
            <section className="border-y border-line bg-surface">
                <div className="mx-auto max-w-6xl divide-y divide-line px-5 sm:px-8">
                    {faqs.map(item => (
                        <article
                            key={item.question}
                            className="grid gap-4 py-8 md:grid-cols-[.9fr_1.1fr] md:gap-12"
                        >
                            <h2 className="font-display text-2xl font-semibold leading-snug tracking-tight">
                                {item.question}
                            </h2>
                            <p className="max-w-[62ch] leading-relaxed text-fg-2">{item.answer}</p>
                        </article>
                    ))}
                </div>
            </section>
            <section className="mx-auto max-w-6xl px-5 py-16 text-center sm:px-8">
                <h2 className="font-display text-3xl font-semibold tracking-tight">
                    See how it feels.
                </h2>
                <p className="mx-auto mt-4 max-w-[45ch] leading-relaxed text-fg-2">
                    Open the sample and make one edit. For writing advice, visit our{' '}
                    <Link
                        href="/resources"
                        className="text-accent-strong underline underline-offset-4"
                    >
                        practical resources
                    </Link>
                    .
                </p>
                <div className="mt-7">
                    <MarketingCTA />
                </div>
                <p className="mt-5 text-sm text-fg-3">
                    Still need help?{' '}
                    <a
                        href="mailto:support@latexy.com"
                        className="text-accent-strong underline underline-offset-4"
                    >
                        Contact support
                    </a>
                    .
                </p>
            </section>
        </div>
    )
}
