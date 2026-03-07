import Link from 'next/link'
import { MotionItem, MotionReveal, MotionStagger } from '@/components/marketing/MotionPrimitives'

const cards = [
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
    <div className="content-shell py-12">
      <MotionReveal>
        <p className="overline">Resources</p>
        <h1 className="section-title mt-2 text-white">Everything needed to ship better resumes, faster.</h1>
        <p className="mt-4 max-w-2xl text-zinc-300">
          Practical resources focused on outcomes: stronger interviews, faster iteration, better scoring confidence.
        </p>
      </MotionReveal>

      <MotionStagger className="mt-8 grid gap-4 md:grid-cols-2">
        {cards.map((item) => (
          <MotionItem key={item.title}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <p className="overline">Resource</p>
              <h2 className="mt-3 text-xl font-semibold text-white">{item.title}</h2>
              <p className="mt-2 text-zinc-300">{item.text}</p>
              <Link href={item.href} className="mt-4 inline-flex text-sm text-orange-200 hover:text-white">
                {item.cta}
              </Link>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>
    </div>
  )
}
