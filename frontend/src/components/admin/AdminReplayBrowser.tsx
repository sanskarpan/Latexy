'use client'

import { useMemo, useState } from 'react'
import {
  buildReplayBrowserUrl,
  describeReplayBrowserFilters,
  EMPTY_REPLAY_BROWSER_FILTERS,
  REPLAY_BROWSER_CONSENT_COVERAGE,
  REPLAY_BROWSER_DURATION_OPTIONS,
  REPLAY_BROWSER_MASKING_POLICY,
  REPLAY_BROWSER_PLANS,
  REPLAY_BROWSER_ROUTES,
  replayBrowserSavedFilterLinks,
  type ReplayBrowserFilters,
} from '@/lib/analytics/replay-browser'
import {
  analyticsDashboardLinks,
  analyticsReplayLinkConfig,
  analyticsReplayTriageLinks,
} from '@/lib/analytics/posthog'

const RANGES = [7, 30, 90] as const

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5 border-t border-line py-2 first:border-t-0 first:pt-0 sm:grid-cols-[11rem_1fr] sm:gap-3">
      <dt className="text-[11px] font-medium text-fg-3">{label}</dt>
      <dd className="text-xs text-fg-2">{value}</dd>
    </div>
  )
}

function ExternalLink({
  href,
  children,
  primary = false,
}: {
  href: string
  children: React.ReactNode
  primary?: boolean
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={
        primary
          ? 'inline-flex items-center justify-center rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg hover:brightness-110'
          : 'inline-flex items-center justify-center rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2'
      }
    >
      {children}
    </a>
  )
}

