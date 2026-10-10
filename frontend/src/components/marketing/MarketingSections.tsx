import Link from 'next/link'
import { ArrowRight } from 'lucide-react'

export function MarketingCTA({
    label = 'Build my résumé',
    href = '/try?mode=visual',
}: {
    label?: string
    href?: string
}) {
    return (
        <Link
            href={href}
            className="inline-flex min-h-12 items-center justify-center gap-3 rounded-[var(--radius-md)] bg-accent px-6 py-3 font-semibold text-accent-fg shadow-[var(--shadow-1)] transition hover:brightness-110 focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
            {label}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
        </Link>
    )
}

export function MarketingSectionHeading({
    eyebrow,
    title,
    copy,
}: {
    eyebrow: string
    title: string
    copy: string
}) {
    return (
        <div className="max-w-[650px]">
            <p className="text-sm font-semibold text-accent-strong">{eyebrow}</p>
            <h2 className="mt-3 font-display text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
                {title}
            </h2>
            <p className="mt-4 text-lg leading-relaxed text-fg-2">{copy}</p>
        </div>
    )
}

export function MarketingFAQ({ items }: { items: { question: string; answer: string }[] }) {
    return (
        <section className="border-y border-line bg-surface-2">
            <script
                type="application/ld+json"
                dangerouslySetInnerHTML={{
                    __html: JSON.stringify({
                        '@context': 'https://schema.org',
                        '@type': 'FAQPage',
                        mainEntity: items.map(item => ({
                            '@type': 'Question',
                            name: item.question,
                            acceptedAnswer: { '@type': 'Answer', text: item.answer },
                        })),
                    }).replace(/</g, '\\u003c'),
                }}
            />
            <div className="mx-auto grid max-w-6xl gap-8 px-5 py-16 sm:px-8 md:grid-cols-[.7fr_1.3fr]">
                <div>
                    <p className="text-sm font-semibold text-accent-strong">A few things to know</p>
                    <h2 className="mt-3 font-display text-3xl font-semibold tracking-tight">
                        Before you start
                    </h2>
                </div>
                <div className="divide-y divide-line">
                    {items.map(item => (
                        <details key={item.question} className="group py-5 first:pt-0">
                            <summary className="cursor-pointer text-lg font-semibold marker:text-accent-strong">
                                {item.question}
                            </summary>
                            <p className="mt-3 max-w-[62ch] leading-relaxed text-fg-2">
                                {item.answer}
                            </p>
                        </details>
                    ))}
                </div>
            </div>
        </section>
    )
}
