import Link from 'next/link'

/**
 * Landing page — "Typeset" reference (redesign, PRD 2026-08-03).
 * The site is set like a printed specimen: serif display, mono labels, a baseline
 * grid, real section marks, and proof-marks used only where they mean something.
 * Token-driven (resolves to typeset·light/dark), server-rendered, CSS-only motion
 * (LCP is the headline text, not a demo). Problem-oriented sections, honest copy.
 */

const reveal = 'motion-safe:animate-[fade-in-up_.7s_cubic-bezier(.2,.7,.2,1)_both]'

const problems = [
  {
    quip: '“The AI rewrote my whole résumé.”',
    title: 'You approve every edit.',
    body: 'The optimizer drafts; you accept, reject, or rewrite each change with its reason shown. No silent auto-rewrite — the document stays yours.',
  },
  {
    quip: '“My projects live in GitHub, not a form.”',
    title: 'Import from where you work.',
    body: 'Pull your best projects from GitHub, a portfolio URL, or a LinkedIn export — summarized into résumé-ready lines you choose to keep.',
  },
  {
    quip: '“The ATS ate my formatting.”',
    title: 'Parse-clean by design.',
    body: 'Single-column, standard headings, real text — the formatting where ATS value is actually won, not keyword-stuffed to a fake score.',
  },
]

