import CapabilityGate from '@/components/CapabilityGate'

export { MarketingCTA } from './MarketingCTA'

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
