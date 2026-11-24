'use client'

import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { apiClient, type AdminAuditEntry } from '@/lib/api-client'
import { formatDateTime, formatNumber, shortId, summarize } from './admin-format'

const PAGE_SIZE = 50

type ChangeFilters = {
  key: string
  target_id: string
  actor_user_id: string
  action: string
  created_after: string
  created_before: string
}

const EMPTY_FILTERS: ChangeFilters = {
  key: '',
  target_id: '',
  actor_user_id: '',
  action: '',
  created_after: '',
  created_before: '',
}

function toIso(value: string): string {
  if (!value) return ''
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? '' : parsed.toISOString()
}

function diffValue(value: Record<string, unknown> | null): string {
  return value == null ? '—' : JSON.stringify(value, null, 2)
}

export default function AdminChangeHistory() {
  const [items, setItems] = useState<AdminAuditEntry[]>([])
  const [total, setTotal] = useState(0)
  const [limit, setLimit] = useState(PAGE_SIZE)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState<ChangeFilters>(EMPTY_FILTERS)
  const [draft, setDraft] = useState<ChangeFilters>(EMPTY_FILTERS)
  const [reloadKey, setReloadKey] = useState(0)
  const generation = useRef(0)

  const loadPage = useCallback(
    async (cursor: string | null, append: boolean) => {
      const current = ++generation.current
      if (append) {
        setLoadingMore(true)
      } else {
        setLoading(true)
        setItems([])
        setNextCursor(null)
        setHasMore(false)
      }
      setError(null)
      try {
        const next = await apiClient.getAdminChangeHistory({
          key: applied.key || undefined,
          target_id: applied.target_id || undefined,
          actor_user_id: applied.actor_user_id || undefined,
          action: applied.action || undefined,
          created_after: applied.created_after || undefined,
          created_before: applied.created_before || undefined,
          limit: PAGE_SIZE,
          cursor: cursor || undefined,
        })
        if (generation.current !== current) return
        setItems((previous) => (append ? [...previous, ...next.items] : next.items))
        setTotal(next.total)
        setLimit(next.limit)
        setNextCursor(next.next_cursor)
        setHasMore(next.has_more)
      } catch (err) {
        if (generation.current === current) {
          setError(err instanceof Error ? err.message : 'Failed to load change history')
        }
      } finally {
        if (generation.current === current) {
          setLoading(false)
          setLoadingMore(false)
        }
      }
    },
    [applied],
  )

  useEffect(() => {
    void loadPage(null, false)
  }, [loadPage, reloadKey])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setApplied({
      key: draft.key.trim(),
      target_id: draft.target_id.trim(),
      actor_user_id: draft.actor_user_id.trim(),
      action: draft.action.trim(),
      created_after: toIso(draft.created_after),
      created_before: toIso(draft.created_before),
    })
  }

  const resetFilters = () => {
    setApplied(EMPTY_FILTERS)
    setDraft(EMPTY_FILTERS)
    setReloadKey((value) => value + 1)
  }

  const updateDraft = (key: keyof ChangeFilters, value: string) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
  }

  return (
    <section aria-labelledby="admin-change-history-heading" className="space-y-4">
      <div>
        <h2 id="admin-change-history-heading" className="text-lg font-semibold text-fg">
          Flag &amp; entitlement change history
        </h2>
        <p className="mt-1 max-w-3xl text-xs leading-relaxed text-fg-3">
          Read-only, append-only history for feature flags, kill-switches, plan cells and account-role cells. Every row
          keeps the operator, timestamp, reason and the changed safe fields. There is no edit or delete control.
        </p>
      </div>

      <form
        className="grid gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-4 sm:grid-cols-2 lg:grid-cols-4"
        onSubmit={applyFilters}
      >
        <label className="text-[11px] text-fg-2">
          Feature key
          <input
            value={draft.key}
            onChange={(event) => updateDraft('key', event.target.value)}
            placeholder="cover_letters"
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          Target ID
          <input
            value={draft.target_id}
            onChange={(event) => updateDraft('target_id', event.target.value)}
            placeholder="free:cover_letters"
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          Actor user ID
          <input
            value={draft.actor_user_id}
            onChange={(event) => updateDraft('actor_user_id', event.target.value)}
            placeholder="UUID"
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          Action
          <input
            value={draft.action}
            onChange={(event) => updateDraft('action', event.target.value)}
            placeholder="feature_flag.update"
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          Changed after
          <input
            type="datetime-local"
            value={draft.created_after}
            onChange={(event) => updateDraft('created_after', event.target.value)}
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <label className="text-[11px] text-fg-2">
          Changed before
          <input
            type="datetime-local"
            value={draft.created_before}
            onChange={(event) => updateDraft('created_before', event.target.value)}
            className="mt-1 w-full rounded border border-line bg-bg px-3 py-2 font-mono text-xs text-fg"
          />
        </label>
        <div className="flex items-end gap-2 sm:col-span-2">
          <button
            type="submit"
            className="min-h-[38px] flex-1 rounded border border-line px-3 py-2 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            Apply filters
          </button>
          <button
            type="button"
            onClick={resetFilters}
            className="min-h-[38px] rounded border border-line px-3 py-2 text-xs text-fg-3 hover:bg-surface-2"
          >
            Reset
          </button>
        </div>
      </form>

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--radius-md)] border border-err/20 bg-err/[0.06] px-4 py-3 text-xs text-err"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setReloadKey((value) => value + 1)}
            className="rounded border border-err/30 px-2.5 py-1 font-medium"
          >
            Retry
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface">
        {loading && items.length === 0 ? (
          <div className="space-y-2 p-4">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="h-16 animate-pulse rounded-md bg-surface-2" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <p className="px-5 py-12 text-center text-sm text-fg-3">No flag or entitlement changes match these filters.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1000px] border-collapse text-sm">
              <caption className="sr-only">Immutable flag and entitlement change history, newest first</caption>
              <thead>
                <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Time</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Actor</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Target</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Old value</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">New value</th>
                  <th scope="col" className="px-4 py-3 text-left font-semibold">Reason</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr key={row.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-4 py-3 text-xs text-fg-3">{formatDateTime(row.created_at)}</td>
                    <td className="px-4 py-3 text-xs text-fg-2">
                      <p className="break-all">{row.actor_email || shortId(row.actor_user_id, 12)}</p>
                      <p className="mt-0.5 font-mono text-[10px] text-fg-3">{shortId(row.actor_user_id, 12)}</p>
                    </td>
                    <td className="px-4 py-3 text-xs text-fg-3">
                      <p className="font-mono text-[10px] text-fg-2">{row.action}</p>
                      <p className="mt-1">{row.target_type}</p>
                      <p className="mt-0.5 break-all font-mono text-[10px]">{shortId(row.target_id, 32)}</p>
                    </td>
                    <td className="px-4 py-3">
                      <pre className="max-h-56 max-w-[260px] overflow-auto whitespace-pre-wrap rounded border border-line bg-surface-2/60 p-2 text-[10px] leading-relaxed text-fg-3">
                        {diffValue(row.before)}
                      </pre>
                    </td>
                    <td className="px-4 py-3">
                      <pre className="max-h-56 max-w-[260px] overflow-auto whitespace-pre-wrap rounded border border-line bg-surface-2/60 p-2 text-[10px] leading-relaxed text-fg-3">
                        {diffValue(row.after)}
                      </pre>
                    </td>
                    <td className="max-w-[280px] px-4 py-3 text-xs text-fg-3">{summarize(row.reason, 240)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 text-xs text-fg-3">
          <span>
            {formatNumber(total)} changes · showing {formatNumber(items.length)} · page size {formatNumber(limit)}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setReloadKey((value) => value + 1)}
              disabled={loading}
              className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={() => {
                if (nextCursor) void loadPage(nextCursor, true)
              }}
              disabled={!hasMore || !nextCursor || loading || loadingMore}
              className="rounded border border-line px-3 py-1.5 font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              {loadingMore ? 'Loading…' : 'Load more'}
            </button>
          </div>
        </div>
      </div>
    </section>
  )
}
