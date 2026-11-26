'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  apiClient,
  type AdminActivityEvent,
  type AdminActivityFeedResponse,
} from '@/lib/api-client'
import {
  ACTIVITY_CATEGORY_META,
  ACTIVITY_PAGE_SIZE,
  ACTIVITY_POLL_MS,
  MAX_ACTIVITY_ROWS,
  formatActivityTime,
  mergeActivityRows,
} from '@/lib/admin-activity'

const MAX_CATCH_UP_PAGES = 5

type FeedMode = 'live' | 'fallback'

function categoryBadge(event: AdminActivityEvent) {
  const meta = ACTIVITY_CATEGORY_META[event.category]
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${meta.badgeClassName}`}
    >
      {meta.label}
    </span>
  )
}

export default function AdminActivityFeed() {
  const [rows, setRows] = useState<AdminActivityEvent[]>([])
  const [paused, setPaused] = useState(false)
  const [mode, setMode] = useState<FeedMode | null>(null)
  const [detail, setDetail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [hasLoaded, setHasLoaded] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<string | null>(null)
  const [retryNonce, setRetryNonce] = useState(0)

  const cursorRef = useRef<string | null>(null)
  const modeRef = useRef<FeedMode | null>(null)
  const seenRef = useRef<Set<string>>(new Set())
  const inFlightRef = useRef(false)

  const applyPage = useCallback((page: AdminActivityFeedResponse) => {
    if (page.next_cursor) cursorRef.current = page.next_cursor

    const switchingMode = modeRef.current !== null && modeRef.current !== page.mode
    modeRef.current = page.mode
    setMode(page.mode)
    setDetail(page.detail)

    if (switchingMode) {
      // Live and fallback rows use different opaque id prefixes. Replacing the
      // buffer avoids showing the same underlying activity twice after a mode
      // switch.
      seenRef.current = new Set(page.items.map((item) => item.id))
      setRows(mergeActivityRows([], page.items))
    } else {
      const fresh = page.items.filter((item) => !seenRef.current.has(item.id))
      for (const item of fresh) seenRef.current.add(item.id)
      if (fresh.length > 0) {
        setRows((previous) => mergeActivityRows(previous, fresh))
      }
    }

    setHasLoaded(true)
    setLastUpdated(page.generated_at)
  }, [])

  useEffect(() => {
    if (paused) return

    let cancelled = false
    let timer: number | null = null

    const tick = async () => {
      if (cancelled || inFlightRef.current) return
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      inFlightRef.current = true
      try {
        let pages = 0
        let more = true
        while (more && pages < MAX_CATCH_UP_PAGES && !cancelled) {
          const page = await apiClient.getAdminActivityFeed({
            cursor: cursorRef.current,
            limit: ACTIVITY_PAGE_SIZE,
          })
          if (cancelled) return
          applyPage(page)
          more = page.has_more
          pages += 1
        }
        if (!cancelled) setError(null)
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Live activity feed unavailable')
        }
      } finally {
        inFlightRef.current = false
      }
    }

    void tick()
    timer = window.setInterval(() => {
      void tick()
    }, ACTIVITY_POLL_MS)

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void tick()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      cancelled = true
      if (timer !== null) window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [applyPage, paused, retryNonce])

  const status = paused
    ? { label: 'Paused', tone: 'text-fg-3 border-line bg-surface-2' }
    : error
      ? { label: 'Reconnecting', tone: 'text-err border-err/30 bg-err/10' }
      : mode === 'fallback'
        ? { label: 'Fallback', tone: 'text-warn border-warn/30 bg-warn/10' }
        : hasLoaded
          ? { label: 'Live', tone: 'text-ok border-ok/30 bg-ok/10' }
          : { label: 'Connecting…', tone: 'text-fg-3 border-line bg-surface-2' }

  const degraded = mode === 'fallback' || Boolean(error)

  return (
    <section
      id="admin-activity-feed"
      aria-labelledby="admin-activity-feed-heading"
      className="overflow-hidden rounded-[var(--radius-lg)] border border-line bg-surface"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <h3 id="admin-activity-feed-heading" className="text-sm font-semibold text-fg">
            Live activity
          </h3>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-fg-3">
            Typed signups, payments, compiles, optimizations and errors. Updates every{' '}
            {ACTIVITY_POLL_MS / 1000}s. Only opaque ids and event names are shown; document
            content, prompts, emails and payment credentials never leave the backend.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span
            role="status"
            aria-live="polite"
            className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider ${status.tone}`}
          >
            {status.label}
          </span>
          <button
            type="button"
            aria-pressed={paused}
            onClick={() => setPaused((value) => !value)}
            className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2"
          >
            {paused ? 'Resume' : 'Pause'}
          </button>
        </div>
      </div>

      {mode === 'fallback' && (
        <div
          role="status"
          className="border-b border-warn/30 bg-warn/10 px-5 py-3 text-xs text-warn"
        >
          <span className="font-semibold">Fallback mode.</span>{' '}
          {detail ?? 'Live activity sources are unavailable; showing recent first-party usage events.'}
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 border-b border-err/20 bg-err/[0.06] px-5 py-3 text-xs text-err"
        >
          <span>
            <span className="font-semibold">Live feed interrupted.</span> Keeping the last rendered
            rows and retrying automatically: {error}
          </span>
          <button
            type="button"
            onClick={() => setRetryNonce((value) => value + 1)}
            className="rounded-[var(--radius-md)] border border-err/30 px-3 py-1.5 text-xs font-medium text-err hover:bg-err/10"
          >
            Retry now
          </button>
        </div>
      )}

      {!hasLoaded && !paused && !error ? (
        <div role="status" className="px-5 py-8 text-center text-sm text-fg-3">
          Connecting to the live activity feed…
        </div>
      ) : rows.length === 0 ? (
        <div className="px-5 py-8 text-center text-sm text-fg-3">
          {paused
            ? 'Paused. Resume to check for new activity.'
            : 'No matching activity yet. Signups, payments, compiles, optimizations and errors will appear here.'}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-sm">
            <caption className="sr-only">
              Live redacted admin activity, newest first. The buffer is bounded to the newest{' '}
              {MAX_ACTIVITY_ROWS} rows.
            </caption>
            <thead>
              <tr className="border-b border-line text-[10px] uppercase tracking-wider text-fg-3">
                <th scope="col" className="px-5 py-3 text-left font-semibold">Time</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Category</th>
                <th scope="col" className="px-4 py-3 text-left font-semibold">Event</th>
                <th scope="col" className="px-4 py-3 text-right font-semibold">Record</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((event) => (
                <tr key={event.id} className="border-t border-line align-middle">
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-fg-3">
                    <time dateTime={event.created_at} title={new Date(event.created_at).toLocaleString()}>
                      {formatActivityTime(event.created_at)}
                    </time>
                  </td>
                  <td className="px-4 py-2.5">{categoryBadge(event)}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-fg">{event.event}</td>
                  <td className="px-4 py-2.5 text-right">
                    {event.href ? (
                      <a
                        href={event.href}
                        className="text-xs font-medium text-accent-strong hover:underline"
                      >
                        Open
                      </a>
                    ) : (
                      <span className="text-xs text-fg-3">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line px-5 py-2.5 text-[10px] text-fg-3">
        <span>
          {rows.length === 0 ? 'No rows' : `${rows.length} of ${MAX_ACTIVITY_ROWS} rows`} · bounded
          buffer
        </span>
        <span>
          {paused
            ? 'Polling paused.'
            : degraded
              ? 'Degraded feed; automatic retry is active.'
              : lastUpdated
                ? `Updated ${new Date(lastUpdated).toLocaleTimeString()}`
                : 'Waiting for the first poll.'}
        </span>
      </div>
    </section>
  )
}