export default function AdminReplayBrowser() {
  const [days, setDays] = useState<number>(30)
  const [route, setRoute] = useState('')
  const [plan, setPlan] = useState('')
  const [error, setError] = useState('')
  const [duration, setDuration] = useState('')
  const [checkoutFailure, setCheckoutFailure] = useState(false)

  const filters = useMemo<ReplayBrowserFilters>(
    () => ({
      route: route || null,
      plan: plan || null,
      error: error === 'console' ? 'console' : null,
      minActiveSeconds: duration ? Number(duration) : null,
      checkoutFailure,
    }),
    [checkoutFailure, duration, error, plan, route],
  )
  const config = useMemo(() => analyticsReplayLinkConfig(days), [days])
  const triage = useMemo(() => analyticsReplayTriageLinks(days), [days])
  const savedLinks = useMemo(
    () => (config ? replayBrowserSavedFilterLinks(config) : []),
    [config],
  )
  const dashboardLinks = analyticsDashboardLinks()
  const customHref = config ? buildReplayBrowserUrl(config, filters) : null
  const summary = describeReplayBrowserFilters(filters)

  const resetFilters = () => {
    setRoute(EMPTY_REPLAY_BROWSER_FILTERS.route ?? '')
    setPlan(EMPTY_REPLAY_BROWSER_FILTERS.plan ?? '')
    setError('')
    setDuration('')
    setCheckoutFailure(EMPTY_REPLAY_BROWSER_FILTERS.checkoutFailure)
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Session replay library</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Filter consented, fully masked replays by sanitized route, plan, console error, active
            duration, or checkout failure. PostHog owns the recordings and the results list; this
            view only builds the pre-filtered link for the configured project and date range, so no
            raw replay data is embedded in the admin app.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            {config ? 'PostHog configured' : 'PostHog not configured'}
          </span>
          <div
            className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
            role="group"
            aria-label="Replay date range"
          >
            {RANGES.map((range) => (
              <button
                key={range}
                type="button"
                aria-pressed={days === range}
                onClick={() => setDays(range)}
                className={`rounded px-3 py-1.5 text-xs font-medium transition ${
                  days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'
                }`}
              >
                {range} days
              </button>
            ))}
          </div>
        </div>
      </div>

      <section
        aria-labelledby="replay-privacy-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="replay-privacy-heading" className="text-sm font-semibold text-fg">
              Consent coverage and masking policy
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Replay is opt-in and fully masked. These links do not change capture, consent, or
              masking, and this view has no disable-masking control.
            </p>
          </div>
          <span className="rounded-full border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-ok">
            Enforced in code
          </span>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-2">
              Consent coverage
            </h4>
            <dl className="mt-2">
              <StatusRow label="Consent model" value={REPLAY_BROWSER_CONSENT_COVERAGE.model} />
              <StatusRow
                label="Gated routes"
                value={REPLAY_BROWSER_CONSENT_COVERAGE.gatedRoutes}
              />
              <StatusRow
                label="Capture before consent"
                value={REPLAY_BROWSER_CONSENT_COVERAGE.captureBeforeConsent}
              />
              <StatusRow
                label="Consent withdrawal"
                value={REPLAY_BROWSER_CONSENT_COVERAGE.withdrawal}
              />
              <StatusRow
                label="Excluded surfaces"
                value={REPLAY_BROWSER_CONSENT_COVERAGE.excludedSurfaces.join(', ')}
              />
            </dl>
          </div>
          <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-2">
              Masking policy
            </h4>
            <dl className="mt-2">
              <StatusRow label="Text nodes" value={REPLAY_BROWSER_MASKING_POLICY.textNodes} />
              <StatusRow label="Inputs" value={REPLAY_BROWSER_MASKING_POLICY.inputs} />
              <StatusRow
                label="Element attributes"
                value={REPLAY_BROWSER_MASKING_POLICY.elementAttributes}
              />
              <StatusRow
                label="PostHog project privacy"
                value={REPLAY_BROWSER_MASKING_POLICY.projectSetting}
              />
              <StatusRow
                label="Disable-masking switch"
                value={REPLAY_BROWSER_MASKING_POLICY.disableMasking}
              />
            </dl>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="replay-saved-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="replay-saved-heading" className="text-sm font-semibold text-fg">
              Saved filters
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Curated combinations for the common triage dimensions. Each opens the PostHog replay
              list for the selected {days}-day range.
            </p>
          </div>
        </div>

        {config ? (
          <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {savedLinks.map((saved) => (
              <a
                key={saved.id}
                href={saved.href}
                target="_blank"
                rel="noreferrer"
                className="group rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-3 transition hover:border-accent/40 hover:bg-surface-2"
              >
                <span className="block text-xs font-semibold text-fg group-hover:text-accent-strong">
                  {saved.label}
                </span>
                <span className="mt-1 block text-[11px] leading-relaxed text-fg-3">
                  {saved.description}
                </span>
                <span className="mt-2 block text-[10px] font-semibold uppercase tracking-wider text-accent-strong">
                  Open in PostHog
                </span>
              </a>
            ))}
          </div>
        ) : (
          <p className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            Set NEXT_PUBLIC_POSTHOG_PROJECT_ID to enable saved replay filters and deep links.
          </p>
        )}
      </section>

      <section
        aria-labelledby="replay-custom-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <h3 id="replay-custom-heading" className="text-sm font-semibold text-fg">
          Build a filtered view
        </h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
          Filters combine with AND. Route choices are sanitized product paths only; document,
          share, portfolio, and guest-editor surfaces are never available here.
        </p>

        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <label className="text-[11px] font-medium text-fg-3">
            Route
            <select
              aria-label="Replay route filter"
              value={route}
              onChange={(event) => setRoute(event.target.value)}
              className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
            >
              <option value="">Any route</option>
              {REPLAY_BROWSER_ROUTES.map((option) => (
                <option key={option.path} value={option.path}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-[11px] font-medium text-fg-3">
            Plan
            <select
              aria-label="Replay plan filter"
              value={plan}
              onChange={(event) => setPlan(event.target.value)}
              className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
            >
              <option value="">Any plan</option>
              {REPLAY_BROWSER_PLANS.map((option) => (
                <option key={option.key} value={option.key}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="text-[11px] font-medium text-fg-3">
            Error
            <select
              aria-label="Replay error filter"
              value={error}
              onChange={(event) => setError(event.target.value)}
              className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
            >
              <option value="">Any error state</option>
              <option value="console">Console error</option>
            </select>
          </label>

          <label className="text-[11px] font-medium text-fg-3">
            Duration
            <select
              aria-label="Replay duration filter"
              value={duration}
              onChange={(event) => setDuration(event.target.value)}
              className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
            >
              <option value="">Any duration</option>
              {REPLAY_BROWSER_DURATION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>

          <label className="flex items-center gap-2 self-end rounded border border-line bg-bg px-3 py-2 text-xs text-fg-2">
            <input
              type="checkbox"
              checked={checkoutFailure}
              onChange={(event) => setCheckoutFailure(event.target.checked)}
              className="h-4 w-4 rounded border-line text-accent"
            />
            Checkout failure
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
          <p className="text-xs text-fg-2" aria-live="polite">
            Active filters: <span className="font-medium text-fg">{summary}</span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={resetFilters}
              className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
            >
              Reset filters
            </button>
            {customHref ? (
              <ExternalLink href={customHref} primary>
                Open filtered replay list
              </ExternalLink>
            ) : (
              <span className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-3">
                Configure PostHog to open links
              </span>
            )}
          </div>
        </div>
      </section>

      <section
        aria-labelledby="replay-triage-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="replay-triage-heading" className="text-sm font-semibold text-fg">
              Triage deep links
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              One click into the most common replay investigations for the selected {days}-day
              range. Route links use templated product paths; document, share, and portfolio
              surfaces are never listed.
            </p>
          </div>
          {dashboardLinks && (
            <div className="flex flex-wrap gap-2">
              <ExternalLink href={dashboardLinks.replays}>Replay home</ExternalLink>
              <ExternalLink href={dashboardLinks.settings}>Replay privacy settings</ExternalLink>
            </div>
          )}
        </div>

        {triage ? (
          <div className="mt-4 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <ExternalLink href={triage.checkoutFailures}>Checkout failures</ExternalLink>
              <ExternalLink href={triage.jsErrors}>Console errors</ExternalLink>
              <ExternalLink href={triage.longSessions}>Long sessions</ExternalLink>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                By route
              </span>
              {triage.routes.map((link) => (
                <ExternalLink key={link.label} href={link.href}>
                  {link.label}
                </ExternalLink>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
                By plan
              </span>
              {triage.plans.map((link) => (
                <ExternalLink key={link.label} href={link.href}>
                  {link.label}
                </ExternalLink>
              ))}
            </div>
          </div>
        ) : (
          <p className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            Set NEXT_PUBLIC_POSTHOG_PROJECT_ID to show triage deep links.
          </p>
        )}
      </section>
    </div>
  )
}
