'use client'

import Link from 'next/link'
import { useEffect } from 'react'

/**
 * Route-level error boundary (redesign). Renders inside the root layout, so it
 * inherits the active aesthetic + mode tokens — sibling to not-found.tsx.
 */
export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <div className="flex min-h-[70vh] flex-col items-center justify-center bg-bg px-6 py-20 text-center text-fg">
      <p className="font-mono text-sm uppercase tracking-[0.3em] text-accent-strong">500 · Error</p>
      <h1 className="mt-4 max-w-[18ch] text-balance font-display text-[clamp(2rem,5vw,3.4rem)] font-semibold leading-[1.05] tracking-[-0.02em] text-fg">
        Something broke on our end.
      </h1>
      <p className="mt-4 max-w-[42ch] font-body text-base text-fg-2">
        This one is on us, not you. The team has been notified — try again in a moment, or head
        back to somewhere solid.
      </p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <button
          type="button"
          onClick={() => reset()}
          className="inline-flex items-center rounded-[var(--radius-md)] bg-accent px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
          Try again
        </button>
        <Link
          href="/"
          className="inline-flex items-center rounded-[var(--radius-md)] border border-line-2 px-6 py-3 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-fg transition duration-150 hover:border-accent hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
        >
          Back home
        </Link>
      </div>
    </div>
  )
}
