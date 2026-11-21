'use client'

import { useCallback, useEffect, useState } from 'react'
import { apiClient, type AdminAuditList } from '@/lib/api-client'
import { formatDateTime, formatNumber, shortId, summarize } from './admin-format'

const PAGE_SIZE = 50

export default function AdminAudit() {
  const [data, setData] = useState<AdminAuditList | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [action, setAction] = useState('')
  const [targetType, setTargetType] = useState('')
  const [targetId, setTargetId] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminAudit({
        action: action || undefined,
        target_type: targetType || undefined,
        target_id: targetId || undefined,
        limit: PAGE_SIZE,
        offset,
      })
      setData(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load audit log')
    } finally {
      setLoading(false)
    }
  }, [action, offset, targetId, targetType])

  useEffect(() => {
    void load()
  }, [load])

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE))

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-fg">Admin audit log</h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Append-only records for admin mutations, refund decisions, PII reveals, and support actions. The database
          rejects UPDATE and DELETE on this table. Secrets, document content, and credentials are redacted before write.
        </p>
      </div>

      <form
        className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={(event) => {
          event.preventDefault()
          setOffset(0)
        }}
      >
        <label className="text-[11px] text-fg-2">
          Action
          <input value={action} onChange={(event) => setAction(event.target.value)} placeholder="billing.refund.approved" className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
        </label>
        <label className="text-[11px] text-fg-2">
          Target type
          <input value={targetType} onChange={(event) => setTargetType(event.target.value)} placeholder="user, refund_request…" className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
        </label>
        <label className="text-[11px] text-fg-2">
          Target ID
          <input value={targetId} onChange={(event) => setTargetId(event.target.value)} className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg" />
        </label>
        <div className="flex items-end gap-2">
          <button type="submit" className="min-h-[38px] flex-1 rounded border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2">Apply filters</button>
          <button type="button" onClick={() => { setAction(''); setTargetType(''); setTargetId(''); setOffset(0) }} className="min-h-[38px] rounded border border-line px-3 py-2 text-xs text-fg-3 hover:bg-surface-2">Reset</button>
        </div>
      </form>

      {error && <div role="alert" className="rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err">{error}</div>}

      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
        {loading && !data ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 6 }).map((_, index) => <div key={index} className="h-12 animate-pulse rounded-md bg-surface-2" />)}
          </div>
        ) : !data || data.items.length === 0 ? (
          <p className="px-5 py-12 text-center text-sm text-fg-3">No audit entries match these filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] border-collapse text-sm">
              <caption className="sr-only">Immutable admin audit entries, newest first</caption>
              <thead>
                <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Time</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Actor</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Action</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Target</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Reason</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Request</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((row) => (
                  <tr key={row.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-fg-3">{formatDateTime(row.created_at)}</td>
                    <td className="px-4 py-3 text-xs text-fg-2">
                      <p className="break-all">{row.actor_email || shortId(row.actor_user_id, 12)}</p>
                      <p className="mt-0.5 font-mono text-[10px] text-fg-3">{shortId(row.actor_user_id, 12)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <button type="button" onClick={() => setSelected(selected === row.id ? null : row.id)} className="text-left font-mono text-xs text-fg hover:text-accent-strong">
                        {row.action}
                      </button>
                      {selected === row.id && (
                        <pre className="mt-2 max-h-56 max-w-[420px] overflow-auto whitespace-pre-wrap rounded border border-line bg-surface-2/60 p-2 text-[10px] leading-relaxed text-fg-3">
                          {JSON.stringify({ before: row.before, after: row.after, metadata: row.metadata }, null, 2)}
                        </pre>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-3">
                      <p>{row.target_type}</p>
                      <p className="mt-0.5 break-all font-mono text-[10px]">{shortId(row.target_id, 18)}</p>
                    </td>
                    <td className="max-w-[280px] px-4 py-3 text-xs text-fg-3">{summarize(row.reason, 120)}</td>
                    <td className="px-4 py-3 text-[10px] text-fg-3">
                      <p className="font-mono">{shortId(row.request_id, 14)}</p>
                      <p className="mt-0.5">{row.ip_address || 'no IP'}</p>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-fg-3">
          <span>{formatNumber(data?.total ?? 0)} entries · page {page} of {pageCount}</span>
          <div className="flex gap-2">
            <button type="button" onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} disabled={offset === 0} className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">Previous</button>
            <button type="button" onClick={() => setOffset(offset + PAGE_SIZE)} disabled={offset + PAGE_SIZE >= (data?.total ?? 0)} className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">Next</button>
          </div>
        </div>
      </div>
    </div>
  )
}
