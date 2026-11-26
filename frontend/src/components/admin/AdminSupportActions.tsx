'use client'

import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminPaymentReceipt,
  type AdminSupportActionResult,
  type AdminUserPayment,
} from '@/lib/api-client'
import { formatDateTime, formatMoney, shortId } from './admin-format'

const ELIGIBLE_RECEIPT_STATUSES = new Set(['paid', 'partially_refunded'])

const LINE_ITEM_STATE_COPY: Record<AdminPaymentReceipt['line_items_state'], string> = {
  available: 'Itemised lines came from the payment processor.',
  not_exposed: 'The payment processor did not expose itemised lines; the receipt will use the Latexy ledger total.',
  not_linked: 'This payment has no processor reference; the receipt will use the Latexy ledger total.',
  unconfigured: 'The payment processor is not configured; the receipt will use the Latexy ledger total.',
}

function StatePill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${
        ok
          ? 'border-ok/30 bg-ok/10 text-ok'
          : 'border-line bg-surface-2 text-fg-3'
      }`}
    >
      {label}
    </span>
  )
}

export default function AdminSupportActions({
  userId,
  emailVerified,
  emailLabel,
  payments,
  onChanged,
}: {
  userId: string
  emailVerified: boolean
  emailLabel: string
  payments: AdminUserPayment[]
  onChanged: () => void | Promise<void>
}) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [selectedPaymentId, setSelectedPaymentId] = useState('')
  const [receipt, setReceipt] = useState<AdminPaymentReceipt | null>(null)
  const [lastResult, setLastResult] = useState<string | null>(null)

  const eligiblePayments = useMemo(
    () => payments.filter((payment) => ELIGIBLE_RECEIPT_STATUSES.has(payment.status)),
    [payments],
  )

  useEffect(() => {
    setSelectedPaymentId((current) =>
      current && eligiblePayments.some((payment) => payment.id === current)
        ? current
        : (eligiblePayments[0]?.id ?? ''),
    )
  }, [eligiblePayments])

  useEffect(() => {
    setReceipt(null)
  }, [selectedPaymentId])

  const cleanedReason = reason.trim()

  const requireReason = (): string | null => {
    if (cleanedReason.length < 3) {
      toast.error('Enter a reason of at least 3 characters for this audited action')
      return null
    }
    return cleanedReason
  }

  const recordResult = (result: AdminSupportActionResult) => {
    const stateNote =
      result.action === 'payment_receipt' && result.line_items_source === 'local'
        ? ' Sent with the ledger total; no provider line items were available.'
        : ''
    setLastResult(
      `${
        result.action === 'verification_email'
          ? 'Verification email'
          : result.action === 'password_reset'
            ? 'Password reset email'
            : 'Payment receipt'
      } accepted by the provider.${stateNote}`,
    )
  }

  const sendVerification = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!window.confirm(`Send a verification link to ${emailLabel}?`)) return
    setBusy('verification')
    try {
      const result = await apiClient.resendAdminVerificationEmail(userId, cleaned)
      recordResult(result)
      toast.success('Verification email accepted for delivery')
      await onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Verification email failed')
    } finally {
      setBusy(null)
    }
  }

  const sendPasswordReset = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (
      !window.confirm(
        `Send a password reset link to ${emailLabel}? Resetting will sign out their existing sessions.`,
      )
    ) {
      return
    }
    setBusy('password-reset')
    try {
      const result = await apiClient.sendAdminPasswordReset(userId, cleaned)
      recordResult(result)
      toast.success('Password reset email accepted for delivery')
      await onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Password reset email failed')
    } finally {
      setBusy(null)
    }
  }

  const loadReceipt = async () => {
    if (!selectedPaymentId) return
    setBusy('receipt-preview')
    try {
      const next = await apiClient.getAdminPaymentReceipt(userId, selectedPaymentId)
      setReceipt(next)
    } catch (err) {
      setReceipt(null)
      toast.error(err instanceof Error ? err.message : 'Receipt lookup failed')
    } finally {
      setBusy(null)
    }
  }

  const sendReceipt = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!selectedPaymentId) {
      toast.error('Choose a settled payment first')
      return
    }
    if (!window.confirm(`Email a payment receipt for this payment to ${emailLabel}?`)) return
    setBusy('receipt-send')
    try {
      const result = await apiClient.resendAdminPaymentReceipt(
        userId,
        selectedPaymentId,
        cleaned,
      )
      recordResult(result)
      toast.success('Payment receipt accepted for delivery')
      await onChanged()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Payment receipt failed')
    } finally {
      setBusy(null)
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-fg">Support email delivery</h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Resend account emails through the existing transactional provider. Each send needs a
            reason and an explicit confirmation, is rate-limited per operator and target, and is
            written to the immutable audit log. Tokens and one-time links are never returned here.
          </p>
        </div>
        <StatePill label={emailVerified ? 'email verified' : 'email unverified'} ok={emailVerified} />
      </div>

      <label className="mt-3 block text-[11px] font-medium text-fg-2">
        Reason for these support emails
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={1000}
          placeholder="e.g. Ticket #1234 — customer cannot receive account email"
          className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
        />
      </label>
      <p className="mt-1 text-[10px] text-fg-3">
        The same reason is recorded on every audit row written by this panel.
      </p>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-line bg-surface-2/40 p-3">
          <p className="text-xs font-semibold text-fg">Account email</p>
          <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
            Verification is only sent while the address is unverified. Password reset is only
            available for accounts with a password credential.
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void sendVerification()}
              disabled={Boolean(busy) || !cleanedReason || emailVerified}
              className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {busy === 'verification' ? 'Sending…' : 'Resend verification'}
            </button>
            <button
              type="button"
              onClick={() => void sendPasswordReset()}
              disabled={Boolean(busy) || !cleanedReason}
              className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {busy === 'password-reset' ? 'Sending…' : 'Send password reset'}
            </button>
          </div>
          {emailVerified && (
            <p className="mt-2 text-[10px] text-fg-3">
              Verification resend is hidden because this address is already verified.
            </p>
          )}
        </div>

        <div className="rounded-md border border-line bg-surface-2/40 p-3">
          <p className="text-xs font-semibold text-fg">Payment receipt</p>
          <p className="mt-1 text-[10px] leading-relaxed text-fg-3">
            Only settled payments are eligible. A lookup shows what the processor exposes before
            anything is emailed.
          </p>
          <select
            aria-label="Receipt payment"
            value={selectedPaymentId}
            onChange={(event) => setSelectedPaymentId(event.target.value)}
            disabled={Boolean(busy) || eligiblePayments.length === 0}
            className="mt-2 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg disabled:opacity-50"
          >
            {eligiblePayments.length === 0 ? (
              <option value="">No settled payments</option>
            ) : (
              eligiblePayments.map((payment) => (
                <option key={payment.id} value={payment.id}>
                  {shortId(payment.id, 12)} · {formatMoney(payment.amount / 100, payment.currency)} ·{' '}
                  {payment.status} · {formatDateTime(payment.created_at)}
                </option>
              ))
            )}
          </select>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void loadReceipt()}
              disabled={Boolean(busy) || !selectedPaymentId}
              className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {busy === 'receipt-preview' ? 'Loading…' : 'Look up receipt'}
            </button>
            <button
              type="button"
              onClick={() => void sendReceipt()}
              disabled={Boolean(busy) || !cleanedReason || !selectedPaymentId}
              className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {busy === 'receipt-send' ? 'Sending…' : 'Email receipt'}
            </button>
          </div>

          {receipt && (
            <div className="mt-3 rounded border border-line bg-bg/40 p-2">
              <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-fg-3">
                <span>
                  {shortId(receipt.payment_id, 16)} · {receipt.status} ·{' '}
                  {formatDateTime(receipt.paid_at)}
                </span>
                <span className="font-mono text-fg-2">
                  {formatMoney(receipt.amount_minor / 100, receipt.currency)}
                </span>
              </div>
              <p className="mt-1 text-[10px] text-fg-3">
                {LINE_ITEM_STATE_COPY[receipt.line_items_state] ??
                  'Receipt source state is unavailable.'}
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
                          : formatMoney(item.amount_minor / 100, item.currency ?? receipt.currency)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>

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
