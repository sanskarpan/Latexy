import Link from 'next/link'
import { MotionItem, MotionReveal, MotionStagger } from '@/components/marketing/MotionPrimitives'

const faqs = [
  {
    q: 'How does Latexy improve ATS score?',
    a: 'Latexy analyzes job description context, maps resume content against target signals, and suggests optimized rewrite paths.',
  },
  {
    q: 'Can I use my own model provider?',
    a: 'Yes. BYOK supports provider key management so you can run optimization using your own credentials.',
  },
  {
    q: 'Is LaTeX output deterministic?',
    a: 'The platform is designed for deterministic compilation with queue-based processing and observable execution logs.',
  },
  {
    q: 'Do I need to use all features every run?',
    a: 'No. You can compile only, optimize + compile, or run ATS checks independently based on workflow stage.',
  },
]

export default function FAQPage() {
  return (
    <div className="bg-bg text-fg">
      {/* ── masthead ── */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 lg:py-24">
        <MotionReveal>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">
            Frequently asked
          </p>
          <h1 className="mt-5 max-w-[20ch] text-balance font-display text-[clamp(2.4rem,6vw,4.4rem)] font-semibold leading-[1.0] tracking-[-0.025em] text-fg">
            Clear answers for product, workflow, and reliability.
          </h1>
          <p className="mt-6 max-w-[46ch] font-body text-lg text-fg-2">
            The questions we hear most, answered plainly — no fine print, no fabricated numbers.
          </p>
        </MotionReveal>
      </section>

      {/* ── the list, set as hairline-ruled entries ── */}
      <section className="border-t border-line">
        <MotionStagger className="mx-auto max-w-6xl px-5 sm:px-8">
          {faqs.map((item) => (
            <MotionItem key={item.q}>
              <article className="border-b border-line py-8">
                <h2 className="text-balance font-display text-[clamp(1.35rem,2.4vw,1.85rem)] font-semibold leading-snug text-fg">
                  {item.q}
                </h2>
                <p className="mt-3 max-w-[62ch] font-body text-base leading-relaxed text-fg-2">
                  {item.a}
                </p>
              </article>
            </MotionItem>
          ))}
        </MotionStagger>
      </section>

      {/* ── closing prompt ── */}
      <section className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-8">
        <h2 className="text-balance font-display text-[clamp(1.8rem,4.5vw,3rem)] font-semibold leading-[1.04] tracking-[-0.02em] text-fg">
          Still have a question?
        </h2>
        <p className="mx-auto mt-5 max-w-[42ch] font-body text-fg-2">
          The fastest answer is a compile. Bring your own key or use ours — three free runs, no card.
        </p>
        <Link
          href="/try"
          className="mt-8 inline-flex items-center rounded-[var(--radius-md)] bg-accent px-8 py-3.5 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
          Open the studio →
        </Link>
      </section>
    </div>
  )
}
