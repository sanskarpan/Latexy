'use client'

import Link from 'next/link'
import dynamic from 'next/dynamic'
import { useEffect, useState } from 'react'
import MarketingFrame from '@/components/marketing/MarketingFrame'
import { MotionItem, MotionReveal, MotionStagger, ScrollDepth } from '@/components/marketing/MotionPrimitives'

const HeroScene3D = dynamic(() => import('@/components/marketing/HeroScene3D'), {
  ssr: false,
})

const heroPhrases = [
  'people remember.',
  'recruiters shortlist.',
  'ATS systems score.',
  'hiring teams trust.',
]

const leftLinks = [
  { label: 'Resume Studio', href: '/try' },
  { label: 'ATS Engine', href: '/platform' },
  { label: 'BYOK Keys', href: '/byok' },
  { label: 'Live Jobs', href: '/dashboard' },
  { label: 'Billing', href: '/billing' },
]

const rightLinks = [
  { label: 'Documentation', href: '/resources' },
  { label: 'API Access', href: '/platform' },
  { label: 'Integrations', href: '/platform' },
  { label: 'Security', href: '/faq' },
  { label: 'Changelog', href: '/updates' },
]

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

const pillars = [
  {
    title: 'Systemic Workflow',
    text: 'Everything from optimization to compile runs in a clear, observable execution path.',
  },
  {
    title: 'Measured Outcomes',
    text: 'Track ATS score lift and optimization impact instead of iterating blindly.',
  },
  {
    title: 'Enterprise Reliability',
    text: 'Stable queues, event streaming, and robust provider architecture with BYOK support.',
  },
]

