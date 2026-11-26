'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminCollaborationActivity,
  type AdminCollaborationCohortRow,
  type AdminCollaborationResponse,
  type AdminCollaborationTenantRow,
} from '@/lib/api-client'

const RANGES = [7, 30, 90, 180] as const
const numberFormatter = new Intl.NumberFormat('en-IN')

function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(Number(value ?? 0))
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}%`
}

function formatHours(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)}h`
}

function MetricCard({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="bg-surface px-4 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fg-3">{label}</p>
      <p className="mt-1 text-lg font-semibold text-fg">{value}</p>
      <p className="mt-0.5 text-[10px] leading-relaxed text-fg-3">{detail}</p>
    </div>
  )
}

function RateCell({
  value,
  numerator,
  denominator,
  label,
}: {
  value: number | null
  numerator: number
  denominator: number
  label: string
}) {
  return (
    <span>
      <span className="block text-xs text-fg">{formatPercent(value)}</span>
      <span className="mt-0.5 block text-[10px] text-fg-3">
        {formatNumber(numerator)} / {formatNumber(denominator)} {label}
      </span>
    </span>
  )
}

function ActivityCells({ activity }: { activity: AdminCollaborationActivity }) {
  return (
    <>
      <td className="px-3 py-3 text-right text-xs text-fg">
        {formatNumber(activity.comments.total)}
        <span className="mt-0.5 block text-[10px] text-fg-3">
          {formatNumber(activity.comments.resolved)} resolved
        </span>
      </td>
      <td className="px-3 py-3 text-right text-xs text-fg">
        <RateCell
          value={activity.comments.resolution_rate}
          numerator={activity.comments.resolved}
          denominator={activity.comments.resolution_denominator}
          label="created"
        />
      </td>
      <td className="px-3 py-3 text-right text-xs text-fg">
        {formatNumber(activity.mentions.delivered)}
        <span className="mt-0.5 block text-[10px] text-fg-3">
          of {formatNumber(activity.mentions.total)} · {formatPercent(activity.mentions.delivery_rate)}
        </span>
      </td>
      <td className="px-3 py-3 text-right text-xs text-fg">
        {formatNumber(activity.review_comments.total)}
        <span className="mt-0.5 block text-[10px] text-fg-3">
          {formatNumber(activity.review_comments.distinct_reviewers)} reviewers
        </span>
      </td>
      <td className="px-3 py-3 text-right text-xs text-fg">
        {formatNumber(activity.review_links.opens)}
        <span className="mt-0.5 block text-[10px] text-fg-3">
          {formatNumber(activity.review_links.distinct_links_opened)} links
        </span>
      </td>
      <td className="px-3 py-3 text-right text-xs text-fg">
        {formatHours(activity.time_to_first_review.median_hours)}
        <span className="mt-0.5 block text-[10px] text-fg-3">
          {formatNumber(activity.time_to_first_review.reviewed_submissions)} /{' '}
          {formatNumber(activity.time_to_first_review.denominator)} submissions
        </span>
      </td>
    </>
  )
}

function SuppressedCells({ columnCount, reason }: { columnCount: number; reason: string }) {
  return (
    <td colSpan={columnCount} className="px-3 py-3 text-xs text-fg-3">
      Hidden: {reason === 'fewer_than_minimum_members' ? 'fewer than five members' : reason}
    </td>
  )
}

