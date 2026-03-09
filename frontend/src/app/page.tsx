import Link from 'next/link'
import dynamic from 'next/dynamic'
import HeroTypingLine from '@/components/marketing/HeroTypingLine'
import { MotionItem, MotionReveal, MotionStagger, ScrollDepth } from '@/components/marketing/MotionPrimitives'

const HeroScene3D = dynamic(() => import('@/components/marketing/HeroScene3D'), {
  ssr: false,
  loading: () => null,
})

const featureCards = [
  {
    title: 'LaTeX-First Accuracy',
    text: 'No visual drift. Production-grade resume output every run.',
  },
  {
    title: 'Signal-Driven ATS Scoring',
    text: 'Keyword fit, structure checks, and recommendations in one pass.',
  },
  {
    title: 'AI Context Optimization',
    text: 'Inject job context and auto-adapt bullets to target role intent.',
  },
]

const workflow = [
  {
    step: '01',
    title: 'Draft Or Import Resume',
    text: 'Start with your existing LaTeX resume or use a clean template baseline.',
  },
  {
    step: '02',
    title: 'Inject Job Context',
    text: 'Paste the target job description and run a context-aware optimization.',
  },
  {
    step: '03',
    title: 'Review ATS Signals',
    text: 'Check score movement, keyword alignment, and risk areas before submitting.',
  },
  {
    step: '04',
    title: 'Ship Final PDF',
    text: 'Compile and download a deterministic, application-ready resume output.',
  },
]

export default function LandingPage() {
  return (
    <div className="relative overflow-hidden py-12">
      <ScrollDepth className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_58%_44%,rgba(247,123,82,0.24),transparent_46%)]" />

      <div className="content-shell">
        <MotionReveal className="relative" y={30}>
          <div className="orange-burst relative mx-auto max-w-5xl rounded-[44px] border border-white/10 bg-black/45 p-3 sm:p-4">
            <div className="relative h-[360px] overflow-hidden rounded-[34px] bg-black sm:h-[460px]">
              <HeroScene3D />
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_52%_38%,rgba(255,132,93,0.28),transparent_42%)]" />
              <div className="absolute inset-0 bg-[radial-gradient(circle_at_50%_30%,rgba(255,183,160,0.16),transparent_48%)]" />
              <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/5 via-black/30 to-black/60" />

              <div className="absolute inset-x-0 bottom-6 z-20 px-3 sm:bottom-9">
                <h1 className="text-center text-[clamp(2.15rem,7.1vw,6.25rem)] font-semibold leading-[0.92] tracking-[-0.04em] text-white">
                  <span className="block">Build resumes</span>
                  <HeroTypingLine />
                </h1>
              </div>
            </div>
          </div>

          <p className="mx-auto mt-8 max-w-2xl text-center text-lg text-zinc-300">
            LaTeX precision, ATS intelligence, and AI optimization in one clean control surface.
          </p>

          <div className="mt-8 flex flex-wrap justify-center gap-4">
            <Link href="/try" className="btn-accent px-8 py-3 font-bold">
              Start Building
            </Link>
            <Link href="/platform" className="btn-ghost px-8 py-3 font-bold">
              Explore Platform
            </Link>
          </div>
        </MotionReveal>

        <MotionStagger className="mt-20 grid gap-4 sm:grid-cols-3">
          {[
            ['Latency', '8.4s median compile'],
            ['ATS Lift', '+23% average score gain'],
            ['Resumes', '50k+ generated monthly'],
          ].map(([k, v]) => (
            <MotionItem key={k}>
              <div className="surface-card px-6 py-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
                <p className="text-xs font-bold uppercase tracking-widest text-zinc-500">{k}</p>
                <p className="mt-2 text-xl font-bold text-white">{v}</p>
              </div>
            </MotionItem>
          ))}
        </MotionStagger>

        <MotionStagger className="mt-8 grid gap-4 md:grid-cols-3">
          {featureCards.map((card) => (
            <MotionItem key={card.title}>
              <article className="surface-card edge-highlight p-6 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
                <p className="overline">Feature</p>
                <h3 className="mt-3 text-xl font-bold text-white">{card.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-zinc-400">{card.text}</p>
              </article>
            </MotionItem>
          ))}
        </MotionStagger>

        <MotionReveal className="mt-12">
          <section className="surface-card edge-highlight p-8 sm:p-10">
            <p className="overline">Workflow</p>
            <h2 className="section-title mt-2 font-bold text-white">A complete application pipeline, not just a form.</h2>
            <p className="mt-4 max-w-3xl text-zinc-400">
              Move from resume draft to high-confidence submission with measurable quality signals at each step.
            </p>

            <div className="mt-10 grid gap-4 md:grid-cols-2">
              {workflow.map((item) => (
                <div key={item.step} className="rounded-2xl border border-white/10 border-l-4 border-l-orange-300/40 bg-black/35 p-6">
                  <p className="text-xs font-mono font-bold tracking-[0.2em] text-orange-200">STEP {item.step}</p>
                  <h3 className="mt-3 text-lg font-bold text-white">{item.title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-zinc-400">{item.text}</p>
                </div>
              ))}
            </div>
          </section>
        </MotionReveal>

        <MotionReveal className="mt-12">
          <section className="surface-panel edge-highlight bg-gradient-to-br from-orange-300/10 to-transparent p-10 text-center sm:p-16">
            <p className="overline">Get Started</p>
            <h2 className="section-title mt-2 font-bold text-white">Turn every application into a repeatable system.</h2>
            <p className="mx-auto mt-4 max-w-2xl text-lg text-zinc-400">
              Launch the studio, run your optimized pipeline, and ship stronger resumes in less time.
            </p>
            <div className="mt-10 flex flex-wrap justify-center gap-4">
              <Link href="/try" className="btn-accent px-10 py-4 text-lg font-bold">
                Open Resume Studio
              </Link>
              <Link href="/dashboard" className="btn-ghost px-10 py-4 text-lg font-bold">
                View Dashboard
              </Link>
            </div>
          </section>
        </MotionReveal>
      </div>
    </div>
  )
}
