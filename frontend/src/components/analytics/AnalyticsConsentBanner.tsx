'use client'

import Link from 'next/link'
import { writeAnalyticsConsent } from '@/lib/analytics/posthog'

export default function AnalyticsConsentBanner() {
  const choose = (value: 'granted' | 'denied') => {
    writeAnalyticsConsent(value, 'banner')
  }

  return (
    <section
      role="region"
      aria-label="Analytics consent"
      className="fixed inset-x-3 bottom-3 z-[var(--z-toast)] mx-auto max-w-3xl rounded-[var(--radius-lg)] border border-line bg-surface p-4 shadow-[var(--shadow-2)] sm:inset-x-6 sm:bottom-6 sm:p-5"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-fg">Help us improve Latexy</p>
          <p className="mt-1 text-xs leading-relaxed text-fg-2">
            With your permission we use optional browser analytics and masked session replay to
            understand how the product is used and to fix problems. Text and form inputs are
            masked, and résumé editing and public document pages are excluded from replay.
            Limited server-side service and billing analytics run without replay and never include
            document content.
          </p>
          <p className="mt-1 text-[11px] text-fg-3">
            Read the{' '}
            <Link href="/privacy" className="underline underline-offset-2 hover:text-fg">
              privacy policy
            </Link>
            . You can change this choice later from “Privacy choices” in the footer.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => choose('denied')}
            className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2 hover:text-fg"
          >
            Essential only
          </button>
          <button
            type="button"
            onClick={() => choose('granted')}
            className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
          >
            Allow analytics
          </button>
        </div>
      </div>
    </section>
  )
}
