'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminBillingSummary,
  type AdminBillingWebhookList,
  type AdminRefundList,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, formatNumber, shortId, summarize } from './admin-format'

const RANGES = [7, 30, 90] as const
const PAGE_SIZE = 25

type AckFilter = 'all' | 'unacknowledged' | 'acknowledged'

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
  onActionId,
  onNote,
  onReconcile,
  onAcknowledge,
  busyId,
}: {
  data: AdminBillingWebhookList | null
  loading: boolean
  filters: { status: string; acknowledged: AckFilter; q: string }
  onFilters: (next: { status: string; acknowledged: AckFilter; q: string }) => void
  offset: number
  onOffset: (next: number) => void
  actionId: string | null
  note: string
  onActionId: (id: string | null) => void
  onNote: (value: string) => void
  onReconcile: (id: string) => void
  onAcknowledge: (id: string) => void
  busyId: string | null
}) {
  const [draftQuery, setDraftQuery] = useState(filters.q)
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Dodo webhook health</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Durable receipts for signed provider events. Acknowledge a provider-side dead letter only after review;
              reconcile re-reads the linked checkout from Dodo. Replay in Dodo remains the authoritative provider action.
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
                        {!row.acknowledged_at && row.status !== 'processed' && (
                          <button
                            type="button"
                            onClick={() => onAcknowledge(row.id)}
                            disabled={busyId === row.id}
                            className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                          >
                            Quick ack
                          </button>
                        )}
                      </div>
                      {isOpen && (
                        <div className="mt-2 space-y-2 rounded-md border border-line bg-surface-2/60 p-2">
                          <label className="block text-[10px] font-medium text-fg-2">
                            Review note
                            <input
                              value={note}
                              onChange={(event) => onNote(event.target.value)}
                              maxLength={1000}
                              placeholder="What did you verify?"
                              className="mt-1 w-full rounded border border-line bg-bg px-2 py-1 text-xs text-fg"
                            />
                          </label>
                          <div className="flex flex-wrap gap-1.5">
                            <button
                              type="button"
                              onClick={() => onReconcile(row.id)}
                              disabled={busyId === row.id || !note.trim()}
                              className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                            >
                              Reconcile from Dodo
                            </button>
                            <button
                              type="button"
                              onClick={() => onAcknowledge(row.id)}
                              disabled={busyId === row.id || !note.trim()}
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
  busyId: string | null
}) {
  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))
  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
      <div className="border-b border-line px-5 py-4">
        <h3 className="text-sm font-semibold text-fg">Refund approval queue</h3>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
          Requests require a different admin to approve. Execution never happens automatically; the provider webhook
          remains the authoritative settlement record.
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
                const executable = row.status === 'approved' || row.status === 'failed'
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
                      <p>{summarize(row.reason, 160)}</p>
                      {row.decision_note && <p className="mt-1 text-[10px]">Decision: {summarize(row.decision_note, 120)}</p>}
                      {row.last_error && <p className="mt-1 text-[10px] text-err">{summarize(row.last_error, 120)}</p>}
                      {row.provider_refund_id && <p className="mt-1 font-mono text-[10px] text-ok">{row.provider_refund_id}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => onActionId(isOpen ? null : row.id)}
                        className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2"
                      >
                        {isOpen ? 'Cancel' : awaitingDecision || executable ? 'Review' : 'Details'}
                      </button>
                      {isOpen && (awaitingDecision || executable) && (
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
                                disabled={busyId === row.id || !note.trim()}
                                className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                              >
                                Approve
                              </button>
                              <button
                                type="button"
                                onClick={() => onDecision(row.id, 'reject')}
                                disabled={busyId === row.id || !note.trim()}
                                className="rounded border border-err/30 px-2 py-1 text-[10px] font-medium text-err disabled:opacity-40"
                              >
                                Reject
                              </button>
                            </div>
                          ) : (
                            <button
                              type="button"
                              onClick={() => onExecute(row.id)}
                              disabled={busyId === row.id}
                              className="rounded bg-accent px-2 py-1 text-[10px] font-semibold text-accent-fg disabled:opacity-40"
                            >
                              {row.status === 'failed' ? 'Retry refund' : 'Execute refund'}
                            </button>
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

export default function AdminBilling() {
  const [days, setDays] = useState<number>(30)
  const [summary, setSummary] = useState<AdminBillingSummary | null>(null)
  const [webhooks, setWebhooks] = useState<AdminBillingWebhookList | null>(null)
  const [refunds, setRefunds] = useState<AdminRefundList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<{ status: string; acknowledged: AckFilter; q: string }>({
    status: 'failed',
    acknowledged: 'unacknowledged',
    q: '',
  })
  const [webhookOffset, setWebhookOffset] = useState(0)
  const [refundOffset, setRefundOffset] = useState(0)
  const [actionId, setActionId] = useState<string | null>(null)
  const [refundActionId, setRefundActionId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [refundNote, setRefundNote] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [refreshKey, setRefreshKey] = useState(0)
  const [showCreate, setShowCreate] = useState(false)
  const [refundPaymentId, setRefundPaymentId] = useState('')
  const [refundAmount, setRefundAmount] = useState('')
  const [refundItemId, setRefundItemId] = useState('')
  const [refundReason, setRefundReason] = useState('')

  const acknowledged = filters.acknowledged === 'all' ? undefined : filters.acknowledged === 'acknowledged'

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextSummary, nextWebhooks, nextRefunds] = await Promise.all([
        apiClient.getAdminBillingSummary(days),
        apiClient.getAdminBillingWebhooks({
          status: filters.status === 'all' ? undefined : filters.status,
          acknowledged,
          q: filters.q || undefined,
          limit: PAGE_SIZE,
          offset: webhookOffset,
        }),
        apiClient.getAdminRefundRequests({ limit: PAGE_SIZE, offset: refundOffset }),
      ])
      setSummary(nextSummary)
      setWebhooks(nextWebhooks)
      setRefunds(nextRefunds)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load billing control room')
    } finally {
      setLoading(false)
    }
  }, [acknowledged, days, filters.q, filters.status, refundOffset, webhookOffset])

  useEffect(() => {
    void load()
  }, [load, refreshKey])

  const planMix = useMemo(() => summary?.plan_mix ?? [], [summary])

  const reconcile = async (id: string) => {
    if (!note.trim()) return
    setBusyId(id)
    try {
      const result = await apiClient.reconcileAdminWebhook(id, note.trim())
      toast.success(result.message || 'Provider state reconciled')
      setActionId(null)
      setNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Reconciliation failed')
    } finally {
      setBusyId(null)
    }
  }

  const acknowledge = async (id: string) => {
    const effectiveNote = note.trim() || 'Reviewed in the admin billing control room'
    setBusyId(id)
    try {
      await apiClient.acknowledgeAdminWebhook(id, effectiveNote)
      toast.success('Webhook acknowledged')
      setActionId(null)
      setNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Acknowledgement failed')
    } finally {
      setBusyId(null)
    }
  }

  const decideRefund = async (id: string, decision: 'approve' | 'reject') => {
    if (!refundNote.trim()) return
    setBusyId(id)
    try {
      await apiClient.decideAdminRefund(id, decision, refundNote.trim())
      toast.success(decision === 'approve' ? 'Refund approved' : 'Refund rejected')
      setRefundActionId(null)
      setRefundNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund decision failed')
    } finally {
      setBusyId(null)
    }
  }

  const executeRefund = async (id: string) => {
    setBusyId(id)
    try {
      const updated = await apiClient.executeAdminRefund(id, refundNote.trim() || undefined)
      toast.success(updated.status === 'executed' ? 'Refund submitted to Dodo' : 'Refund execution failed')
      setRefundActionId(null)
      setRefundNote('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund execution failed')
    } finally {
      setBusyId(null)
    }
  }

  const createRefund = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!refundPaymentId.trim() || !refundReason.trim()) return
    setBusyId('create-refund')
    try {
      await apiClient.createAdminRefundRequest({
        payment_id: refundPaymentId.trim(),
        amount: refundAmount.trim() ? Number(refundAmount) : null,
        provider_item_id: refundItemId.trim() || null,
        reason: refundReason.trim(),
      })
      toast.success('Refund request created; a different admin must approve it')
      setShowCreate(false)
      setRefundPaymentId('')
      setRefundAmount('')
      setRefundItemId('')
      setRefundReason('')
      setRefreshKey((value) => value + 1)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Refund request failed')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-6">
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
                aria-pressed={days === range}
                onClick={() => setDays(range)}
                className={`rounded px-3 py-1.5 text-xs font-medium ${days === range ? 'bg-accent-soft text-accent-strong' : 'text-fg-3 hover:text-fg'}`}
              >
                {range} days
              </button>
            ))}
          </div>
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

      {summary && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <Kpi label="MRR" value={formatMoney(summary.mrr)} detail={`ARR ${formatMoney(summary.arr)}`} />
          <Kpi
            label="Active subscriptions"
            value={formatNumber(summary.active_subscriptions)}
            detail={`${formatNumber(summary.past_due_subscriptions)} past due`}
          />
          <Kpi label="Net revenue" value={formatMoney(summary.net_revenue)} detail={`${formatMoney(summary.refunded)} refunded`} />
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
          <Kpi label="Gross revenue" value={formatMoney(summary.gross_revenue)} detail={`Last ${summary.period_days} days`} />
        </div>
      )}

      {planMix.length > 0 && (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
          <h3 className="text-sm font-semibold text-fg">Plan mix</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            {planMix.map((item) => (
              <span key={item.plan_id} className="rounded-full border border-line bg-surface-2 px-3 py-1 text-xs text-fg-2">
                {item.plan_id} · {formatNumber(item.subscriptions)} · {formatMoney(item.mrr)} MRR
              </span>
            ))}
          </div>
        </div>
      )}

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
        onActionId={setActionId}
        onNote={setNote}
        onReconcile={reconcile}
        onAcknowledge={acknowledge}
        busyId={busyId}
      />

      <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-fg">Create refund request</h3>
            <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
              Use the local payment UUID. A full refund leaves the amount blank. Partial refunds require the provider
              line-item ID and are submitted through Dodo only after a second admin approves.
            </p>
          </div>
          <button type="button" onClick={() => setShowCreate((value) => !value)} className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
            {showCreate ? 'Cancel' : 'New request'}
          </button>
        </div>
        {showCreate && (
          <form onSubmit={createRefund} className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <label className="text-[11px] text-fg-2">
              Payment UUID
              <input value={refundPaymentId} onChange={(event) => setRefundPaymentId(event.target.value)} required className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
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
            <button type="submit" disabled={busyId === 'create-refund'} className="min-h-[40px] rounded-md bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-40 sm:col-span-2 lg:col-span-1">
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
        onActionId={setRefundActionId}
        onNote={setRefundNote}
        onDecision={decideRefund}
        onExecute={executeRefund}
        busyId={busyId}
      />
    </div>
  )
}
