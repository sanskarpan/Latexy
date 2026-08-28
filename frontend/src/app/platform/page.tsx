import Link from 'next/link'
import { FileText, GitBranch, Radio, KeyRound } from 'lucide-react'

/**
 * Platform page — "Typeset" re-skin.
 * Server-rendered, token-driven, CSS-only motion. Honest copy; fabricated
 * SLA/latency/volume numbers removed in favour of facts we can stand behind.
 */

const reveal = 'motion-safe:animate-[fade-in-up_.7s_cubic-bezier(.2,.7,.2,1)_both]'

const capabilities = [
  {
    icon: FileText,
    title: 'AI Rewrite Pipeline',
    copy: 'Context-aware rewrite of bullets with conservative, balanced, and aggressive modes — you accept, reject, or edit each change.',
  },
  {
    icon: Radio,
    title: 'ATS Signal Engine',
    copy: 'Keyword alignment, section-structure confidence, and role-fit scoring — measured against the actual job description, not a vanity number.',
  },
  {
    icon: GitBranch,
    title: 'Live Job Streaming',
    copy: 'Observe queue state, progress, and compile logs in real time over WebSocket while runs execute.',
  },
  {
    icon: KeyRound,
    title: 'BYOK Security',
    copy: 'Encrypted provider-key storage with controlled runtime decryption — your key, your models, never logged.',
  },
]

const facts: [string, string][] = [
  ['Compile processing', 'Queued with live logs'],
  ['Model providers', 'OpenAI · Anthropic · Gemini · OpenRouter'],
  ['Change review', 'Per-line accept / reject / edit'],
  ['Engines', 'pdflatex · xelatex · lualatex'],
]

export default function PlatformPage() {
  return (
    <div className="bg-bg text-fg">
      {/* ── hero ── */}
      <section className="mx-auto grid max-w-6xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[1.15fr_.85fr] lg:items-center lg:py-24">
        <div className={reveal}>
          <span className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">Platform</span>
          <h1 className="mt-5 font-display text-[clamp(2.4rem,6vw,4.6rem)] font-semibold leading-[1.0] tracking-[-0.025em] text-balance text-fg">
            A full execution layer for <span className="text-accent">résumé operations.</span>
          </h1>
          <p className="mt-6 max-w-[46ch] font-body text-lg text-fg-2">
            Latexy is built for job seekers and teams that need deterministic output, inspectable
            document checks, and a fast iteration workflow.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/try"
              className="inline-flex items-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              Open Studio →
            </Link>
            <Link
              href="/dashboard"
              className="inline-flex items-center rounded-[var(--radius-md)] border border-line-2 px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-fg transition duration-150 hover:border-accent hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              View Dashboard
            </Link>
          </div>
        </div>

        {/* system snapshot — honest facts */}
        <div
          className={`relative rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] ${reveal} motion-safe:[animation-delay:.12s]`}
        >
          <div className="absolute -top-2.5 left-5 bg-surface px-2 font-ui text-[0.6rem] uppercase tracking-[0.14em] text-fg-3">
            System Snapshot
          </div>
          <dl className="mt-2 divide-y divide-line">
            {facts.map(([k, v]) => (
              <div key={k} className="flex items-baseline justify-between gap-4 py-3 first:pt-1">
                <dt className="font-ui text-[0.62rem] uppercase tracking-[0.16em] text-fg-3">{k}</dt>
                <dd className="text-right font-body text-sm text-fg">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      {/* ── trust strip ── */}
      <div className="border-y border-line bg-surface-2">
        <div className="mx-auto flex max-w-6xl flex-wrap gap-x-8 gap-y-2 px-5 py-3 font-ui text-xs text-fg-3 sm:px-8">
          <span><span className="text-fg">Deterministic</span> compiles</span>
          <span><span className="text-fg">Inspectable</span> document checks</span>
          <span><span className="text-accent-strong">BYOK</span> — your key, your models</span>
          <span><span className="text-fg">Real-time</span> job streaming</span>
        </div>
      </div>

      {/* ── capabilities ── */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <div className="mb-8 flex items-baseline gap-3">
          <span className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">Capabilities</span>
          <span className="h-px flex-1 bg-line" />
        </div>
        <div className="grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-line bg-line md:grid-cols-2">
          {capabilities.map((item) => {
            const Icon = item.icon
            return (
              <article key={item.title} className="bg-surface p-6">
                <div className="flex items-center gap-2">
                  <Icon className="h-4 w-4 text-fg-3" aria-hidden="true" strokeWidth={1.5} />
                </div>
                <h2 className="mt-4 font-display text-xl font-semibold text-fg">{item.title}</h2>
                <p className="mt-2 font-body text-sm leading-relaxed text-fg-2">{item.copy}</p>
              </article>
            )
          })}
        </div>
      </section>

      {/* ── closing ── */}
      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-8">
          <h2 className="font-display text-[clamp(2rem,5vw,3.4rem)] font-semibold leading-[1.02] tracking-[-0.02em] text-balance text-fg">
            Run résumés like <span className="text-accent">infrastructure.</span>
          </h2>
          <p className="mx-auto mt-5 max-w-[42ch] font-body text-fg-2">
            Deterministic output, measurable performance, and iteration speed — from a single studio.
          </p>
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
