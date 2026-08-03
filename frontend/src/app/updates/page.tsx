import { MotionItem, MotionReveal, MotionStagger } from '@/components/marketing/MotionPrimitives'

const updates = [
  {
    date: 'March 06, 2026',
    title: 'New Premium Frontend System',
    points: ['Rebuilt marketing experience with multi-page architecture', 'Unified dark visual language across app and marketing routes'],
  },
  {
    date: 'March 04, 2026',
    title: 'Expanded Job Event Streaming',
    points: ['Improved event flow for logs, progress, and token streams', 'Enhanced reliability in queue-driven execution'],
  },
  {
    date: 'March 01, 2026',
    title: 'BYOK Provider Enhancements',
    points: ['Improved key validation flow', 'Better provider metadata support'],
  },
]

export default function UpdatesPage() {
  return (
    <div className="bg-bg text-fg">
      {/* folio strip */}
      <div className="border-b border-line">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-2 font-ui text-[0.62rem] uppercase tracking-[0.16em] text-fg-3 sm:px-8">
          <span>The Shipping Log</span>
          <span className="hidden sm:inline">Set in Fraunces &amp; JetBrains Mono</span>
          <span>{updates.length} releases</span>
        </div>
      </div>

      {/* ── masthead ── */}
      <section className="mx-auto max-w-6xl px-5 py-16 sm:px-8 lg:py-24">
        <MotionReveal>
          <span className="font-ui text-xs uppercase tracking-[0.18em] text-fg-3">Updates</span>
          <h1 className="mt-5 max-w-[18ch] text-balance font-display text-[clamp(2.4rem,6vw,4.6rem)] font-semibold leading-[1.0] tracking-[-0.025em] text-fg">
            Shipping log and <em className="italic text-accent">platform progress.</em>
          </h1>
          <p className="mt-6 max-w-[46ch] font-body text-lg text-fg-2">
            Product and engineering updates published with clear release dates and impact notes.
          </p>
        </MotionReveal>
      </section>

      {/* ── changelog ── */}
      <section className="mx-auto max-w-6xl px-5 pb-24 sm:px-8">
        <MotionStagger className="border-t border-line">
          {updates.map((item, i) => (
            <MotionItem key={item.title}>
              <article className="grid gap-4 border-b border-line py-10 md:grid-cols-[.85fr_2.15fr] md:gap-10">
                <div className="flex items-baseline gap-3 md:flex-col md:items-start md:gap-2">
                  <span className="font-ui text-xs text-accent-strong">§ {updates.length - i}</span>
                  <time className="font-ui text-xs uppercase tracking-[0.14em] text-fg-3">{item.date}</time>
                </div>
                <div>
                  <h2 className="font-display text-2xl font-semibold text-fg">{item.title}</h2>
                  <ul className="mt-4 space-y-3">
                    {item.points.map((point) => (
                      <li key={point} className="flex gap-3 font-body text-fg-2">
                        <span aria-hidden className="mt-[0.55em] h-px w-4 shrink-0 bg-accent" />
                        <span className="leading-relaxed">{point}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </article>
            </MotionItem>
          ))}
        </MotionStagger>
      </section>
    </div>
  )
}
