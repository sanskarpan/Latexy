'use client'

import { useMemo, useState, type ReactNode } from 'react'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'
import {
  analyticsQualityLinkConfig,
  analyticsRelease,
} from '@/lib/analytics/posthog'
import {
  buildQualityErrorTrackingUrl,
  buildQualityReplayUrl,
  buildQualityTrendsUrl,
  describeQualityFilters,
  normalizeQualityRelease,
  QUALITY_GUARDRAILS,
  QUALITY_ISSUES,
  QUALITY_MIN_COHORT_SIZE,
  QUALITY_RANGES,
  QUALITY_ROUTES,
  qualitySavedInsights,
  qualityTelemetryState,
  type QualityRange,
  type QualityTriageFilters,
} from '@/lib/analytics/quality-triage'

export interface AdminQualityTriageProps {
  /** Testable override; production resolves the configured PostHog project. */
  configOverride?: ReplayLinkConfig | null
  /** Testable override; production reads NEXT_PUBLIC_APP_RELEASE. */
  releaseOverride?: string | null
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

function MissingTelemetry({ compact = false }: { compact?: boolean }) {
  return (
    <span
      className={
        compact
          ? 'text-[11px] font-medium text-warn'
          : 'inline-flex items-center rounded-full border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-warn'
      }
      title="This value is unavailable, not zero."
    >
      Missing telemetry
    </span>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-0.5 border-t border-line py-2 first:border-t-0 first:pt-0 sm:grid-cols-[10rem_1fr] sm:gap-3">
      <dt className="text-[11px] font-medium text-fg-3">{label}</dt>
      <dd className="text-xs leading-relaxed text-fg-2">{value}</dd>
    </div>
  )
}

export default function AdminQualityTriage({
  configOverride,
  releaseOverride,
}: AdminQualityTriageProps) {
  const [days, setDays] = useState<QualityRange>(30)
  const [route, setRoute] = useState('')
  const [releaseInput, setReleaseInput] = useState(() =>
    releaseOverride === undefined ? (analyticsRelease() ?? '') : (releaseOverride ?? ''),
  )

  const config = useMemo(
    () => (configOverride === undefined ? analyticsQualityLinkConfig(days) : configOverride),
    [configOverride, days],
  )
  const release = normalizeQualityRelease(releaseInput)
  const releaseInvalid = releaseInput.trim().length > 0 && release === null
  const filters = useMemo<QualityTriageFilters>(
    () => ({ route: route || null, release }),
    [release, route],
  )
  const telemetry = useMemo(
    () => qualityTelemetryState({ configured: Boolean(config), release, days }),
    [config, days, release],
  )
  const savedInsights = useMemo(
    () => (config ? qualitySavedInsights(config, filters) : []),
    [config, filters],
  )
  const summary = describeQualityFilters(filters)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Quality triage</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Route-level JavaScript errors, rage clicks, and dead clicks. Every row opens a
            pre-filtered PostHog trends insight or replay list for the sanitized route, release, and
            selected 7/30-day range. This view is aggregate-only and never embeds replay, person, or
            session data.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            {config ? 'PostHog linked' : 'Telemetry unavailable'}
          </span>
          <div
            className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5"
            role="group"
            aria-label="Quality triage period"
          >
            {QUALITY_RANGES.map((range) => (
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

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <label className="text-[11px] font-medium text-fg-3">
          Route
          <select
            aria-label="Quality route filter"
            value={route}
            onChange={(event) => setRoute(event.target.value)}
            className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="">All routes</option>
            {QUALITY_ROUTES.map((option) => (
              <option key={option.path} value={option.path}>
                {option.label} ({option.path})
              </option>
            ))}
          </select>
        </label>

        <label className="text-[11px] font-medium text-fg-3">
          Release
          <input
            aria-label="Quality release filter"
            aria-invalid={releaseInvalid || undefined}
            value={releaseInput}
            onChange={(event) => setReleaseInput(event.target.value)}
            placeholder="Deployed SHA or version"
            maxLength={64}
            className="mt-1 block min-h-[38px] w-full rounded border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          />
        </label>

        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/40 px-3 py-2 sm:col-span-2">
          <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">
            Active filters
          </p>
          <p className="mt-1 text-xs font-medium text-fg" aria-live="polite">
            {summary}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
            Release values accept letters, digits, dot, colon, dash, or underscore (maximum 64).
            Invalid values are ignored rather than sent to PostHog.
          </p>
          {releaseInvalid && (
            <p role="alert" className="mt-1 text-[11px] font-medium text-warn">
              Release ignored. Use a bounded identifier such as a git SHA or semantic version.
            </p>
          )}
        </div>
      </div>

      <section
        aria-labelledby="quality-telemetry-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="quality-telemetry-heading" className="text-sm font-semibold text-fg">
              Telemetry and suppression
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">{telemetry.detail}</p>
          </div>
          <span
            className={
              telemetry.missing
                ? 'rounded-full border border-warn/30 bg-warn/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-warn'
                : 'rounded-full border border-ok/30 bg-ok/10 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-ok'
            }
          >
            {telemetry.label}
          </span>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <dl className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
            <StatusRow label="Range" value={`${days} days`} />
            <StatusRow label="Release" value={telemetry.releaseLabel} />
            <StatusRow label="Cohort policy" value={telemetry.suppressionLabel} />
            <StatusRow
              label="Data boundary"
              value="Event class, sanitized route, release, and aggregate count only"
            />
          </dl>
          <div className="rounded-[var(--radius-md)] border border-line bg-surface-2/30 p-4">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-fg-2">
              Why this is not zero-filled
            </h4>
            <p className="mt-2 text-xs leading-relaxed text-fg-3">
              Missing telemetry is shown as unavailable because an absent PostHog project, a blocked
              browser request, or a deployment without the project token cannot prove that zero
              issues occurred. Only PostHog aggregates can distinguish an empty result from missing
              capture.
            </p>
            <p className="mt-2 text-xs leading-relaxed text-fg-3">
              PostHog breakdown groups with fewer than {QUALITY_MIN_COHORT_SIZE} events are suppressed
              before interpretation. This view never requests a person, session, or event history.
            </p>
          </div>
        </div>
      </section>

      <section
        aria-labelledby="quality-saved-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="quality-saved-heading" className="text-sm font-semibold text-fg">
              Saved insights · {days} days
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              The three saved-insight descriptors used for quality triage. Each opens an aggregate
              trends table ranked by event count or a replay list carrying the selected route and
              release. Counts are not mirrored here, so an unavailable project is labelled rather
              than shown as zero.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            No per-user rows
          </span>
        </div>

        {config ? (
          <div className="mt-4 grid gap-3 lg:grid-cols-3">
            {savedInsights.map((insight) => (
              <article
                key={insight.id}
                className="flex flex-col rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-4"
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h4 className="text-sm font-semibold text-fg">{insight.label}</h4>
                    <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
                      {insight.description}
                    </p>
                  </div>
                  <code className="shrink-0 rounded border border-line bg-bg px-1.5 py-0.5 text-[10px] text-fg-2">
                    {insight.event}
                  </code>
                </div>
                <p className="mt-3 text-[10px] font-medium uppercase tracking-wider text-fg-3">
                  Breakdowns: {insight.breakdowns.join(' · ')}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <ExternalLink href={insight.trendsHref} primary>
                    Open trends
                  </ExternalLink>
                  <ExternalLink href={insight.replayHref}>Open replays</ExternalLink>
                  {insight.errorTrackingHref && (
                    <ExternalLink href={insight.errorTrackingHref}>Error tracking</ExternalLink>
                  )}
                </div>
              </article>
            ))}
          </div>
        ) : (
          <p className="mt-4 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-3 py-2 text-xs text-warn">
            {QUALITY_ISSUES[0].missingTelemetry} Set NEXT_PUBLIC_POSTHOG_PROJECT_ID to enable saved
            insight and replay links. No count is displayed as zero.
          </p>
        )}
      </section>

      <section
        aria-labelledby="quality-routes-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 id="quality-routes-heading" className="text-sm font-semibold text-fg">
              By route and release · {days} days
            </h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Each cell opens an aggregate PostHog view for that issue class. Document, share,
              portfolio, and guest-editor paths are intentionally absent; telemetry is blocked
              there.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            {config ? 'Filtered links' : 'Telemetry unavailable'}
          </span>
        </div>

        <div className="mt-4 overflow-x-auto rounded border border-line">
          <table className="min-w-full border-collapse text-left text-xs">
            <caption className="sr-only">
              Quality triage links by sanitized route and issue class. No counts or per-user data
              are shown, and a missing PostHog project is labelled rather than zero-filled.
            </caption>
            <thead className="bg-surface-2 text-[10px] uppercase tracking-[0.14em] text-fg-3">
              <tr>
                <th scope="col" className="px-3 py-2 font-semibold">
                  Route
                </th>
                {QUALITY_ISSUES.map((issue) => (
                  <th key={issue.kind} scope="col" className="px-3 py-2 font-semibold">
                    {issue.shortLabel}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {QUALITY_ROUTES.map((routeOption) => {
                const rowFilters: QualityTriageFilters = {
                  route: routeOption.path,
                  release,
                }
                return (
                  <tr key={routeOption.path}>
                    <th scope="row" className="px-3 py-2 font-medium text-fg">
                      <span className="block">{routeOption.label}</span>
                      <code className="mt-0.5 block text-[10px] font-normal text-fg-3">
                        {routeOption.path}
                      </code>
                    </th>
                    {QUALITY_ISSUES.map((issue) => (
                      <td key={issue.kind} className="px-3 py-2 align-top">
                        {config ? (
                          <div className="flex flex-wrap gap-1.5">
                            <ExternalLink href={buildQualityTrendsUrl(config, issue, rowFilters)}>
                              Trends
                            </ExternalLink>
                            <ExternalLink href={buildQualityReplayUrl(config, issue, rowFilters)}>
                              Replays
                            </ExternalLink>
                            {issue.errorTracking && (
                              <ExternalLink href={buildQualityErrorTrackingUrl(config)}>
                                Errors
                              </ExternalLink>
                            )}
                          </div>
                        ) : (
                          <MissingTelemetry compact />
                        )}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section
        aria-labelledby="quality-guardrails-heading"
        className="rounded-[var(--radius-lg)] border border-line bg-surface p-5"
      >
        <h3 id="quality-guardrails-heading" className="text-sm font-semibold text-fg">
          Guardrails
        </h3>
        <ul className="mt-3 space-y-2 text-xs leading-relaxed text-fg-2">
          <li>{QUALITY_GUARDRAILS.consent}</li>
          <li>{QUALITY_GUARDRAILS.masking}</li>
          <li>
            Excluded surfaces: {QUALITY_GUARDRAILS.excludedSurfaces.join(', ')}. JavaScript errors,
            rage clicks, and dead clicks on those pages are dropped before they reach PostHog;
            replay is blocked there too.
          </li>
          <li>{QUALITY_GUARDRAILS.perUser}</li>
          <li>{QUALITY_GUARDRAILS.suppression}</li>
        </ul>
      </section>
    </div>
  )
}
