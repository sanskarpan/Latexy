'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminPaymentReceipt,
  type AdminReceiptInvoiceState,
  type AdminReceiptLineItemsState,
  type AdminReceiptSearchItem,
  type AdminReceiptSearchResult,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, shortId } from './admin-format'

type SearchMode = 'payment' | 'subscription' | 'user' | 'email'

const SEARCH_MODES: Array<{ id: SearchMode; label: string; placeholder: string }> = [
  {
    id: 'payment',
    label: 'Payment ID',
    placeholder: 'Local payment UUID or Dodo payment ID',
  },
  {
    id: 'subscription',
    label: 'Subscription ID',
    placeholder: 'Local subscription UUID or Dodo subscription/checkout ID',
  },
  {
    id: 'user',
    label: 'User ID',
    placeholder: 'Account user UUID',
  },
  {
    id: 'email',
    label: 'Email hash',
    placeholder: '64-character SHA-256 hex digest',
  },
]

const INVOICE_STATE_COPY: Record<AdminReceiptInvoiceState, string> = {
  available: 'A provider invoice PDF is available and will be attached to the email.',
  not_exposed: 'The payment processor did not expose an invoice for this payment.',
  not_linked: 'This payment has no processor reference; no provider invoice can exist.',
  unconfigured: 'The payment processor is not configured, so no provider invoice can be fetched.',
}

const LINE_ITEM_STATE_COPY: Record<AdminReceiptLineItemsState, string> = {
  available: 'Itemised lines came from the payment processor.',
  not_exposed: 'The payment processor did not expose itemised lines; the ledger total is authoritative.',
  not_linked: 'This payment has no processor reference; the ledger total is authoritative.',
  unconfigured: 'The payment processor is not configured; the ledger total is authoritative.',
}

function newReceiptIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `receipt-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

function StatePill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        ok ? 'border-ok/30 bg-ok/10 text-ok' : 'border-line bg-surface-2 text-fg-3'
      }`}
    >
      {label}
    </span>
  )
}

