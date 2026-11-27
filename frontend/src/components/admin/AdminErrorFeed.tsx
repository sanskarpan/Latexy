'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminErrorAlertEvaluation,
  type AdminErrorFeedResponse,
  type AdminErrorGroup,
} from '@/lib/api-client'
import {
  analyticsQualityLinkConfig,
} from '@/lib/analytics/posthog'
import type { ReplayLinkConfig } from '@/lib/analytics/replay-links'
import {
  buildQualityErrorGroupErrorTrackingUrl,
  buildQualityErrorGroupReplayUrl,
} from '@/lib/analytics/quality-triage'
import { formatNumber } from '@/components/admin/admin-format'

const RANGES = [7, 30] as const
type Range = (typeof RANGES)[number]

export interface AdminErrorFeedProps {
  /** Testable override; production resolves the configured PostHog project. */
  configOverride?: ReplayLinkConfig | null
  /** Testable override; production fetches the aggregate feed. */
  feedOverride?: AdminErrorFeedResponse | null
}

function formatTimestamp(value: string | null): string {
  if (!value) return 'Missing telemetry'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Missing telemetry' : date.toLocaleString()
}

function SourceBadge({ source }: { source: AdminErrorGroup['source'] }) {
  return (
    <span
      className={
        source === 'backend'
          ? 'inline-flex items-center rounded-full border border-accent/30 bg-accent-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-accent'
          : 'inline-flex items-center rounded-full border border-line bg-surface-2 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-fg-2'
      }
    >
      {source}
    </span>
  )
}

function LinkCell({ group, config }: { group: AdminErrorGroup; config: ReplayLinkConfig | null }) {
  if (!config) {
    return <span className="text-[11px] text-fg-3">Missing telemetry</span>
  }
  return (
    <div className="flex flex-wrap gap-2">
      <a
        href={buildQualityErrorGroupReplayUrl(config, group)}
        target="_blank"
        rel="noreferrer"
        className="text-[11px] font-medium text-accent hover:underline"
      >
        Replay
      </a>
      <a
        href={buildQualityErrorGroupErrorTrackingUrl(config, group)}
        target="_blank"
        rel="noreferrer"
        className="text-[11px] font-medium text-accent hover:underline"
      >
        Error tracking
      </a>
    </div>
  )
}

