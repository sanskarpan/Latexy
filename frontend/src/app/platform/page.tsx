import Link from 'next/link'
import { MotionItem, MotionReveal, MotionStagger } from '@/components/marketing/MotionPrimitives'

const capabilities = [
  {
    title: 'AI Rewrite Pipeline',
    copy: 'Context-aware rewrite of bullets with conservative, balanced, and aggressive modes.',
  },
  {
    title: 'ATS Signal Engine',
    copy: 'Keyword alignment, section structure confidence, and role-fit scoring.',
  },
  {
    title: 'Live Job Streaming',
    copy: 'Observe queue state, progress, and logs in real-time while runs execute.',
  },
  {
    title: 'BYOK Security',
    copy: 'Encrypted provider key storage with controlled runtime decryption.',
  },
]

export default function PlatformPage() {
  return (
    <div className="content-shell py-12">
      <MotionReveal>
        <section className="grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
          <div>
            <p className="overline">Platform</p>
            <h1 className="section-title mt-2 text-white">A full execution layer for resume operations.</h1>
            <p className="mt-4 max-w-2xl text-zinc-300">
              Latexy is built for job seekers and teams that need deterministic output, measurable ATS performance, and high iteration speed.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              <Link href="/try" className="btn-accent">Open Studio</Link>
              <Link href="/dashboard" className="btn-ghost">View Dashboard</Link>
            </div>
          </div>

          <div className="surface-card edge-highlight p-5">
            <p className="overline">System Snapshot</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {[
                ['Compile SLA', '99.2%'],
                ['Median Latency', '8.4s'],
                ['Monthly Jobs', '150k+'],
                ['Model Providers', '3'],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg border border-white/10 bg-black/40 p-3">
                  <p className="text-xs text-zinc-500">{k}</p>
                  <p className="mt-1 text-lg text-white">{v}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </MotionReveal>

      <MotionStagger className="mt-8 grid gap-4 md:grid-cols-2">
        {capabilities.map((item) => (
          <MotionItem key={item.title}>
            <article className="surface-card edge-highlight p-5 transition duration-300 hover:-translate-y-1 hover:border-orange-200/30">
              <p className="overline">Capability</p>
              <h2 className="mt-3 text-xl font-semibold text-white">{item.title}</h2>
              <p className="mt-2 text-zinc-300">{item.copy}</p>
            </article>
          </MotionItem>
        ))}
      </MotionStagger>
    </div>
  )
}
