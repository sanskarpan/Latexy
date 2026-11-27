'use client'

import { useMemo, type ReactNode } from 'react'
import { analyticsSavedInsightConfig } from '@/lib/analytics/posthog'
import {
  MIN_INSIGHT_COHORT_SIZE,
  POSTHOG_INSIGHT_EMBED_POLICY,
  POSTHOG_INSIGHT_GUARDRAILS,
  resolveSavedInsightCatalog,
  SAVED_INSIGHT_CATALOG,
  savedInsightCatalogState,
  type SavedInsightLinkConfig,
} from '@/lib/analytics/saved-insights'

export interface AdminPostHogInsightsProps {
  /** Selected admin range; the same 7/30/90-day range as the KPI cards. */
  days: number
  /** Testable override; production resolves the configured PostHog project. */
  configOverride?: SavedInsightLinkConfig | null
}

function ExternalLink({
  href,
  children,
  primary = false,
}: {
  href: string
  children: ReactNode
  primary?: boolean
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={
        primary
          ? 'inline-flex items-center justify-center rounded-[var(--radius-md)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110'
          : 'inline-flex items-center justify-center rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2'
      }
    >
      {children}
    </a>
  )
}

export default function AdminPostHogInsights({
  days,
  configOverride,
}: AdminPostHogInsightsProps) {
  const config = useMemo(
    () => (configOverride === undefined ? analyticsSavedInsightConfig(days) : configOverride),
    [configOverride, days],
  )
  const state = useMemo(() => savedInsightCatalogState({ config, days }), [config, days])
  const insights = useMemo(
    () => (config ? resolveSavedInsightCatalog(config) : []),
    [config],
  )

  return (
    <section
      aria-labelledby="posthog-insights-heading"
      className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="posthog-insights-heading" className="text-sm font-semibold text-fg">
            PostHog saved insights
          </h3>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Funnels, trends, navigation paths, retention, and stickiness for the selected{' '}
            {state.days}-day range. Each view opens the configured PostHog project in one click.
            This panel is read-only and aggregate-only; the first-party KPI cards above remain the
            authoritative billing, compile, and account counts.
          </p>
        </div>
        <span
          className={
            state.configured
              ? 'rounded-full border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-ok'
              : 'rounded-full border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-warn'
          }
        >
          {state.label}
        </span>
      </div>

      {!config && (
        <div
          role="status"
          className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-warn"
        >
          <p className="font-semibold">PostHog exploration links are unavailable.</p>
          <p className="mt-1 leading-relaxed">{state.detail}</p>
          <ul className="mt-2 grid gap-1 text-[11px] text-fg-2 sm:grid-cols-2 lg:grid-cols-3">
            {SAVED_INSIGHT_CATALOG.map((descriptor) => (
              <li key={descriptor.kind}>
                {descriptor.label} · link unavailable
              </li>
            ))}
          </ul>
        </div>
      )}

      {config && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {insights.map((insight) => (
            <article
              key={insight.id}
              className="flex flex-col rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <h4 className="text-sm font-semibold text-fg">{insight.label}</h4>
                  <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{insight.description}</p>
                </div>
                <code className="shrink-0 rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] text-fg-2">
                  {insight.insightType}
                </code>
              </div>

              <dl className="mt-3 space-y-1 text-[10px] text-fg-3">
                <div className="flex gap-1.5">
                  <dt className="font-semibold uppercase tracking-wider">Range</dt>
                  <dd>{insight.dateFrom} → now</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="font-semibold uppercase tracking-wider">Events</dt>
                  <dd className="font-mono">{insight.events.join(' · ')}</dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="font-semibold uppercase tracking-wider">Breakdowns</dt>
                  <dd>
                    {insight.breakdowns.length > 0
                      ? insight.breakdowns.join(' · ')
                      : 'No breakdown · aggregate only'}
                  </dd>
                </div>
                <div className="flex gap-1.5">
                  <dt className="font-semibold uppercase tracking-wider">Source</dt>
                  <dd>{insight.mode === 'saved' ? 'Saved insight' : 'Prefilled draft'}</dd>
                </div>
              </dl>

              <div className="mt-auto flex flex-wrap gap-2 pt-3">
                <ExternalLink href={insight.href} primary>
                  Open {insight.shortLabel.toLowerCase()}
                </ExternalLink>
                {insight.savedHref && (
                  <ExternalLink href={insight.draftHref}>Open draft</ExternalLink>
                )}
              </div>
              {insight.mode === 'draft' && (
                <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
                  Save this view once in PostHog and set{' '}
                  <code className="rounded bg-bg px-1 py-0.5">
                    {SAVED_INSIGHT_CATALOG.find((item) => item.kind === insight.id)?.savedInsightEnvVar}
                  </code>{' '}
                  to pin the saved insight.
                </p>
              )}
            </article>
          ))}
        </div>
      )}

      <div className="mt-4 grid gap-3 border-t border-line pt-3 lg:grid-cols-2">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
            Guardrails
          </p>
          <ul className="mt-2 space-y-1.5 text-[11px] leading-relaxed text-fg-2">
            <li>{POSTHOG_INSIGHT_GUARDRAILS.adminOnly}</li>
            <li>{POSTHOG_INSIGHT_GUARDRAILS.noPublicSharing}</li>
            <li>{POSTHOG_INSIGHT_GUARDRAILS.piiBreakdowns}</li>
            <li>{state.cohortLabel}.</li>
          </ul>
        </div>
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
            Embedding policy
          </p>
          <p className="mt-2 text-[11px] leading-relaxed text-fg-2">
            {POSTHOG_INSIGHT_EMBED_POLICY.reason}
          </p>
          <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
            {state.fallbackLabel}. Small aggregate groups below {MIN_INSIGHT_COHORT_SIZE} are
            suppressed before interpretation. No per-user rows or person histories are requested.
          </p>
        </div>
      </div>
    </section>
  )
}