export default function LandingPage() {
  const [phraseIndex, setPhraseIndex] = useState(0)
  const [typedText, setTypedText] = useState('')
  const [isDeleting, setIsDeleting] = useState(false)
  const [mounted, setMounted] = useState(false)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!mounted) return
    const currentPhrase = heroPhrases[phraseIndex]
    const isFinishedTyping = typedText === currentPhrase
    const isFinishedDeleting = typedText.length === 0

    let timeout = 70

    if (!isDeleting && isFinishedTyping) {
      timeout = 1500
      const timer = setTimeout(() => setIsDeleting(true), timeout)
      return () => clearTimeout(timer)
    }

    if (isDeleting && isFinishedDeleting) {
      setIsDeleting(false)
      setPhraseIndex((prev) => (prev + 1) % heroPhrases.length)
      return
    }

    if (isDeleting) {
      timeout = 34
      const timer = setTimeout(() => {
        setTypedText(currentPhrase.slice(0, typedText.length - 1))
      }, timeout)
      return () => clearTimeout(timer)
    }

    const timer = setTimeout(() => {
      setTypedText(currentPhrase.slice(0, typedText.length + 1))
    }, timeout)

    return () => clearTimeout(timer)
  }, [typedText, isDeleting, phraseIndex, mounted])

  if (!mounted) return <div className="min-h-screen bg-black" />

  return (
    <div className="relative overflow-hidden py-12">
      <ScrollDepth className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_58%_44%,rgba(247,123,82,0.24),transparent_46%)]" />

      <div className="relative grid gap-6 xl:grid-cols-[0.2fr_1fr_0.26fr]">
        <MotionReveal className="hidden space-y-3 text-zinc-400 xl:block" delay={0.1}>
          {leftLinks.map((item) => (
            <Link key={item.label} href={item.href} className="block text-base hover:text-white">
              {item.label}
            </Link>
          ))}
        </MotionReveal>

        <div>
          <MotionReveal className="relative" y={30}>
            <div className="orange-burst relative mx-auto max-w-5xl rounded-[44px] border border-white/10 bg-black/45 p-3 sm:p-4">
              <div className="relative h-[360px] overflow-hidden rounded-[34px] bg-black sm:h-[460px]">
                <HeroScene3D />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-black/5 via-black/30 to-black/60" />
                <div className="absolute inset-x-0 bottom-6 z-20 px-3 sm:bottom-9">
                  <h1 className="text-center font-semibold text-white leading-[0.92] tracking-[-0.04em] text-[clamp(2.15rem,7.1vw,6.25rem)]">
                    <span className="block">Build resumes</span>
                    <span className="block min-h-[1.1em] whitespace-nowrap">
                      {typedText}
                      <span className="ml-1 inline-block h-[0.85em] w-[0.08em] bg-white/90 align-[-0.05em] animate-pulse" />
                    </span>
                  </h1>
                </div>
              </div>
            </div>

            <p className="mx-auto mt-6 max-w-2xl text-center text-lg text-zinc-300">
              LaTeX precision, ATS intelligence, and AI optimization in one clean control surface.
            </p>

            <div className="mt-7 flex flex-wrap justify-center gap-3">
              <Link href="/try" className="btn-primary text-base">
                Start Building
              </Link>
              <Link href="/platform" className="btn-ghost text-base">
                Explore Platform
              </Link>
            </div>
          </MotionReveal>
        </div>

        <MotionReveal className="hidden space-y-3 text-zinc-400 xl:block xl:text-right" delay={0.15}>
          {rightLinks.map((item) => (
            <Link key={item.label} href={item.href} className="block text-base hover:text-white">
              {item.label}
            </Link>
          ))}
        </MotionReveal>
      </div>

      <MotionStagger className="mt-14 grid gap-4 sm:grid-cols-3">
        {[
          ['Latency', '8.4s median compile'],
          ['ATS Lift', '+23% average score gain'],
          ['Resumes', '50k+ generated monthly'],
        ].map(([k, v]) => (
          <MotionItem key={k}>
            <div className="surface-card px-4 py-3 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <p className="text-sm text-zinc-400">{k}</p>
              <p className="mt-1 text-lg text-white">{v}</p>
            </div>
          </MotionItem>
        ))}
      </MotionStagger>

      <MotionStagger className="mt-8 grid gap-4 md:grid-cols-3">
        {featureCards.map((card) => (
          <MotionItem key={card.title}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <p className="overline">Feature</p>
              <h3 className="mt-3 text-xl font-semibold text-white">{card.title}</h3>
              <p className="mt-2 text-zinc-300">{card.text}</p>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>

      <MotionReveal className="mt-10">
        <section className="surface-card edge-highlight p-6 sm:p-8">
          <p className="overline">Workflow</p>
          <h2 className="section-title mt-2 text-white">A complete application pipeline, not just a form.</h2>
          <p className="mt-3 max-w-3xl text-zinc-300">
            Move from resume draft to high-confidence submission with measurable quality signals at each step.
          </p>

          <div className="mt-6 grid gap-3 md:grid-cols-2">
            {workflow.map((item) => (
              <div key={item.step} className="rounded-xl border border-white/10 bg-black/35 p-4">
                <p className="text-xs font-mono tracking-[0.2em] text-orange-200">STEP {item.step}</p>
                <h3 className="mt-2 text-lg font-semibold text-white">{item.title}</h3>
                <p className="mt-2 text-sm text-zinc-300">{item.text}</p>
              </div>
            ))}
          </div>
        </section>
      </MotionReveal>

      <MotionStagger className="mt-8 grid gap-4 md:grid-cols-3">
        {pillars.map((item) => (
          <MotionItem key={item.title}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <p className="overline">Pillar</p>
              <h3 className="mt-3 text-xl font-semibold text-white">{item.title}</h3>
              <p className="mt-2 text-zinc-300">{item.text}</p>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>

      <MotionReveal className="mt-10">
        <section className="surface-panel edge-highlight p-6 text-center sm:p-8">
          <p className="overline">Ready</p>
          <h2 className="section-title mt-2 text-white">Turn every application into a repeatable system.</h2>
          <p className="mx-auto mt-3 max-w-2xl text-zinc-300">
            Launch the studio, run your optimized pipeline, and ship stronger resumes in less time.
          </p>
          <div className="mt-6 flex flex-wrap justify-center gap-3">
            <Link href="/try" className="btn-accent">
              Open Resume Studio
            </Link>
            <Link href="/dashboard" className="btn-ghost">
              View Dashboard
            </Link>
          </div>
        </section>
      </MotionReveal>
    </MarketingFrame>
  )
}
