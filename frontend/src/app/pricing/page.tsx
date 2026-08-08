import Link from 'next/link'
import { Check } from 'lucide-react'

/**
 * Public pricing page — Typeset marketing (redesign, PRD 2026-08-03).
 * Was a re-export of the authenticated /billing screen; now a standalone
 * marketing surface. Live prices + checkout stay on /billing (API-driven), so
 * this page sells the tiers by value and links there for current numbers.
 */

export const metadata = {
  title: 'Pricing | Latexy',
  description: 'Start free, then pick the plan that fits — or bring your own key.',
}

type Tier = {
  id: string
  name: string
  tagline: string
  features: string[]
  cta: { label: string; href: string }
  featured?: boolean
}

const tiers: Tier[] = [
  {
    id: 'free',
    name: 'Free',
    tagline: 'Try it on a real résumé.',
    features: ['3 free compiles', 'Per-change accept / reject review', 'ATS score & recommendations', 'Import from GitHub, a URL, or LinkedIn'],
    cta: { label: 'Start free →', href: '/try' },
  },
  {
    id: 'basic',
    name: 'Basic',
    tagline: 'For an active job search.',
    features: ['Everything in Free', 'More monthly compiles & optimizations', 'Cover letters', 'Version history & variants'],
    cta: { label: 'Choose Basic', href: '/billing' },
  },
  {
    id: 'pro',
    name: 'Pro',
    tagline: 'The full toolchain.',
    features: ['Everything in Basic', 'Higher limits & priority compiles', 'All AI tools (steer, batch-tailor, interview prep)', 'Deep ATS analysis'],
    cta: { label: 'Go Pro', href: '/billing' },
    featured: true,
  },
  {
    id: 'byok',
    name: 'BYOK',
    tagline: 'Your key, your models.',
    features: ['Bring your own OpenAI / Anthropic / Gemini key', 'Use the models you choose', 'Your usage billed to you', 'All Pro features'],
    cta: { label: 'Use your key', href: '/billing' },
  },
]

export default function PricingPage() {
  return (
    <div className="bg-bg text-fg">
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <h1 className="max-w-[18ch] font-display text-[clamp(2.2rem,5.5vw,3.8rem)] font-semibold leading-[1.02] tracking-[-0.025em] text-fg text-balance">
          Start free. Pay only when it&apos;s working for you.
        </h1>
        <p className="mt-5 max-w-[50ch] font-body text-lg text-fg-2">
          Three free compiles, no card. Upgrade for higher limits and the full AI toolchain, or bring your own key.
          Current prices and checkout live on your <Link href="/billing" className="text-accent-strong underline-offset-4 hover:underline">billing page</Link>.
        </p>

        <div className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-line bg-line md:grid-cols-2 lg:grid-cols-4">
          {tiers.map((t) => (
            <div
              key={t.id}
              className={`flex flex-col bg-surface p-6 ${t.featured ? 'ring-1 ring-inset ring-accent' : ''}`}
            >
              <div className="flex items-baseline justify-between">
                <h2 className="font-display text-xl font-semibold text-fg">{t.name}</h2>
                {t.featured && (
                  <span className="rounded-[var(--radius-sm)] border border-accent bg-accent-soft px-1.5 py-0.5 font-ui text-[0.6rem] uppercase tracking-[0.12em] text-accent-strong">
                    Popular
                  </span>
                )}
              </div>
              <p className="mt-1 font-body text-sm text-fg-2">{t.tagline}</p>
              <ul className="mt-5 flex-1 space-y-2.5">
                {t.features.map((f) => (
                  <li key={f} className="flex gap-2 font-body text-sm text-fg-2">
                    <Check size={15} className="mt-0.5 shrink-0 text-accent-strong" aria-hidden />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
              <Link
                href={t.cta.href}
                className={`mt-6 inline-flex items-center justify-center rounded-[var(--radius-md)] px-4 py-2.5 font-ui text-sm font-semibold transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none ${
                  t.featured
                    ? 'bg-accent text-accent-fg hover:brightness-110'
                    : 'border border-line-2 text-fg hover:border-accent hover:text-accent-strong'
                }`}
              >
                {t.cta.label}
              </Link>
            </div>
          ))}
        </div>

        <p className="mt-6 font-ui text-xs text-fg-3">
          Student &amp; team plans available on the billing page. Prices shown there are always current.
        </p>
      </section>
    </div>
  )
}