export default function AdminReceiptLookup() {
  const [mode, setMode] = useState<SearchMode>('payment')
  const [value, setValue] = useState('')
  const [result, setResult] = useState<AdminReceiptSearchResult | null>(null)
  const [selected, setSelected] = useState<AdminReceiptSearchItem | null>(null)
  const [receipt, setReceipt] = useState<AdminPaymentReceipt | null>(null)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [lastResult, setLastResult] = useState<string | null>(null)

  const activeMode = SEARCH_MODES.find((item) => item.id === mode) ?? SEARCH_MODES[0]
  const cleanedReason = reason.trim()

  const requireReason = (): string | null => {
    if (cleanedReason.length < 3) {
      toast.error('Enter a reason of at least 3 characters for this audited action')
      return null
    }
    return cleanedReason
  }

  const runSearch = async () => {
    if (busy) return
    const query = value.trim()
    if (!query) {
      toast.error(`Enter a ${activeMode.label.toLowerCase()} to search`)
      return
    }
    setBusy('search')
    setError(null)
    setReceipt(null)
    setSelected(null)
    setLastResult(null)
    try {
      const next = await apiClient.searchAdminReceipts(
        mode === 'payment'
          ? { payment_id: query }
          : mode === 'subscription'
            ? { subscription_id: query }
            : mode === 'user'
              ? { user_id: query }
              : { email_hash: query },
      )
      setResult(next)
      setSelected(next.items[0] ?? null)
      if (next.items.length === 0) {
        setLastResult('No payments matched that exact lookup. Nothing was looked up at the processor.')
      }
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Receipt search failed')
    } finally {
      setBusy(null)
    }
  }

  const loadReceipt = async (item: AdminReceiptSearchItem) => {
    setSelected(item)
    setReceipt(null)
    setError(null)
    setBusy('receipt-preview')
    try {
      const next = await apiClient.getAdminPaymentReceipt(item.user_id, item.payment_id)
      setReceipt(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Receipt lookup failed')
    } finally {
      setBusy(null)
    }
  }

  const sendReceipt = async () => {
    if (!selected) {
      toast.error('Select a payment first')
      return
    }
    const cleaned = requireReason()
    if (!cleaned) return
    if (
      !window.confirm(
        'Email this payment receipt to the account owner? The send is audited and limited per operator.',
      )
    ) {
      return
    }
    setBusy('receipt-send')
    setError(null)
    setLastResult(null)
    try {
      const next = await apiClient.resendAdminPaymentReceipt(
        selected.user_id,
        selected.payment_id,
        cleaned,
        newReceiptIdempotencyKey(),
      )
      if (next.duplicate) {
        setLastResult(
          'This idempotency key already completed. The earlier receipt was not sent again.',
        )
        toast.success('Receipt already sent for this idempotency key')
      } else {
        const invoiceNote =
          next.invoice_attached === true
            ? ' The provider invoice PDF was attached.'
            : ` No invoice PDF was attached (${next.invoice_state ?? 'not available'}).`
        setLastResult(`Receipt accepted by the provider.${invoiceNote}`)
        toast.success('Payment receipt accepted for delivery')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Payment receipt failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-fg">Receipt and invoice lookup</h2>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
            Find a settled payment by exact payment, subscription, account or email digest.
            Lookups never return an address, card field or raw provider payload. Resends need a
            reason, explicit confirmation and an idempotency key, and are written to the immutable
            audit log.
          </p>
        </div>
        <StatePill label="admin only" ok />
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(150px,210px)_minmax(0,1fr)_auto]">
        <label className="block text-[11px] font-medium text-fg-2">
          Lookup by
          <select
            value={mode}
            onChange={(event) => {
              setMode(event.target.value as SearchMode)
              setValue('')
              setResult(null)
              setSelected(null)
              setReceipt(null)
              setLastResult(null)
            }}
            disabled={Boolean(busy)}
            className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-2 text-xs text-fg"
          >
            {SEARCH_MODES.map((item) => (
              <option key={item.id} value={item.id}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-[11px] font-medium text-fg-2">
          Exact {activeMode.label.toLowerCase()}
          <input
            value={value}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void runSearch()
            }}
            maxLength={255}
            placeholder={activeMode.placeholder}
            aria-label={`Exact ${activeMode.label.toLowerCase()}`}
            className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
          />
        </label>
        <div className="flex items-end">
          <button
            type="button"
            onClick={() => void runSearch()}
            disabled={Boolean(busy) || !value.trim()}
            className="rounded border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            {busy === 'search' ? 'Searching…' : 'Search receipts'}
          </button>
        </div>
      </div>
      <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
        Email hash uses the same one-way digest as email health: SHA-256 of the trimmed, lowercased
        account address. The raw address is never sent by this panel.
      </p>

      {error && (
        <div role="alert" className="mt-3 rounded-md border border-err/30 bg-err/[0.06] px-3 py-2 text-xs text-err">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-4 overflow-hidden rounded-md border border-line">
          {result.items.length === 0 ? (
            <p className="px-3 py-4 text-center text-xs text-fg-3">
              No payments matched this exact lookup.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[760px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                    <th className="px-3 py-2 text-left font-semibold">Payment</th>
                    <th className="px-3 py-2 text-left font-semibold">Account</th>
                    <th className="px-3 py-2 text-left font-semibold">Amount</th>
                    <th className="px-3 py-2 text-left font-semibold">Status</th>
                    <th className="px-3 py-2 text-left font-semibold">Created</th>
                    <th className="px-3 py-2 text-left font-semibold">Receipt</th>
                    <th className="px-3 py-2 text-left font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((item) => {
                    const isSelected = selected?.payment_id === item.payment_id
                    return (
                      <tr
                        key={item.payment_id}
                        className={`border-t border-line ${isSelected ? 'bg-accent/[0.06]' : ''}`}
                      >
                        <td className="px-3 py-2 font-mono text-[10px] text-fg-3">
                          {shortId(item.payment_id, 14)}
                          {item.provider_payment_id && (
                            <p className="mt-0.5 text-[9px] text-fg-3">
                              {shortId(item.provider_payment_id, 18)}
                            </p>
                          )}
                        </td>
                        <td className="px-3 py-2 font-mono text-[10px] text-fg-3">
                          {shortId(item.user_id, 14)}
                        </td>
                        <td className="px-3 py-2 font-mono text-fg-2">
                          {formatMoney(item.amount_minor / 100, item.currency)}
                        </td>
                        <td className="px-3 py-2 text-fg-2">{item.status}</td>
                        <td className="px-3 py-2 text-fg-3">{formatDateTime(item.created_at)}</td>
                        <td className="px-3 py-2">
                          <StatePill
                            label={item.receipt_eligible ? 'settled' : 'not settled'}
                            ok={item.receipt_eligible}
                          />
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => void loadReceipt(item)}
                              disabled={Boolean(busy) || !item.receipt_eligible}
                              className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                            >
                              {busy === 'receipt-preview' && isSelected
                                ? 'Loading…'
                                : 'Look up receipt'}
                            </button>
                            <a
                              href={`/admin?tab=customers&user=${encodeURIComponent(item.user_id)}`}
                              className="rounded border border-line px-2 py-1 text-[10px] font-medium text-accent hover:bg-surface-2"
                            >
                              Timeline
                            </a>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          {result.truncated && (
            <p className="border-t border-line px-3 py-2 text-[10px] text-fg-3">
              Showing the newest {result.limit} payments. Narrow the lookup to see fewer.
            </p>
          )}
        </div>
      )}

      {selected && (
        <div className="mt-4 grid gap-3 xl:grid-cols-2">
          <div className="rounded-md border border-line bg-surface-2/40 p-3">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-xs font-semibold text-fg">Selected payment</p>
                <p className="mt-1 font-mono text-[10px] text-fg-3">
                  {selected.payment_id}
                </p>
              </div>
              <StatePill
                label={selected.receipt_eligible ? 'receipt eligible' : 'not eligible'}
                ok={selected.receipt_eligible}
              />
            </div>
            <p className="mt-2 text-[11px] text-fg-2">
              {formatMoney(selected.amount_minor / 100, selected.currency)} · {selected.status} ·{' '}
              {formatDateTime(selected.created_at)}
            </p>
            <p className="mt-1 text-[10px] text-fg-3">
              Account {shortId(selected.user_id, 18)} · provider{' '}
              {selected.provider_linked ? 'linked' : 'not linked'}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <a
                href={`/admin?tab=customers&user=${encodeURIComponent(selected.user_id)}`}
                className="rounded border border-line px-2.5 py-1.5 text-[10px] font-medium text-accent hover:bg-surface-2"
              >
                Open payment timeline
              </a>
              <button
                type="button"
                onClick={() => void loadReceipt(selected)}
                disabled={Boolean(busy) || !selected.receipt_eligible}
                className="rounded border border-line px-2.5 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
              >
                {busy === 'receipt-preview' ? 'Loading…' : 'Refresh receipt lookup'}
              </button>
            </div>

            <label className="mt-3 block text-[10px] font-medium text-fg-2">
              Reason for this audited resend
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                maxLength={1000}
                placeholder="e.g. Ticket #1234 — customer needs a copy"
                className="mt-1 w-full rounded-md border border-line bg-bg px-2 py-1.5 text-xs text-fg"
              />
            </label>
            <button
              type="button"
              onClick={() => void sendReceipt()}
              disabled={Boolean(busy) || !cleanedReason || !selected.receipt_eligible}
              className="mt-2 rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {busy === 'receipt-send' ? 'Sending…' : 'Email receipt'}
            </button>
            <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
              Each click uses a fresh idempotency key. A retry with a completed key returns the
              earlier result instead of sending a duplicate. Sends are rate-limited per operator
              and account.
            </p>
          </div>

          <div className="rounded-md border border-line bg-surface-2/40 p-3">
            <p className="text-xs font-semibold text-fg">Receipt preview</p>
            {!receipt ? (
              <p className="mt-2 text-[11px] leading-relaxed text-fg-3">
                Look up the receipt to inspect provider invoice availability and line items before
                sending anything.
              </p>
            ) : (
              <>
                <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[10px] text-fg-3">
                  <span>
                    {shortId(receipt.payment_id, 16)} · {receipt.status} ·{' '}
                    {formatDateTime(receipt.paid_at)}
                  </span>
                  <span className="font-mono text-fg-2">
                    {formatMoney(receipt.amount_minor / 100, receipt.currency)}
                  </span>
                </div>
                <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
                  {INVOICE_STATE_COPY[receipt.invoice_state]}
                </p>
                <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
                  {LINE_ITEM_STATE_COPY[receipt.line_items_state]}
                </p>
                {receipt.line_items.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {receipt.line_items.map((item, index) => (
                      <li
                        key={`${item.description}-${index}`}
                        className="flex items-center justify-between gap-2 border-t border-line pt-1 text-[10px] text-fg-2"
                      >
                        <span className="min-w-0 truncate">
                          {item.description} × {item.quantity}
                        </span>
                        <span className="shrink-0 font-mono text-fg-3">
                          {item.amount_minor == null
                            ? '—'
                            : formatMoney(
                                item.amount_minor / 100,
                                item.currency ?? receipt.currency,
                              )}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </>
            )}
          </div>
        </div>
      )}

      {lastResult && (
        <div
          role="status"
          className="mt-3 rounded-md border border-line bg-surface-2/60 px-3 py-2 text-[11px] text-fg-3"
        >
          <p className="font-semibold text-fg-2">Delivery result</p>
          <p className="mt-1">{lastResult}</p>
        </div>
      )}
    </section>
  )
}