export default function AdminErrorFeed({ configOverride, feedOverride }: AdminErrorFeedProps) {
  const [days, setDays] = useState<Range>(7)
  const [data, setData] = useState<AdminErrorFeedResponse | null>(feedOverride ?? null)
  const [loading, setLoading] = useState(feedOverride === undefined)
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [evaluation, setEvaluation] = useState<AdminErrorAlertEvaluation | null>(null)

  const load = useCallback(async (range: Range) => {
    setLoading(true)
    setError(null)
    try {
      const feed = await apiClient.getAdminErrorFeed({ days: range, limit: 25 })
      setData(feed)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load the error feed')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (feedOverride !== undefined) {
      setData(feedOverride)
      setLoading(false)
      return
    }
    void load(days)
  }, [days, feedOverride, load])

  const config = useMemo(
    () => (configOverride === undefined ? analyticsQualityLinkConfig(days) : configOverride),
    [configOverride, days],
  )

  const evaluate = async (dryRun: boolean) => {
    const cleanedReason = reason.trim()
    if (!dryRun) {
      if (cleanedReason.length < 3) {
        toast.error('Enter a reason for this dispatch (at least 3 characters)')
        return
      }
      if (!confirmed) {
        toast.error('Confirm the dispatch before sending alerts')
        return
      }
    }
    setBusy(true)
    try {
      const result = await apiClient.evaluateAdminErrorAlerts({
        reason: cleanedReason.length >= 3 ? cleanedReason : 'Preview error alert thresholds',
        confirm: dryRun ? false : true,
        dry_run: dryRun,
      })
      setEvaluation(result)
      if (!dryRun) {
        toast.success(
          result.alerted > 0
            ? `Dispatched ${result.alerted} alert group(s)`
            : 'Evaluation complete; no alert was delivered',
        )
        await load(days)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Alert evaluation failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-fg">Error feed</h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Grouped by sanitized route, release, and error class. No messages, stacks,
            prompts, emails, tokens, or document content are captured. Masked replay only.
          </p>
        </div>
        <div className="flex items-center gap-1 rounded-[var(--radius-md)] border border-line p-0.5">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setDays(range)}
              aria-pressed={days === range}
              className={
                days === range
                  ? 'rounded-[var(--radius-sm)] bg-accent px-2.5 py-1 text-[11px] font-semibold text-accent-fg'
                  : 'rounded-[var(--radius-sm)] px-2.5 py-1 text-[11px] font-medium text-fg-2 hover:bg-surface-2'
              }
            >
              {range}d
            </button>
          ))}
        </div>
      </div>

      {loading && <div className="mt-4 text-xs text-fg-3">Loading aggregate errors...</div>}
      {error && !loading && (
        <div className="mt-4 rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-xs text-err">
          {error}
        </div>
      )}

      {data && !loading && !error && (
        <>
          <dl className="mt-4 grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-[var(--radius-md)] border border-line px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-fg-3">Events</dt>
              <dd className="mt-0.5 font-semibold text-fg">{formatNumber(data.totals.events)}</dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-fg-3">Visible groups</dt>
              <dd className="mt-0.5 font-semibold text-fg">{formatNumber(data.totals.visible_groups)}</dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-fg-3">Suppressed</dt>
              <dd className="mt-0.5 font-semibold text-fg">{formatNumber(data.totals.suppressed_groups)}</dd>
            </div>
            <div className="rounded-[var(--radius-md)] border border-line px-3 py-2">
              <dt className="text-[10px] uppercase tracking-wider text-fg-3">Alert delivery</dt>
              <dd className="mt-0.5 font-semibold text-fg">
                {data.delivery.configured
                  ? data.delivery.channels.join(', ')
                  : 'Not configured'}
              </dd>
            </div>
          </dl>

          <p className="mt-3 text-[11px] leading-relaxed text-fg-3">
            Threshold: {data.threshold.occurrences} occurrences in{' '}
            {data.threshold.window_minutes} minutes, at most one alert per group every{' '}
            {data.threshold.cooldown_minutes} minutes. {formatNumber(data.totals.suppressed_groups)}{' '}
            group(s) with fewer than {data.suppression.minimum_cohort_size} occurrences are
            suppressed. No per-user rows.
          </p>
          <p className="mt-1 text-[11px] text-fg-3">
            <a
              href={data.runbook_url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-accent hover:underline"
            >
              Open the error alert runbook
            </a>
          </p>

          <div className="mt-4 overflow-x-auto">
            {data.groups.length === 0 ? (
              <div className="rounded-[var(--radius-md)] border border-dashed border-line px-4 py-8 text-center text-xs text-fg-3">
                No aggregate error group meets the five-occurrence visibility policy in this range.
              </div>
            ) : (
              <table className="w-full min-w-[720px] text-left text-xs">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                    <th scope="col" className="py-2 pr-3 font-semibold">Source</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">Class</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">Route</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">Release</th>
                    <th scope="col" className="py-2 pr-3 text-right font-semibold">Events</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">Last seen</th>
                    <th scope="col" className="py-2 pr-3 font-semibold">Alerts</th>
                    <th scope="col" className="py-2 font-semibold">PostHog</th>
                  </tr>
                </thead>
                <tbody>
                  {data.groups.map((group) => (
                    <tr key={group.id} className="border-b border-line/60 align-top last:border-b-0">
                      <td className="py-2 pr-3"><SourceBadge source={group.source} /></td>
                      <td className="py-2 pr-3 font-medium text-fg">{group.error_class}</td>
                      <td className="py-2 pr-3 font-mono text-[11px] text-fg-2">{group.route}</td>
                      <td className="py-2 pr-3 font-mono text-[11px] text-fg-2">{group.release}</td>
                      <td className="py-2 pr-3 text-right font-semibold text-fg">
                        {formatNumber(group.occurrence_count)}
                      </td>
                      <td className="py-2 pr-3 text-[11px] text-fg-3">
                        {formatTimestamp(group.last_seen_at)}
                      </td>
                      <td className="py-2 pr-3 text-[11px] text-fg-3">
                        {group.last_alerted_at
                          ? `${formatNumber(group.alert_count)} sent`
                          : 'None'}
                      </td>
                      <td className="py-2"><LinkCell group={group} config={config} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-surface-2/40 p-3">
            <p className="text-[11px] font-semibold text-fg-2">Evaluate threshold alerts</p>
            <p className="mt-1 text-[11px] text-fg-3">
              Preview is read-only. Dispatch requires a reason and confirmation, sends only
              aggregate metadata to the configured Slack/email channel, and is audited.
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <label className="min-w-[16rem] flex-1 text-[11px] text-fg-3">
                Reason
                <input
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  maxLength={1000}
                  placeholder="Why are you evaluating alerts?"
                  className="mt-1 w-full rounded-[var(--radius-sm)] border border-line bg-surface px-2 py-1.5 text-xs text-fg"
                />
              </label>
              <label className="flex items-center gap-2 text-[11px] text-fg-2">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                Confirm dispatch
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() => void evaluate(true)}
                className="rounded-[var(--radius-sm)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50"
              >
                Preview
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void evaluate(false)}
                className="rounded-[var(--radius-sm)] bg-accent px-3 py-1.5 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
              >
                Dispatch alerts
              </button>
            </div>
            {evaluation && (
              <p className="mt-2 text-[11px] text-fg-3">
                {evaluation.dry_run ? 'Preview' : 'Evaluation'}: {evaluation.candidate_count}{' '}
                candidate(s), {evaluation.selected_count} selected,{' '}
                {evaluation.skipped_cooldown} skipped by cooldown, {evaluation.alerted}{' '}
                delivered.{' '}
                {!evaluation.delivery_configured &&
                  'No Slack or email channel is configured, so nothing is marked as alerted.'}
              </p>
            )}
          </div>
        </>
      )}
    </section>
  )
}
