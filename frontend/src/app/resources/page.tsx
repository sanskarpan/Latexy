import Link from 'next/link'

/**
 * Resources — "Typeset" re-skin. Server-rendered, token-driven, CSS-only motion.
 * Editorial list of resource entries set as an index with hairline rules and
 * mono section marks. Content, links, and CTAs preserved from the original.
 */

const reveal = 'motion-safe:animate-[fade-in-up_.7s_cubic-bezier(.2,.7,.2,1)_both]'

const resources = [
  {
    title: 'Guides',
    text: 'Role-specific resume strategy, ATS optimization heuristics, and rewrite frameworks.',
    cta: 'Read Guides',
    href: '/faq',
  },
  {
    title: 'Workflows',
    text: 'Operational checklists for weekly resume iteration and job-targeted adaptation.',
    cta: 'See Workflows',
    href: '/platform',
  },
  {
    title: 'Templates',
    text: 'LaTeX-ready templates designed for ATS readability and strong visual hierarchy.',
    cta: 'Open Studio',
    href: '/try',
  },
  {
    title: 'Best Practices',
    text: 'How to decide when to rewrite, when to trim, and how to benchmark score movement.',
    cta: 'Start Learning',
    href: '/faq',
  },
]

export default function ResourcesPage() {
  return (
    <div className="bg-bg text-fg">
      {/* ── header ── */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 lg:py-24">
        <div className={reveal}>
          <span className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">Resources</span>
          <h1 className="mt-5 max-w-[18ch] text-balance font-display text-[clamp(2.4rem,6vw,4.6rem)] font-semibold leading-[1] tracking-[-0.025em] text-fg">
            Everything needed to ship <span className="text-accent">better resumes</span>, faster.
          </h1>
          <p className="mt-6 max-w-[46ch] font-body text-lg text-fg-2">
            Practical resources focused on outcomes: stronger interviews, faster iteration, better
            scoring confidence.
          </p>
        </div>
      </section>

      {/* ── resource index ── */}
      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 sm:px-8">
          <ul className="divide-y divide-line">
            {resources.map((item) => (
              <li key={item.title}>
                <div className="grid gap-4 py-8 sm:grid-cols-[1fr_auto] sm:items-baseline sm:gap-8">
                  <div>
                    <h2 className="font-display text-[clamp(1.4rem,3vw,2rem)] font-semibold tracking-[-0.01em] text-fg">
                      {item.title}
                    </h2>
                    <p className="mt-2 max-w-[52ch] font-body text-base leading-relaxed text-fg-2">
                      {item.text}
                    </p>
                  </div>
                  <Link
                    href={item.href}
                    className="inline-flex min-h-[44px] items-center self-center font-ui text-xs font-semibold uppercase tracking-[0.14em] text-accent-strong transition duration-150 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
                  >
                    {item.cta} →
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </section>

      {/* ── closing ── */}
      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-8">
          <h2 className="mx-auto max-w-[20ch] text-balance font-display text-[clamp(1.8rem,4.5vw,3rem)] font-semibold leading-[1.04] tracking-[-0.02em] text-fg">
            Stop reading. Start <span className="text-accent">compiling.</span>
          </h2>
          <Link
            href="/try"
            className="mt-8 inline-flex items-center rounded-[var(--radius-md)] bg-accent px-8 py-3.5 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
          >
            Open the studio →
          </Link>
        </div>
      </section>
    </div>
  )
}
