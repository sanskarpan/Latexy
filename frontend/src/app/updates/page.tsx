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
    <div className="content-shell py-12">
      <MotionReveal>
        <p className="overline">Updates</p>
        <h1 className="section-title mt-2 text-white">Shipping log and platform progress.</h1>
        <p className="mt-4 max-w-2xl text-zinc-300">
          Product and engineering updates published with clear release dates and impact notes.
        </p>
      </MotionReveal>

      <MotionStagger className="mt-8 space-y-4">
        {updates.map((item) => (
          <MotionItem key={item.title}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:border-orange-200/30">
              <p className="text-xs uppercase tracking-wider text-zinc-500">{item.date}</p>
              <h2 className="mt-2 text-xl font-semibold text-white">{item.title}</h2>
              <div className="mt-3 space-y-2 text-zinc-300">
                {item.points.map((point) => (
                  <p key={point}>{point}</p>
                ))}
              </div>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>
    </div>
  )
}
