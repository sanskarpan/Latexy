import MarketingFrame from '@/components/marketing/MarketingFrame'
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
    <MarketingFrame>
      <MotionReveal>
        <p className="overline">FAQ</p>
        <h1 className="section-title mt-2 text-white">Clear answers for product, workflow, and reliability.</h1>
      </MotionReveal>

      <MotionStagger className="mt-8 grid gap-4 md:grid-cols-2">
        {faqs.map((item) => (
          <MotionItem key={item.q}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <h2 className="text-lg font-semibold text-white">{item.q}</h2>
              <p className="mt-2 text-zinc-300">{item.a}</p>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>
    </MarketingFrame>
  )
}
