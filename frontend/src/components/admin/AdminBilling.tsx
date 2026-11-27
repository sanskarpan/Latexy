'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminBillingReconciliationList,
  type AdminBillingSummary,
  type AdminBillingWebhookList,
  type AdminRefundList,
} from '@/lib/api-client'
import AdminRevenueBreakdown from './AdminRevenueBreakdown'
import AdminCouponStudentPerformance from './AdminCouponStudentPerformance'
import AdminPlanHealth from './AdminPlanHealth'
import AdminTeamSeatUtilization from './AdminTeamSeatUtilization'
import { formatDateTime, formatMoney, formatNumber, shortId, summarize } from './admin-format'
import AdminCheckoutFunnel from './AdminCheckoutFunnel'

const RANGES = [7, 30, 90] as const
const PAGE_SIZE = 25
const PAYMENT_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

type AckFilter = 'all' | 'unacknowledged' | 'acknowledged'

function dateBoundary(value: string, endOfDay = false): string | undefined {
  if (!value) return undefined
  const parsed = new Date(`${value}T${endOfDay ? '23:59:59.999' : '00:00:00.000'}Z`)
  return Number.isNaN(parsed.getTime()) ? undefined : parsed.toISOString()
}

function Kpi({ label, value, detail, tone }: { label: string; value: string; detail?: string; tone?: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-fg-3">{label}</p>
      <p className={`mt-2 text-2xl font-semibold tracking-tight ${tone ?? 'text-fg'}`}>{value}</p>
      {detail && <p className="mt-1 text-[11px] leading-relaxed text-fg-3">{detail}</p>}
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'processed' || status === 'executed' || status === 'approved'
      ? 'border-ok/30 bg-ok/10 text-ok'
      : status === 'failed' || status === 'rejected'
        ? 'border-err/30 bg-err/10 text-err'
        : status === 'pending' || status === 'processing' || status === 'executing'
          ? 'border-warn/30 bg-warn/10 text-warn'
          : 'border-line bg-surface-2 text-fg-3'
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone}`}>
      {status}
    </span>
  )
}

function WebhookHealth({
  data,
  loading,
  filters,
  onFilters,
  offset,
  onOffset,
  actionId,
  note,
  replayConfirmed,
  onActionId,
  onNote,
  onReplayConfirmed,
  onReconcile,
  onReplay,
  onAcknowledge,
  busyId,
}: {
  data: AdminBillingWebhookList | null
  loading: boolean
  filters: {
    status: string
    acknowledged: AckFilter
    q: string
    receivedAfter: string
    receivedBefore: string
    deadLetter: boolean
  }
  onFilters: (next: {
    status: string
    acknowledged: AckFilter
    q: string
    receivedAfter: string
    receivedBefore: string
    deadLetter: boolean
  }) => void
  offset: number
  onOffset: (next: number) => void
  actionId: string | null
  note: string
  replayConfirmed: boolean
  onActionId: (id: string | null) => void
  onNote: (value: string) => void
  onReplayConfirmed: (value: boolean) => void
  onReconcile: (id: string) => void
  onReplay: (id: string) => void
  onAcknowledge: (id: string, quick?: boolean) => void
  busyId: string | null
}) {
  const [draftQuery, setDraftQuery] = useState(filters.q)
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  return (
    <section id="admin-billing-webhooks" className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Dodo webhook health</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Durable receipts for signed provider events. Acknowledge a provider-side dead letter only after review;
              replay re-fetches the provider resource and runs the normal idempotent billing handler. Raw signatures and
              payloads are never stored or shown here.
            </p>
          </div>
          <a
            href="https://app.dodopayments.com/developer/webhooks"
            target="_blank"
            rel="noreferrer"
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Open Dodo webhook logs
          </a>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <select
            aria-label="Webhook status"
            value={filters.status}
            onChange={(event) => onFilters({ ...filters, status: event.target.value })}
            className="min-h-[38px] rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="all">All statuses</option>
            <option value="failed">Failed / dead letter</option>
            <option value="processed">Processed</option>
            <option value="processing">Processing</option>
          </select>
          <select
            aria-label="Webhook acknowledgement"
            value={filters.acknowledged}
            onChange={(event) => onFilters({ ...filters, acknowledged: event.target.value as AckFilter })}
            className="min-h-[38px] rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg"
          >
            <option value="unacknowledged">Unacknowledged</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="all">All</option>
          </select>
          <label className="flex min-h-[38px] items-center gap-2 rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg-2">
            <input
              type="checkbox"
              checked={filters.deadLetter}
              onChange={(event) => onFilters({ ...filters, deadLetter: event.target.checked })}
            />
            Dead letters only
          </label>
          <label className="flex items-center gap-1.5 text-[11px] text-fg-3">
            Received after
            <input
              type="date"
              value={filters.receivedAfter}
              max={filters.receivedBefore || undefined}
              onChange={(event) => onFilters({ ...filters, receivedAfter: event.target.value })}
              className="min-h-[38px] rounded-md border border-line bg-bg px-2 py-1 text-xs text-fg"
            />
          </label>
          <label className="flex items-center gap-1.5 text-[11px] text-fg-3">
            Received before
            <input
              type="date"
              value={filters.receivedBefore}
              min={filters.receivedAfter || undefined}
              onChange={(event) => onFilters({ ...filters, receivedBefore: event.target.value })}
              className="min-h-[38px] rounded-md border border-line bg-bg px-2 py-1 text-xs text-fg"
            />
          </label>
          <form
            className="flex min-w-48 flex-1 gap-2"
            onSubmit={(event) => {
              event.preventDefault()
              onFilters({ ...filters, q: draftQuery.trim() })
            }}
          >
            <input
              type="search"
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="Event, resource, or error…"
              aria-label="Search webhooks"
              className="min-h-[38px] min-w-0 flex-1 rounded-md border border-line bg-bg px-3 py-1.5 text-xs text-fg"
            />
            <button type="submit" className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
              Search
            </button>
          </form>
        </div>
      </div>
      {loading && !data ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <p className="px-5 py-12 text-center text-sm text-fg-3">No webhook events match these filters.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse text-sm">
            <caption className="sr-only">Billing webhook events, newest first</caption>
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-4 py-3 text-left font-semibold">Received</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Event</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Status</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Local ledger</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Attempts</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Review</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                const isOpen = actionId === row.id
                return (
                  <tr key={row.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-fg-3">{formatDateTime(row.received_at)}</td>
                    <td className="px-4 py-3">
                      <p className="font-mono text-xs text-fg">{row.event_type}</p>
                      <p className="mt-1 font-mono text-[10px] text-fg-3">{shortId(row.event_resource_id, 22)}</p>
                      <p className="mt-0.5 font-mono text-[10px] text-fg-3">{row.event_id}</p>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={row.status} />
                      {row.acknowledged_at && (
                        <p className="mt-1 text-[10px] text-fg-3">Acknowledged {formatDateTime(row.acknowledged_at)}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-3">
                      {row.local_link.linked ? (
                        <span className="font-mono text-ok">{row.local_link.local_type} linked</span>
                      ) : (
                        <span className="text-warn">No local intent</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-3">
                      <p>{row.attempts}</p>
                      <p className="mt-0.5 text-[10px]">reconcile: {row.reconcile_attempts}</p>
                    </td>
                    <td className="max-w-[340px] px-4 py-3">
                      {row.last_error ? (
                        <p className="text-[11px] leading-relaxed text-err/90">{summarize(row.last_error, 120)}</p>
                      ) : (
                        <p className="text-[11px] text-fg-3">—</p>
                      )}
                      {row.acknowledgement_note && (
                        <p className="mt-1 text-[10px] leading-relaxed text-fg-3">Ack: {row.acknowledgement_note}</p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {row.status !== 'processed' && (
                          <button
                            type="button"
                            onClick={() => onActionId(isOpen ? null : row.id)}
                            className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
                          >
                            {isOpen ? 'Cancel' : 'Review'}
                          </button>
                        )}
                        {!row.acknowledged_at && row.status === 'failed' && (
                          <button
                            type="button"
                            onClick={() => onAcknowledge(row.id, true)}
                            disabled={Boolean(busyId)}
                            className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                          >
                            Quick ack
                          </button>
                        )}
                      </div>
                      {isOpen && (
                        <div className="mt-2 space-y-2 rounded-md border border-line bg-surface-2/60 p-2">
                          <label className="block text-[10px] font-medium text-fg-2">
                            Review reason
                            <input
                              value={note}
                              onChange={(event) => onNote(event.target.value)}
                              maxLength={1000}
                              placeholder="What did you verify?"
                              className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-xs text-fg"
                            />
                          </label>
                          <label className="flex items-start gap-2 text-[10px] leading-relaxed text-fg-3">
                            <input
                              type="checkbox"
                              checked={replayConfirmed}
                              onChange={(event) => onReplayConfirmed(event.target.checked)}
                              className="mt-0.5"
                            />
                            I confirm this replay re-reads the provider resource and is audited against my admin account.
                          </label>
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              type="button"
                              onClick={() => onReplay(row.id)}
                              disabled={Boolean(busyId) || !note.trim() || !replayConfirmed || !row.event_resource_id}
                              className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                            >
                              Replay from provider
                            </button>
                            <button
                              type="button"
                              onClick={() => onReconcile(row.id)}
                              disabled={Boolean(busyId) || !note.trim()}
                              className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 disabled:opacity-40"
                            >
                              Reconcile from Dodo
                            </button>
                            {row.status === 'failed' && (
                              <button
                                type="button"
                                onClick={() => onAcknowledge(row.id)}
                                disabled={Boolean(busyId) || !note.trim()}
                                className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 disabled:opacity-40"
                              >
                                Acknowledge
                              </button>
                            )}
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-fg-3">
        <span>
          {formatNumber(data?.total ?? 0)} events · page {page} of {pageCount}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))}
            disabled={offset === 0}
            className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => onOffset(offset + PAGE_SIZE)}
            disabled={offset + PAGE_SIZE >= (data?.total ?? 0)}
            className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </section>
  )
}

function RefundQueue({
  data,
  loading,
  offset,
  onOffset,
  actionId,
  note,
  onActionId,
  onNote,
  onDecision,
  onExecute,
  onReconcile,
  busyId,
}: {
  data: AdminRefundList | null
  loading: boolean
  offset: number
  onOffset: (next: number) => void
  actionId: string | null
  note: string
  onActionId: (id: string | null) => void
  onNote: (value: string) => void
  onDecision: (id: string, decision: 'approve' | 'reject') => void
  onExecute: (id: string) => void
  onReconcile: (id: string) => void
  busyId: string | null
}) {
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Refund and goodwill approval queue</h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
          Refunds and goodwill compensation both require a different admin to approve. Execution never happens
          automatically; the provider webhook remains the authoritative settlement record.
        </p>
      </div>
      {loading && !data ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-fg-3">No refund requests yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-sm">
            <caption className="sr-only">Refund requests, newest first</caption>
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-4 py-3 text-left font-semibold">Requested</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Status</th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">Amount</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Payment</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Reason / decision</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                const isOpen = actionId === row.id
                const awaitingDecision = row.status === 'pending'
                const executable = row.status === 'approved'
                const failed = row.status === 'failed'
                const reconcilable = (row.status === 'executing' || failed) && Boolean(row.provider_refund_id)
                return (
                  <tr key={row.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-fg-3">
                      {formatDateTime(row.requested_at)}
                      {row.requested_email && <p className="mt-1 text-[10px]">{row.requested_email}</p>}
                    </td>
                    <td className="px-4 py-3"><StatusBadge status={row.status} /></td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-xs font-semibold text-fg">
                      {row.amount == null ? 'Full payment' : formatMoney(row.amount / 100, row.currency || 'INR')}
                    </td>
                    <td className="px-4 py-3 font-mono text-[10px] text-fg-3">{shortId(row.payment_id, 14)}</td>
                    <td className="max-w-[320px] px-4 py-3 text-xs text-fg-3">
                      {row.request_kind === 'goodwill' && (
                        <span className="mb-1 inline-flex rounded border border-warn/30 bg-warn/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-warn">
                          Goodwill
                        </span>
                      )}
                      <p>{summarize(row.reason, 160)}</p>
                      {row.evidence && <p className="mt-1 text-[10px] text-fg-2">Evidence: {summarize(row.evidence, 120)}</p>}
                      {row.decision_note && <p className="mt-1 text-[10px]">Decision: {summarize(row.decision_note, 120)}</p>}
                      {row.last_error && <p className="mt-1 text-[10px] text-err">{summarize(row.last_error, 120)}</p>}
                      {row.provider_refund_id && <p className="mt-1 font-mono text-[10px] text-ok">{row.provider_refund_id}</p>}
                    </td>
                    <td className="px-4 py-3">
                      {(awaitingDecision || executable || failed || reconcilable) && (
                        <button
                          type="button"
                          onClick={() => onActionId(isOpen ? null : row.id)}
                          disabled={Boolean(busyId)}
                          className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                        >
                          {isOpen ? 'Cancel' : 'Review'}
                        </button>
                      )}
                      {isOpen && (awaitingDecision || executable || failed || reconcilable) && (
                        <div className="mt-2 space-y-2 rounded-md border border-line bg-surface-2/60 p-2">
                          <label className="block text-[10px] font-medium text-fg-2">
                            Note
                            <input
                              value={note}
                              onChange={(event) => onNote(event.target.value)}
                              maxLength={1000}
                              className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-xs text-fg"
                            />
                          </label>
                          {awaitingDecision ? (
                            <div className="flex flex-wrap gap-1.5">
                              <button
                                type="button"
                                onClick={() => onDecision(row.id, 'approve')}
                                disabled={Boolean(busyId) || !note.trim()}
                                className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                onClick={() => onDecision(row.id, 'reject')}
                                disabled={Boolean(busyId) || !note.trim()}
                                className="rounded border border-err/30 px-2 py-1 text-[10px] font-medium text-err disabled:opacity-40"
                              >
                                Reject
                              </button>
                            </div>
                          ) : executable ? (
                            <button
                              type="button"
                              onClick={() => onExecute(row.id)}
                              disabled={Boolean(busyId)}
                              className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                            >
                              Execute refund
                            </button>
                          ) : (
                            <>
                              {failed ? (
                                <p className="text-[10px] leading-relaxed text-warn">
                                  Provider execution failed. Reconcile this refund with Dodo before any new attempt; do not resubmit.
                                </p>
                              ) : (
                                <p className="text-[10px] leading-relaxed text-warn">
                                  Provider settlement is still pending. Re-read the authoritative refund from Dodo; do not resubmit.
                                </p>
                              )}
                              {reconcilable && (
                                <button
                                  type="button"
                                  onClick={() => onReconcile(row.id)}
                                  disabled={Boolean(busyId) || !note.trim()}
                                  className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                                >
                                  Reconcile with Dodo
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-fg-3">
        <span>{formatNumber(data?.total ?? 0)} requests · page {page} of {pageCount}</span>
        <div className="flex gap-2">
          <button type="button" onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} className="rounded border border-line px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
          <button type="button" onClick={() => onOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= (data?.total ?? 0)} className="rounded border border-line px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
        </div>
      </div>
    </section>
  )
}

function ReconciliationQueue({
  data,
  loading,
  offset,
  onOffset,
  actionId,
  note,
  confirmed,
  onActionId,
  onNote,
  onConfirmed,
  onAcknowledge,
  onReplay,
  busyId,
}: {
  data: AdminBillingReconciliationList | null
  loading: boolean
  offset: number
  onOffset: (next: number) => void
  actionId: string | null
  note: string
  confirmed: boolean
  onActionId: (id: string | null) => void
  onNote: (value: string) => void
  onConfirmed: (value: boolean) => void
  onAcknowledge: (id: string) => void
  onReplay: (id: string) => void
  busyId: string | null
}) {
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  return (
    <section id="admin-billing-reconciliation" className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Reconciliation queue</h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
          One row per unresolved failed webhook, joined to its local payment, subscription, or refund intent. Replay
          re-reads the provider resource through the idempotent handler; acknowledge only after review. Resolved rows
          disappear from this queue.
        </p>
      </div>
      {loading && !data ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="h-12 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      ) : !data || data.items.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-fg-3">No unresolved billing reconciliation items.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[1020px] border-collapse text-sm">
            <caption className="sr-only">Unresolved failed webhooks, newest first</caption>
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-4 py-3 text-left font-semibold">Received / age</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Event</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Mismatch</th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">Amount</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Local intent</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => {
                const isOpen = actionId === row.id
                return (
                  <tr key={row.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-fg-3">
                      {formatDateTime(row.received_at)}
                      <p className="mt-1 text-[10px]">
                        {row.age_hours == null ? '—' : `${formatNumber(row.age_hours)} h old`}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <p className="font-mono text-xs text-fg">{row.event_type}</p>
                      <p className="mt-1 font-mono text-[10px] text-fg-3">{shortId(row.event_resource_id, 22)}</p>
                    </td>
                    <td className="max-w-[360px] px-4 py-3 text-xs text-fg-3">
                      <p className="leading-relaxed text-warn">{row.mismatch_reason}</p>
                      {row.last_error && <p className="mt-1 text-[10px] text-err/90">{summarize(row.last_error, 140)}</p>}
                      <p className="mt-1 text-[10px]">{row.suggested_action}</p>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-right text-xs font-semibold text-fg">
                      {row.amount_minor == null ? '—' : formatMoney(row.amount_minor / 100, row.currency || 'INR')}
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-3">
                      {row.local_link.linked ? (
                        <>
                          <p className="font-mono text-ok">{row.local_link.local_type}</p>
                          <p className="mt-1 font-mono text-[10px]">{shortId(row.local_link.local_id, 18)}</p>
                          {row.link_status && <p className="mt-1 text-[10px]">status: {row.link_status}</p>}
                        </>
                      ) : (
                        <span className="text-warn">No local intent</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => onActionId(isOpen ? null : row.id)}
                        className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
                      >
                        {isOpen ? 'Cancel' : 'Review'}
                      </button>
                      {isOpen && (
                        <div className="mt-2 w-[260px] space-y-2 rounded-md border border-line bg-surface-2/60 p-2">
                          <label className="block text-[10px] font-medium text-fg-2">
                            Reason
                            <input
                              value={note}
                              onChange={(event) => onNote(event.target.value)}
                              maxLength={1000}
                              placeholder="What did you verify?"
                              className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-xs text-fg"
                            />
                          </label>
                          <label className="flex items-start gap-2 text-[10px] leading-relaxed text-fg-3">
                            <input
                              type="checkbox"
                              checked={confirmed}
                              onChange={(event) => onConfirmed(event.target.checked)}
                              className="mt-0.5"
                            />
                            Confirm replay against the provider and audit log.
                          </label>
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              type="button"
                              onClick={() => onReplay(row.id)}
                              disabled={Boolean(busyId) || !note.trim() || !confirmed || !row.can_replay}
                              className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                            >
                              Replay
                            </button>
                            <button
                              type="button"
                              onClick={() => onAcknowledge(row.id)}
                              disabled={Boolean(busyId) || !note.trim()}
                              className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 disabled:opacity-40"
                            >
                              Acknowledge
                            </button>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-fg-3">
        <span>
          {formatNumber(data?.total ?? 0)} unresolved · page {page} of {pageCount}
        </span>
        <div className="flex gap-2">
          <button type="button" onClick={() => onOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} className="rounded border border-line px-3 py-1.5 font-medium disabled:opacity-40">Previous</button>
          <button type="button" onClick={() => onOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= (data?.total ?? 0)} className="rounded border border-line px-3 py-1.5 font-medium disabled:opacity-40">Next</button>
        </div>
      </div>
    </section>
  )
}

export default function AdminBilling() {
  const [days, setDays] = useState<number>(30)
  const [granularity, setGranularity] = useState<'day' | 'month'>('day')
  const [windowStart, setWindowStart] = useState('')
  const [windowEnd, setWindowEnd] = useState('')
  const [summary, setSummary] = useState<AdminBillingSummary | null>(null)
  const [webhooks, setWebhooks] = useState<AdminBillingWebhookList | null>(null)
  const [reconciliation, setReconciliation] = useState<AdminBillingReconciliationList | null>(null)
  const [refunds, setRefunds] = useState<AdminRefundList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<{
    status: string
    acknowledged: AckFilter
    q: string
    receivedAfter: string
    receivedBefore: string
    deadLetter: boolean
  }>(() => {
    if (typeof window === 'undefined') {
      return {
        status: 'failed',
        acknowledged: 'unacknowledged',
        q: '',
        receivedAfter: '',
        receivedBefore: '',
        deadLetter: true,
      }
    }
    const params = new URLSearchParams(window.location.search)
    // Attention deep links use webhook_status; `status` is accepted too so
    // older bookmarks and hand-written links keep working.
    const requestedStatus = params.get('webhook_status') ?? params.get('status')
    const requestedAck = params.get('acknowledged')
    return {
      status: ['failed', 'processed', 'processing'].includes(requestedStatus ?? '')
        ? (requestedStatus as string)
        : 'failed',
      acknowledged: requestedAck === 'all' || requestedAck === 'acknowledged'
        ? (requestedAck as AckFilter)
        : 'unacknowledged',
      q: params.get('q')?.slice(0, 200) ?? '',
      receivedAfter: '',
      receivedBefore: '',
      deadLetter: true,
    }
  })
  const [attentionFilter] = useState<string | null>(() => {
    if (typeof window === 'undefined') return null
    const params = new URLSearchParams(window.location.search)
    const subscription = params.get('subscription_status')
    const payment = params.get('payment_status')
    if (subscription) return `subscriptions: ${subscription}`
    if (payment) return `payments: ${payment}`
    return null
  })
  const [webhookOffset, setWebhookOffset] = useState(0)
  const [reconciliationOffset, setReconciliationOffset] = useState(0)
  const [refundOffset, setRefundOffset] = useState(0)
  const [actionId, setActionId] = useState<string | null>(null)
  const [reconciliationActionId, setReconciliationActionId] = useState<string | null>(null)
  const [refundActionId, setRefundActionId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [replayConfirmed, setReplayConfirmed] = useState(false)
  const [reconciliationNote, setReconciliationNote] = useState('')
  const [reconciliationConfirmed, setReconciliationConfirmed] = useState(false)
  const [refundNote, setRefundNote] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [refundPaymentId, setRefundPaymentId] = useState('')
  const [refundKind, setRefundKind] = useState<'refund' | 'goodwill'>('refund')
  const [refundAmount, setRefundAmount] = useState('')
  const [refundItemId, setRefundItemId] = useState('')
  const [refundReason, setRefundReason] = useState('')
  const [refundEvidence, setRefundEvidence] = useState('')
  const requestGeneration = useRef(0)
  const busyRef = useRef(false)

  const acknowledged = filters.acknowledged === 'all' ? undefined : filters.acknowledged === 'acknowledged'
  const customWindow = Boolean(windowStart || windowEnd)

  const load = useCallback(async () => {
    const generation = ++requestGeneration.current
    setLoading(true)
    setError(null)
    const [summaryResult, webhookResult, reconciliationResult, refundResult] = await Promise.allSettled([
      apiClient.getAdminBillingSummary(days, {
        start: dateBoundary(windowStart),
        end: dateBoundary(windowEnd, true),
        granularity,
      }),
      apiClient.getAdminBillingWebhooks({
        status: filters.status === 'all' ? undefined : filters.status,
        acknowledged,
        received_after: dateBoundary(filters.receivedAfter),
        received_before: dateBoundary(filters.receivedBefore, true),
        dead_letter: filters.deadLetter,
        q: filters.q || undefined,
        limit: PAGE_SIZE,
        offset: webhookOffset,
      }),
      apiClient.getAdminBillingReconciliation({ limit: PAGE_SIZE, offset: reconciliationOffset }),
      apiClient.getAdminRefundRequests({ limit: PAGE_SIZE, offset: refundOffset }),
    ])
    if (requestGeneration.current !== generation) return
    const failures: string[] = []
    if (summaryResult.status === 'fulfilled') setSummary(summaryResult.value)
    else failures.push('summary')
    if (webhookResult.status === 'fulfilled') setWebhooks(webhookResult.value)
    else failures.push('webhooks')
    if (reconciliationResult.status === 'fulfilled') setReconciliation(reconciliationResult.value)
    else failures.push('reconciliation queue')
    if (refundResult.status === 'fulfilled') setRefunds(refundResult.value)
    else failures.push('refund queue')
    if (failures.length) {
      setError(`Could not load ${failures.join(', ')}. Other sections show their last successful data.`)
    }
    setLoading(false)
  }, [
    acknowledged,
    days,
    filters.deadLetter,
    filters.q,
    filters.receivedAfter,
    filters.receivedBefore,
    filters.status,
    granularity,
    reconciliationOffset,
    refundOffset,
    webhookOffset,
    windowEnd,
    windowStart,
  ])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const beginBusy = (id: string): boolean => {
    if (busyRef.current) return false
    busyRef.current = true
    setBusyId(id)
    return true
  }

  const endBusy = () => {
    busyRef.current = false
    setBusyId(null)
  }

  const reconcile = async (id: string) => {
    if (!note.trim() || !beginBusy(id)) return
    try {
      const result = await apiClient.reconcileAdminWebhook(id, note.trim())
      toast.success(result.message || 'Provider state reconciled')
      setActionId(null)
      setNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Reconciliation failed')
    } finally {
      endBusy()
    }
  }

  const acknowledge = async (id: string, quick = false) => {
    // Quick ack must never reuse another row's editable note.
    const effectiveNote = quick
      ? 'Quick acknowledgement from the billing control room'
      : note.trim()
    if (!effectiveNote || !beginBusy(id)) return
    try {
      await apiClient.acknowledgeAdminWebhook(id, effectiveNote)
      toast.success('Webhook acknowledged')
      setActionId(null)
      setNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Acknowledgement failed')
    } finally {
      endBusy()
    }
  }

  const replay = async (id: string) => {
    if (!note.trim() || !replayConfirmed || !beginBusy(id)) return
    try {
      const result = await apiClient.replayAdminWebhook(id, note.trim(), true)
      if (result.replayed) toast.success(result.message || 'Provider resource replayed')
      else toast.message(result.message || 'Event was already processed')
      setActionId(null)
      setNote('')
      setReplayConfirmed(false)
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Replay failed')
    } finally {
      endBusy()
    }
  }

  const acknowledgeReconciliation = async (id: string) => {
    if (!reconciliationNote.trim() || !beginBusy(id)) return
    try {
      await apiClient.acknowledgeAdminReconciliation(id, reconciliationNote.trim())
      toast.success('Reconciliation item acknowledged')
      setReconciliationActionId(null)
      setReconciliationNote('')
      setReconciliationConfirmed(false)
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Acknowledgement failed')
    } finally {
      endBusy()
    }
  }

  const replayReconciliation = async (id: string) => {
    if (!reconciliationNote.trim() || !reconciliationConfirmed || !beginBusy(id)) return
    try {
      const result = await apiClient.replayAdminReconciliation(id, reconciliationNote.trim(), true)
      if (result.replayed) toast.success(result.message || 'Provider resource replayed')
      else toast.message(result.message || 'Event was already processed')
      setReconciliationActionId(null)
      setReconciliationNote('')
      setReconciliationConfirmed(false)
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Replay failed')
    } finally {
      endBusy()
    }
  }

  const decideRefund = async (id: string, decision: 'approve' | 'reject') => {
    if (!refundNote.trim() || !beginBusy(id)) return
    try {
      await apiClient.decideAdminRefund(id, decision, refundNote.trim())
      toast.success(decision === 'approve' ? 'Refund approved' : 'Refund rejected')
      setRefundActionId(null)
      setRefundNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund decision failed')
    } finally {
      endBusy()
    }
  }

  const executeRefund = async (id: string) => {
    if (!beginBusy(id)) return
    try {
      const updated = await apiClient.executeAdminRefund(id, refundNote.trim() || undefined)
      if (updated.status === 'executed' || updated.status === 'executing') {
        toast.success(updated.status === 'executing' ? 'Refund submission in progress' : 'Refund submitted to Dodo')
      } else {
        toast.error(updated.last_error || 'Refund execution failed')
      }
      setRefundActionId(null)
      setRefundNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund execution failed')
    } finally {
      endBusy()
    }
  }

  const reconcileRefund = async (id: string) => {
    if (!refundNote.trim() || !beginBusy(id)) return
    try {
      const updated = await apiClient.reconcileAdminRefund(id, refundNote.trim())
      if (updated.status === 'executed') {
        toast.success('Refund reconciled: Dodo reports it as succeeded')
      } else if (updated.status === 'executing') {
        toast.success('Refund reconciled: Dodo still reports it as pending')
      } else {
        toast.error(updated.last_error || 'Dodo reports the refund as failed')
      }
      setRefundActionId(null)
      setRefundNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund reconciliation failed')
    } finally {
      endBusy()
    }
  }

  const createRefund = async (event: React.FormEvent) => {
    event.preventDefault()
    const paymentReference = refundPaymentId.trim()
    if (!paymentReference || !refundReason.trim()) return
    const amount = refundAmount.trim() ? Number(refundAmount) : null
    if (amount !== null && (!Number.isInteger(amount) || amount <= 0)) {
      toast.error('Refund amount must be a positive whole number')
      return
    }
    if (amount === null && refundItemId.trim()) {
      toast.error('A full refund must not include a provider line-item ID')
      return
    }
    if (!beginBusy('create-refund')) return
    try {
      await apiClient.createAdminRefundRequest({
        ...(PAYMENT_UUID_RE.test(paymentReference)
          ? { payment_id: paymentReference }
          : { provider_payment_id: paymentReference }),
        request_kind: refundKind,
        amount,
        provider_item_id: refundItemId.trim() || null,
        reason: refundReason.trim(),
        evidence: refundEvidence.trim() || null,
      })
      toast.success(
        `${refundKind === 'goodwill' ? 'Goodwill' : 'Refund'} request created; a different admin must approve it`,
      )
      setShowCreate(false)
      setRefundPaymentId('')
      setRefundKind('refund')
      setRefundAmount('')
      setRefundItemId('')
      setRefundReason('')
      setRefundEvidence('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund request failed')
    } finally {
      endBusy()
    }
  }

  return (
    <div id="admin-billing" className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-fg">Revenue control room</h2>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Authoritative billing state from Postgres, with provider webhook review and an audited, dual-control refund
            workflow. Provider credentials and customer payment details are never shown here.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-[var(--radius-md)] border border-line bg-surface p-0.5" role="group" aria-label="Billing period">
            {RANGES.map((range) => (
              <button
                key={range}
                type="button"
                aria-pressed={!customWindow && days === range}
                onClick={() => { setDays(range); setWindowStart(''); setWindowEnd('') }}
                className={`rounded px-3 py-1.5 text-xs font-medium ${!customWindow && days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}
              >
                {range} days
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-fg-3">
            Window
            <input
              type="date"
              aria-label="Summary start date"
              value={windowStart}
              max={windowEnd || undefined}
              onChange={(event) => setWindowStart(event.target.value)}
              className="min-h-[38px] rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg"
            />
            <span>to</span>
            <input
              type="date"
              aria-label="Summary end date"
              value={windowEnd}
              min={windowStart || undefined}
              onChange={(event) => setWindowEnd(event.target.value)}
              className="min-h-[38px] rounded-md border border-line bg-surface px-2 py-1 text-xs text-fg"
            />
          </label>
          {customWindow && (
            <button type="button" onClick={() => { setWindowStart(''); setWindowEnd('') }} className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
              Clear window
            </button>
          )}
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading} className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-50">
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">
          {error}
        </div>
      )}

      {attentionFilter && (
        <div className="rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 px-4 py-3 text-xs text-warn">
          Attention filter · {attentionFilter}. Use the subscription and payment records below the KPI strip to review
          the affected accounts; no automatic retry or refund is performed.
        </div>
      )}

      <AdminCheckoutFunnel />

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Kpi
            label="MRR"
            value={formatMoney(summary.mrr, summary.currency)}
            detail={`ARR ${formatMoney(summary.arr, summary.currency)} · ${formatNumber(summary.mrr_minor)} minor`}
          />
          <Kpi
            label="ARPU"
            value={formatMoney(summary.arpu, summary.currency)}
            detail={`${formatNumber(summary.arpu_minor)} minor / ${formatNumber(summary.active_subscriptions)} active`}
          />
          <Kpi
            label="Active subscriptions"
            value={formatNumber(summary.active_subscriptions)}
            detail={`${formatNumber(summary.past_due_subscriptions)} past due`}
          />
          <Kpi
            label="Net revenue"
            value={formatMoney(summary.net_revenue, summary.currency)}
            detail={`${formatMoney(summary.refunded, summary.currency)} refunded`}
          />
          <Kpi
            label="Webhook failures"
            value={formatNumber(summary.unacknowledged_webhook_failures)}
            detail={`${formatNumber(summary.webhook_failures_24h)} in 24h · ${formatNumber(summary.webhooks_24h)} received`}
            tone={summary.unacknowledged_webhook_failures > 0 ? 'text-err' : 'text-fg'}
          />
          <Kpi
            label="Refund queue"
            value={formatNumber(summary.open_refund_requests)}
            detail="Pending or approved"
            tone={summary.open_refund_requests > 0 ? 'text-warn' : 'text-fg'}
          />
          <Kpi
            label="Gross revenue"
            value={formatMoney(summary.gross_revenue, summary.currency)}
            detail={`${formatNumber(summary.payments_count)} payments · ${summary.period_days} day window`}
          />
        </div>
      )}

      <AdminRevenueBreakdown
        summary={summary}
        granularity={granularity}
        onGranularity={setGranularity}
      />

      <AdminCouponStudentPerformance />

      <AdminPlanHealth />

      <AdminTeamSeatUtilization />

      <WebhookHealth
        data={webhooks}
        loading={loading}
        filters={filters}
        onFilters={(next) => {
          setFilters(next)
          setWebhookOffset(0)
        }}
        offset={webhookOffset}
        onOffset={setWebhookOffset}
        actionId={actionId}
        note={note}
        replayConfirmed={replayConfirmed}
        onActionId={(id) => { setActionId(id); setNote(''); setReplayConfirmed(false) }}
        onNote={setNote}
        onReplayConfirmed={setReplayConfirmed}
        onReconcile={reconcile}
        onReplay={replay}
        onAcknowledge={acknowledge}
        busyId={busyId}
      />

      <ReconciliationQueue
        data={reconciliation}
        loading={loading}
        offset={reconciliationOffset}
        onOffset={setReconciliationOffset}
        actionId={reconciliationActionId}
        note={reconciliationNote}
        confirmed={reconciliationConfirmed}
        onActionId={(id) => {
          setReconciliationActionId(id)
          setReconciliationNote('')
          setReconciliationConfirmed(false)
        }}
        onNote={setReconciliationNote}
        onConfirmed={setReconciliationConfirmed}
        onAcknowledge={acknowledgeReconciliation}
        onReplay={replayReconciliation}
        busyId={busyId}
      />

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Create refund or goodwill request</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Use the local payment UUID or the Dodo payment ID. A full refund leaves the amount blank. Partial refunds
              require the provider line-item ID and are submitted through Dodo only after a different admin approves.
            </p>
          </div>
          <button type="button" onClick={() => setShowCreate((value) => !value)} className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
            {showCreate ? 'Cancel' : 'New request'}
          </button>
        </div>
        {showCreate && (
          <form onSubmit={createRefund} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-[11px] text-fg-2">
              Payment UUID or Dodo payment ID
              <input value={refundPaymentId} onChange={(event) => setRefundPaymentId(event.target.value)} required minLength={4} maxLength={255} className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
            </label>
            <label className="text-[11px] text-fg-2">
              Request type
              <select value={refundKind} onChange={(event) => setRefundKind(event.target.value as 'refund' | 'goodwill')} className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg">
                <option value="refund">Refund</option>
                <option value="goodwill">Goodwill</option>
              </select>
            </label>
            <label className="text-[11px] text-fg-2">
              Amount (paise, blank = full)
              <input value={refundAmount} onChange={(event) => setRefundAmount(event.target.value)} inputMode="numeric" className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg" />
            </label>
            <label className="text-[11px] text-fg-2">
              Provider item ID (partial only)
              <input value={refundItemId} onChange={(event) => setRefundItemId(event.target.value)} className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
            </label>
            <label className="text-[11px] text-fg-2 sm:col-span-2">
              Reason
              <input value={refundReason} onChange={(event) => setRefundReason(event.target.value)} required minLength={3} maxLength={1000} className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg" />
            </label>
            <label className="text-[11px] text-fg-2 sm:col-span-2 lg:col-span-3">
              Evidence (optional, admin-only)
              <textarea value={refundEvidence} onChange={(event) => setRefundEvidence(event.target.value)} maxLength={2000} rows={2} className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg" placeholder="Ticket IDs, policy reference, or customer correspondence summary. Never paste card data." />
            </label>
            <button type="submit" disabled={Boolean(busyId)} className="min-h-[40px] rounded-md bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-40 sm:col-span-2 lg:col-span-1">
              Submit request
            </button>
          </form>
        )}
      </section>

      <RefundQueue
        data={refunds}
        loading={loading}
        offset={refundOffset}
        onOffset={setRefundOffset}
        actionId={refundActionId}
        note={refundNote}
        onActionId={(id) => { setRefundActionId(id); setRefundNote('') }}
        onNote={setRefundNote}
        onDecision={decideRefund}
        onExecute={executeRefund}
        onReconcile={reconcileRefund}
        busyId={busyId}
      />
    </div>
  )
}