export default function LandingPage() {
  return (
    <div className="bg-bg text-fg">
      {/* ── hero ── */}
      <section className="mx-auto grid max-w-6xl gap-10 px-5 py-16 sm:px-8 lg:grid-cols-[1.15fr_.85fr] lg:items-center lg:py-24">
        <div className={reveal}>
          <span className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">
            New — import projects from GitHub, a URL, or LinkedIn
          </span>
          <h1 className="mt-5 font-display text-[clamp(2.6rem,7vw,5.4rem)] font-semibold leading-[0.98] tracking-[-0.025em] text-fg">
            Your résumé, <span className="text-accent">tailored</span> — and you approve every line.
          </h1>
          <p className="mt-6 max-w-[42ch] font-body text-lg text-fg-2">
            Write in LaTeX, let the AI tailor it to the role, and review every change before it lands.
            Output that looks like it came off a press — because it did.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <Link
              href="/try"
              className="inline-flex items-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              Start compiling →
            </Link>
            <Link
              href="/templates"
              className="inline-flex items-center rounded-[var(--radius-md)] border border-line-2 px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-fg transition duration-150 hover:border-accent hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
            >
              See an example
            </Link>
            <span className="font-ui text-xs text-fg-3">3 free compiles · no card</span>
          </div>
        </div>

        {/* living specimen */}
        <div
          className={`relative rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] ${reveal} motion-safe:[animation-delay:.12s]`}
          aria-label="A résumé being edited"
        >
          <div className="absolute -top-2.5 left-5 bg-surface px-2 font-ui text-[0.6rem] uppercase tracking-[0.14em] text-fg-3">
            resume.tex → resume.pdf
          </div>
          <p className="font-display text-2xl font-semibold text-fg">Ada Lovelace</p>
          <p className="mt-0.5 font-ui text-xs text-fg-3">Staff Engineer · London · ada@analytical.dev</p>
          <div className="my-3 h-px bg-fg" />
          <p className="font-ui text-[0.62rem] uppercase tracking-[0.2em] text-accent-strong">Experience</p>
          <p className="mt-1 font-body text-sm leading-relaxed text-fg-2">
            Led the{' '}
            <span className="border-b-2 border-accent bg-accent-soft px-0.5 text-fg">Kubernetes</span>{' '}
            migration, cutting p95 latency{' '}
            <span className="text-err line-through decoration-err">a lot</span>{' '}
            <span className="border-b-2 border-accent bg-accent-soft px-0.5 text-fg">from 380ms to 140ms</span>.
          </p>
          <p className="mt-3 font-ui text-[0.62rem] uppercase tracking-[0.2em] text-accent-strong">Skills</p>
          <p className="mt-1 font-body text-sm text-fg-2">
            Go · Rust ·{' '}
            <span className="border-b-2 border-accent bg-accent-soft px-0.5 text-fg">Distributed systems</span> · Postgres
          </p>
          <p className="mt-4 font-ui text-[0.62rem] leading-relaxed text-fg-3">
            ↑ AI proposed 3 edits · you accepted 2, kept your voice.
          </p>
        </div>
      </section>

      {/* ── trust strip (honest facts, no fabricated numbers) ── */}
      <div className="border-y border-line bg-surface-2">
        <div className="mx-auto flex max-w-6xl flex-wrap gap-x-8 gap-y-2 px-5 py-3 font-ui text-xs text-fg-3 sm:px-8">
          <span><span className="text-fg">Sub-second</span> compiles</span>
          <span><span className="text-fg">4</span> import sources: <span className="text-accent-strong">github · url · linkedin · pdf</span></span>
          <span><span className="text-fg">Per-change</span> accept / reject / edit</span>
          <span><span className="text-fg">BYOK</span> — your key, your models</span>
        </div>
      </div>

      {/* ── problems, not features ── */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <div className="grid gap-px overflow-hidden rounded-[var(--radius-lg)] border border-line bg-line md:grid-cols-3">
          {problems.map((p) => (
            <article key={p.title} className="bg-surface p-6">
              <span className="font-ui text-[0.72rem] italic text-fg-3">{p.quip}</span>
              <h3 className="mt-3 font-display text-xl font-semibold text-fg">{p.title}</h3>
              <p className="mt-2 font-body text-sm leading-relaxed text-fg-2">{p.body}</p>
            </article>
          ))}
        </div>
      </section>

      {/* ── product moment: source → impression ── */}
      <section className="mx-auto max-w-6xl px-5 pb-16 sm:px-8">
        <div className="mb-6">
          <h2 className="font-display text-[clamp(1.5rem,3vw,2.1rem)] font-semibold text-fg">
            Source on the left. Impression on the right.
          </h2>
        </div>
        <div className="grid overflow-hidden rounded-[var(--radius-lg)] border border-line md:grid-cols-2">
          <div className="border-b border-line bg-code-bg p-5 md:border-b-0 md:border-r">
            <div className="mb-3 flex justify-between font-ui text-[0.6rem] uppercase tracking-[0.14em] text-fg-3">
              <span>resume.tex</span><span>utf-8 · lualatex</span>
            </div>
            <pre className="overflow-x-auto font-ui text-[0.76rem] leading-relaxed text-code-fg">
{`\\section{Experience}
\\resumeItem{Architected a scalable
  payments pipeline, cutting
  latency 40%.}

\\section{Skills}
Go, Rust, Kubernetes, Postgres`}</pre>
          </div>
          <div className="bg-surface p-5">
            <div className="mb-3 flex justify-between font-ui text-[0.6rem] uppercase tracking-[0.14em] text-fg-3">
              <span>resume.pdf</span><span>1 page · compiled 0.8s</span>
            </div>
            <p className="font-display text-xl font-semibold text-fg">Ada Lovelace</p>
            <p className="font-ui text-xs text-fg-3">Staff Engineer · London</p>
            <div className="my-2 h-px bg-fg" />
            <p className="font-ui text-[0.6rem] uppercase tracking-[0.2em] text-accent-strong">Experience</p>
            <p className="mt-1 font-body text-sm text-fg-2">Architected a scalable payments pipeline, cutting latency 40%.</p>
            <p className="mt-3 font-ui text-[0.6rem] uppercase tracking-[0.2em] text-accent-strong">Skills</p>
            <p className="mt-1 font-body text-sm text-fg-2">Go · Rust · Kubernetes · Postgres</p>
          </div>
        </div>
      </section>

      {/* ── closing ── */}
      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-5 py-20 text-center sm:px-8">
          <h2 className="font-display text-[clamp(2rem,5.5vw,3.8rem)] font-semibold leading-[1.02] tracking-[-0.02em] text-fg">
            Compile something <span className="text-accent">worth reading.</span>
          </h2>
          <p className="mx-auto mt-5 max-w-[40ch] font-body text-fg-2">
            Three free compiles. Bring your own key or use ours. Your résumé, finally set right.
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