function TenantTable({
  rows,
  selectedTenantId,
  onSelect,
}: {
  rows: AdminCollaborationTenantRow[]
  selectedTenantId: string | null
  onSelect: (tenantId: string) => void
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1120px] border-collapse text-sm">
        <caption className="sr-only">
          Collaboration usage by tenant; activity counts are limited to the selected date range
        </caption>
        <thead>
          <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
            <th scope="col" className="px-5 py-3 text-left font-semibold">Tenant</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Members</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Cohorts</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Comments</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Resolution</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Mentions delivered</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Review comments</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Review opens</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Median first review</th>
            <th scope="col" className="px-5 py-3 text-right font-semibold">Drill-down</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={row.tenant_id}
              className={`border-t border-line align-top ${
                selectedTenantId === row.tenant_id ? 'bg-surface-2/60' : ''
              }`}
            >
              <td className="px-5 py-3">
                <p className="text-xs font-medium text-fg">{row.name}</p>
                <p className="mt-0.5 text-[10px] text-fg-3">
                  {row.slug} · {row.plan_id} · {row.active ? 'active' : 'inactive'}
                </p>
              </td>
              {row.suppressed ? (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">Hidden</td>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <SuppressedCells columnCount={6} reason={row.suppression_reason ?? 'suppressed'} />
                  <td className="px-5 py-3 text-right">
                    <span className="text-[10px] text-fg-3">Fewer than 5 members</span>
                  </td>
                </>
              ) : row.activity ? (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg">
                    {formatNumber(row.member_count)}
                    <span className="mt-0.5 block text-[10px] text-fg-3">
                      {formatNumber(row.cohort_member_count)} cohort members
                    </span>
                  </td>
                  <td className="px-3 py-3 text-right text-xs text-fg">
                    {formatNumber(row.cohort_count)}
                    <span className="mt-0.5 block text-[10px] text-fg-3">
                      {formatNumber(row.submitted_resume_count)} submissions
                    </span>
                  </td>
                  <ActivityCells activity={row.activity} />
                  <td className="px-5 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => onSelect(row.tenant_id)}
                      aria-pressed={selectedTenantId === row.tenant_id}
                      className="min-h-[32px] rounded border border-line px-2.5 py-1 text-[11px] font-medium text-fg-2 hover:bg-surface-2"
                    >
                      {selectedTenantId === row.tenant_id ? 'Showing' : 'Cohorts'}
                    </button>
                  </td>
                </>
              ) : (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <SuppressedCells columnCount={6} reason="no activity" />
                  <td className="px-5 py-3 text-right" />
                </>
              )}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={10} className="px-5 py-8 text-center text-sm text-fg-3">
                No tenants are registered.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

function CohortTable({ rows }: { rows: AdminCollaborationCohortRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1040px] border-collapse text-sm">
        <caption className="sr-only">Tenant cohort collaboration activity in the selected date range</caption>
        <thead>
          <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
            <th scope="col" className="px-5 py-3 text-left font-semibold">Cohort</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Members</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Submissions</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Comments</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Resolution</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Mentions delivered</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Review comments</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Review opens</th>
            <th scope="col" className="px-3 py-3 text-right font-semibold">Median first review</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.cohort_id} className="border-t border-line align-top">
              <td className="px-5 py-3 text-xs font-medium text-fg">{row.name}</td>
              {row.suppressed ? (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">Hidden</td>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <SuppressedCells columnCount={6} reason={row.suppression_reason ?? 'suppressed'} />
                </>
              ) : row.activity ? (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg">{formatNumber(row.member_count)}</td>
                  <td className="px-3 py-3 text-right text-xs text-fg">{formatNumber(row.submission_count)}</td>
                  <ActivityCells activity={row.activity} />
                </>
              ) : (
                <>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <td className="px-3 py-3 text-right text-xs text-fg-3">—</td>
                  <SuppressedCells columnCount={6} reason="no activity" />
                </>
              )}
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td colSpan={9} className="px-5 py-8 text-center text-sm text-fg-3">
                This tenant has no cohorts.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

export default function AdminCollaboration() {
  const [days, setDays] = useState(30)
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [applied, setApplied] = useState({ days: 30, from: '', to: '' })
  const [selectedTenantId, setSelectedTenantId] = useState<string | null>(null)
  const [data, setData] = useState<AdminCollaborationResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestGeneration = useRef(0)

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminCollaborationAnalytics({
        days: applied.days,
        start_date: applied.from || undefined,
        end_date: applied.to || undefined,
        tenant_id: selectedTenantId ?? undefined,
      })
      if (generation === requestGeneration.current) setData(next)
    } catch (err) {
      if (generation === requestGeneration.current) {
        setError(err instanceof Error ? err.message : String(err))
      }
    } finally {
      if (generation === requestGeneration.current) setLoading(false)
    }
  }, [applied, selectedTenantId])

  useEffect(() => {
    void load()
  }, [load])

  const applyPreset = (range: number) => {
    setDays(range)
    setFrom('')
    setTo('')
    setSelectedTenantId(null)
    setApplied({ days: range, from: '', to: '' })
  }

  const applyRange = () => {
    setSelectedTenantId(null)
    setApplied({ days, from, to })
  }

  const summary = data?.summary
  const selectedTenant = data?.selected_tenant ?? null

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-fg">Collaboration and tenant cohorts</h2>
            <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
              Comments, resolutions, mentions, review-link activity and time-to-first-review by tenant and cohort.
              Aggregate counts only. Comment text, reviewer identities, emails and document content are never
              returned, and groups below {formatNumber(data?.minimum_group_size ?? 5)} members are hidden.
            </p>
          </div>
          <span className="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-[10px] font-semibold text-fg-3">
            {data ? `${data.start_date} → ${data.end_date} UTC` : 'Loading window…'}
          </span>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-3">
          <div role="group" aria-label="Collaboration date range" className="flex flex-wrap gap-1">
            {RANGES.map((range) => {
              const active = !applied.from && !applied.to && applied.days === range
              return (
                <button
                  key={range}
                  type="button"
                  aria-pressed={active}
                  onClick={() => applyPreset(range)}
                  className={`min-h-[36px] rounded border px-3 py-1.5 text-xs font-medium ${
                    active ? 'border-accent text-accent-strong' : 'border-line text-fg-2 hover:bg-surface-2'
                  }`}
                >
                  {range}d
                </button>
              )
            })}
          </div>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            From
            <input
              type="date"
              aria-label="Collaboration start date"
              value={from}
              onChange={(event) => setFrom(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">
            To
            <input
              type="date"
              aria-label="Collaboration end date"
              value={to}
              onChange={(event) => setTo(event.target.value)}
              className="mt-1 block min-h-[36px] rounded border border-line bg-bg px-2 py-1.5 text-xs font-normal normal-case tracking-normal text-fg"
            />
          </label>
          <button
            type="button"
            onClick={applyRange}
            disabled={loading}
            className="min-h-[36px] rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            {loading ? 'Loading…' : 'Apply range'}
          </button>
          {selectedTenantId && (
            <button
              type="button"
              onClick={() => setSelectedTenantId(null)}
              className="min-h-[36px] rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
            >
              Clear tenant filter
            </button>
          )}
        </div>

        {error && (
          <p role="alert" className="mt-3 rounded border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">
            {error}
          </p>
        )}
      </div>

      {summary && data && (
        <>
          <div className="grid gap-px border-b border-line bg-line sm:grid-cols-2 xl:grid-cols-3">
            <MetricCard
              label="Comments"
              value={formatNumber(summary.comments.total)}
              detail={`${formatNumber(summary.comments.resolved)} resolved · ${formatPercent(
                summary.comments.resolution_rate,
              )} of ${formatNumber(summary.comments.resolution_denominator)} created`}
            />
            <MetricCard
              label="Distinct commenters"
              value={formatNumber(summary.comments.distinct_authors)}
              detail="Distinct authors with a comment in the range"
            />
            <MetricCard
              label="Mentions delivered"
              value={`${formatNumber(summary.mentions.delivered)} / ${formatNumber(summary.mentions.total)}`}
              detail={`${formatPercent(summary.mentions.delivery_rate)} delivery · ${formatNumber(
                summary.mentions.distinct_mentioned_users,
              )} distinct mentioned users`}
            />
            <MetricCard
              label="Review comments"
              value={formatNumber(summary.review_comments.total)}
              detail={`${formatNumber(summary.review_comments.distinct_reviewers)} distinct reviewers · ${formatNumber(
                summary.review_comments.distinct_review_links,
              )} review links`}
            />
            <MetricCard
              label="Review-link opens"
              value={formatNumber(summary.review_links.opens)}
              detail={`${formatNumber(summary.review_links.distinct_links_opened)} distinct review-capable links`}
            />
            <MetricCard
              label="Time to first review"
              value={formatHours(summary.time_to_first_review.median_hours)}
              detail={`${formatNumber(summary.time_to_first_review.reviewed_submissions)} reviewed of ${formatNumber(
                summary.time_to_first_review.denominator,
              )} cohort submissions · p90 ${formatHours(summary.time_to_first_review.p90_hours)}`}
            />
          </div>

          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
            <div>
              <h3 className="text-xs font-semibold text-fg">Tenants</h3>
              <p className="mt-0.5 text-[10px] text-fg-3">
                {formatNumber(data.reconciliation.visible_tenant_count)} visible ·{' '}
                {formatNumber(data.suppressed_tenants)} suppressed ·{' '}
                {formatNumber(data.reconciliation.tenant_member_count)} tenant member links
              </p>
            </div>
            <p className="text-[10px] text-fg-3">
              Visible {formatNumber(data.reconciliation.visible_tenant_member_count)} + hidden{' '}
              {formatNumber(data.reconciliation.suppressed_tenant_member_count)} ={' '}
              {formatNumber(data.reconciliation.tenant_member_count)} members
            </p>
          </div>

          <TenantTable
            rows={data.tenants}
            selectedTenantId={selectedTenantId}
            onSelect={(tenantId) =>
              setSelectedTenantId((current) => (current === tenantId ? null : tenantId))
            }
          />

          {selectedTenant && (
            <div className="border-t border-line">
              <div className="flex flex-wrap items-start justify-between gap-3 bg-surface-2/50 px-5 py-4">
                <div>
                  <h3 className="text-xs font-semibold text-fg">{selectedTenant.name}</h3>
                  <p className="mt-0.5 text-[10px] text-fg-3">
                    {selectedTenant.slug} · {selectedTenant.plan_id} ·{' '}
                    {selectedTenant.suppressed
                      ? 'suppressed tenant'
                      : `${formatNumber(selectedTenant.member_count)} members · ${formatNumber(
                          selectedTenant.cohort_count,
                        )} cohorts · ${formatNumber(
                          selectedTenant.cohort_member_count,
                        )} cohort member links · ${formatNumber(
                          selectedTenant.submitted_resume_count,
                        )} submissions`}
                  </p>
                </div>
                <span className="rounded-full border border-line bg-surface px-2.5 py-1 text-[10px] font-semibold text-fg-3">
                  Per-tenant drill-down
                </span>
              </div>
              {selectedTenant.suppressed ? (
                <p className="px-5 py-8 text-sm text-fg-3">
                  This tenant has fewer than {formatNumber(data.minimum_group_size)} members, so its collaboration
                  activity and cohort list are hidden.
                </p>
              ) : (
                <>
                  {selectedTenant.reconciliation && (
                    <div className="border-b border-line px-5 py-3 text-[10px] text-fg-3">
                      Reconciled: {formatNumber(selectedTenant.reconciliation.member_count)} members ·{' '}
                      {formatNumber(selectedTenant.reconciliation.cohort_member_count)} cohort member links
                      (visible {formatNumber(selectedTenant.reconciliation.visible_cohort_member_count)} + hidden{' '}
                      {formatNumber(selectedTenant.reconciliation.suppressed_cohort_member_count)}) ·{' '}
                      {formatNumber(selectedTenant.reconciliation.submitted_resume_count)} submissions
                    </div>
                  )}
                  <CohortTable rows={selectedTenant.cohorts} />
                  {selectedTenant.cohorts.every((row) => row.suppressed) &&
                    selectedTenant.cohorts.length > 0 && (
                      <p className="border-t border-line px-5 py-3 text-[10px] text-fg-3">
                        {formatNumber(selectedTenant.suppressed_cohort_count)} cohort
                        {selectedTenant.suppressed_cohort_count === 1 ? '' : 's'} hidden because they have fewer
                        than {formatNumber(data.minimum_group_size)} members.
                      </p>
                    )}
                </>
              )}
            </div>
          )}

          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-3 text-[10px] text-fg-3">
            <span>
              Time-to-first-review denominator = cohort submissions in range. Median and p90 use only reviewed
              submissions and are hidden below {formatNumber(data.minimum_group_size)} reviews.
            </span>
            <span>
              Source: collaboration and tenancy tables · aggregate only · no comment text or reviewer identity
            </span>
          </div>
        </>
      )}

      {!data && error && (
        <div className="px-5 py-10 text-center text-sm text-fg-3">
          Collaboration analytics are unavailable. Adjust the range or retry.
        </div>
      )}
      {!data && !error && (
        <div role="status" className="px-5 py-10 text-center text-sm text-fg-3">
          Loading collaboration analytics…
        </div>
      )}
    </section>
  )
}
