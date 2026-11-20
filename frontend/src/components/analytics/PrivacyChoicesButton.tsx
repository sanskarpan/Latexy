'use client'

import { writeAnalyticsConsent } from '@/lib/analytics/posthog'

/** Re-opens the analytics choice without requiring a page reload. */
export default function PrivacyChoicesButton() {
  return (
    <button
      type="button"
      onClick={() => writeAnalyticsConsent(null)}
      className="font-ui text-xs text-fg-3 transition hover:text-fg"
    >
      Privacy choices
    </button>
  )
}
