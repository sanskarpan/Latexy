import Link from 'next/link'
import PublicPlanCatalog from '@/components/billing/PublicPlanCatalog'

export const metadata = {
  title: 'Pricing | Latexy',
  description: 'Current Latexy plans, prices and included capabilities. Start with a free account or bring your own key.',
}

export default function PricingPage() {
  return (
    <div className="bg-bg text-fg">
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <h1 className="max-w-[18ch] font-display text-[clamp(2.2rem,5.5vw,3.8rem)] font-semibold leading-[1.02] tracking-[-0.025em] text-fg text-balance">
          Start free. Choose the plan that fits.
        </h1>
        <p className="mt-5 max-w-[55ch] font-body text-lg text-fg-2">
          Compare current prices, usage allowances and included capabilities. Plans here use the same catalog as your{' '}
          <Link href="/billing" className="text-accent-strong underline-offset-4 hover:underline">billing page</Link>.
          {' '}Free account allowances are separate from the anonymous trial.
        </p>
        <PublicPlanCatalog />
        <p className="mt-8 text-sm text-fg-2">
          Already subscribed? Manage your subscription on the billing page. Retiring a plan from new sales doesn&apos;t cancel an existing subscription.
        </p>
      </section>
    </div>
  )
}
