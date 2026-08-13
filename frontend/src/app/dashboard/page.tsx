'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  apiClient,
  type CoverLetterStatsResponse,
  type JobStateResponse,
  type ResumeStats,
  type UserAnalyticsResponse,
  type UserAnalyticsTimeseriesResponse,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'
import { ActivityAreaChart, FeatureUsageBars, StatusDonutChart } from '@/components/analytics/MetricCharts'
import { JobQueue } from '@/components/JobQueue'

const ranges = [
  { label: '7D', days: 7 },
  { label: '30D', days: 30 },
  { label: '90D', days: 90 },
]

export default function DashboardPage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const router = useRouter()
  const [selectedRange, setSelectedRange] = useState(30)
  const [analytics, setAnalytics] = useState<UserAnalyticsResponse | null>(null)
  const [timeseries, setTimeseries] = useState<UserAnalyticsTimeseriesResponse | null>(null)
  const [stats, setStats] = useState<ResumeStats | null>(null)
  const [clStats, setClStats] = useState<CoverLetterStatsResponse | null>(null)
  const [recentJobs, setRecentJobs] = useState<JobStateResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionLoading && !session) {
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
    }
  }, [session, sessionLoading, router])

  const fetchDashboardData = useCallback(async () => {
    if (!session) return
    setLoading(true)
    setError(null)
    try {
      const [analyticsData, timeseriesData, statsData, jobsData, clStatsData] = await Promise.all([
        apiClient.getMyAnalytics(selectedRange),
        apiClient.getMyAnalyticsTimeseries(selectedRange),
        apiClient.getResumeStats(),
        apiClient.listJobs(),
        apiClient.getCoverLetterStats().catch(() => ({ total: 0 })),
      ])

      setAnalytics(analyticsData)
      setTimeseries(timeseriesData)
      setStats(statsData)
      setClStats(clStatsData)
      setRecentJobs([...(jobsData.jobs || [])].sort((a, b) => b.last_updated - a.last_updated).slice(0, 10))
    } catch (err) {
      if (process.env.NODE_ENV === 'development') {
        console.error('Failed to fetch dashboard data', err)
      }
      setError(err instanceof Error ? err.message : 'Failed to load dashboard data')
    } finally {
      setLoading(false)
    }
  }, [session, selectedRange])

  useEffect(() => {
    fetchDashboardData()
  }, [fetchDashboardData])

  const dailySeries = useMemo(() => {
    if (timeseries?.activity_series?.length) {
      return timeseries.activity_series.map((point) => ({ date: point.date, value: point.events }))
    }
    if (!analytics) return []
    return Object.entries(analytics.daily_activity)
      .sort(([left], [right]) => new Date(left).getTime() - new Date(right).getTime())
      .map(([date, value]) => ({ date, value }))
  }, [timeseries, analytics])

  const featureSeries = useMemo(() => {
    if (timeseries?.feature_series?.length) {
      return timeseries.feature_series.map((item) => ({ name: item.feature, value: item.count }))
    }
    if (!analytics) return []
    return Object.entries(analytics.feature_usage).map(([name, value]) => ({ name, value }))
  }, [timeseries, analytics])

  const statusSeries = useMemo(() => {
    if (timeseries?.status_distribution) {
      return Object.entries(timeseries.status_distribution).map(([name, value]) => ({ name, value }))
    }
    const counts: Record<string, number> = { completed: 0, processing: 0, queued: 0, failed: 0, cancelled: 0 }
    recentJobs.forEach((job) => {
      counts[job.status] = (counts[job.status] || 0) + 1
    })
    return Object.entries(counts).map(([name, value]) => ({ name, value }))
  }, [timeseries, recentJobs])

  const kpis = useMemo(() => {
    if (!analytics || !stats) return []

    const activeDays = Object.keys(analytics.daily_activity).length
    const avgDailyActions = activeDays > 0 ? (Object.values(analytics.daily_activity).reduce((sum, value) => sum + value, 0) / activeDays).toFixed(1) : '0.0'

    return [
      {
        label: 'Success Rate',
        value: `${Math.round(analytics.success_rate)}%`,
        note: 'Compilation reliability',
      },
      {
        label: 'Avg Compile Latency',
        value: `${analytics.avg_compilation_time}s`,
        note: `For last ${selectedRange} days`,
      },
      {
        label: 'Resume Count',
        value: `${stats.total_resumes}`,
        note: 'Documents in workspace',
      },
      {
        label: 'Cover Letters',
        value: `${clStats?.total ?? 0}`,
        note: 'Generated cover letters',
      },
      {
        label: 'Usage Velocity',
        value: `${avgDailyActions}/day`,
        note: 'Average tracked actions',
      },
    ]
  }, [analytics, stats, clStats, selectedRange])

  if (sessionLoading) {
    return (
      <div className="flex h-[70vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!session) {
    return (
      <div className="content-shell">
        <section className="rounded-[var(--radius-lg)] border border-line bg-surface mx-auto max-w-3xl p-8 text-center">
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Analytics</p>
          <h1 className="mt-2 text-3xl font-semibold text-fg">Usage Intelligence Dashboard</h1>
          <p className="mx-auto mt-3 max-w-xl text-fg-2">
            Signed-in users get pipeline analytics, feature usage charts, and run-performance signals over configurable time windows.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/login" className="rounded-[var(--radius-md)] bg-accent px-6 py-2.5 text-sm font-semibold text-accent-fg hover:brightness-110">
              Sign In
            </Link>
            <Link href="/" className="rounded-[var(--radius-md)] border border-line-2 px-6 py-2.5 text-sm text-fg hover:bg-surface-2">
              View Public Site
            </Link>
          </div>
        </section>
      </div>
    )
  }

  return (
    <div className="content-shell space-y-6">
      <section className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-ui text-xs uppercase tracking-[0.16em] text-fg-3">Dashboard</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-fg">Usage Intelligence</h1>
          <p className="mt-1 text-sm text-fg-2">Detailed analytics for your personal resume optimization workflow.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {ranges.map((range) => (
            <button
              key={range.days}
              onClick={() => setSelectedRange(range.days)}
              aria-pressed={selectedRange === range.days}
              aria-label={`Show last ${range.days} days`}
              className={`rounded-[var(--radius-md)] border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] transition ${
                selectedRange === range.days
                  ? 'border-accent bg-accent-soft text-accent-strong'
                  : 'border-line bg-surface-2 text-fg-2 hover:border-line-2 hover:text-fg'
              }`}
            >
              {range.label}
            </button>
          ))}
          <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line-2 px-4 py-1.5 text-xs text-fg hover:bg-surface-2">
            Workspace
          </Link>
        </div>
      </section>

      {error && !loading && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-lg)] border border-err/30 bg-err/10 px-4 py-3">
          <div>
            <p className="text-sm font-semibold text-err">Couldn&apos;t load dashboard data</p>
            <p className="text-xs text-err/80">{error}</p>
          </div>
          <button
            onClick={fetchDashboardData}
            className="rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-4 py-1.5 text-xs font-semibold text-err transition hover:bg-err/20"
          >
            Retry
          </button>
        </div>
      )}

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        {loading ? (
          Array.from({ length: 5 }).map((_, index) => <div key={index} className="rounded-[var(--radius-lg)] border border-line bg-surface h-28 animate-pulse" />)
        ) : error ? (
          <article className="rounded-[var(--radius-lg)] border border-dashed border-err/30 bg-surface p-6 text-center md:col-span-2 xl:col-span-5">
            <p className="text-sm font-semibold text-err">Couldn&apos;t load metrics</p>
            <p className="mt-1 text-xs text-fg-3">Your metrics are unavailable right now. Use retry above to try again.</p>
          </article>
        ) : (
          kpis.map((item) => (
              <article key={item.label} className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-fg-3">{item.label}</p>
                <p className="mt-2 text-3xl font-semibold text-fg">{item.value}</p>
                <p className="mt-1 text-xs text-fg-2">{item.note}</p>
              </article>
            ))
        )}
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <section className="space-y-6">
          <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="mb-3 flex items-end justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-fg">Activity Trend</h2>
                <p className="text-xs text-fg-3">Daily action density over the selected window</p>
              </div>
              <span className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-fg-3">
                {selectedRange} day window
              </span>
            </div>
            {loading ? (
              <div className="h-[280px] animate-pulse rounded-[var(--radius-lg)] bg-surface-2" />
            ) : error ? (
              <ChartUnavailable heightClass="h-[280px]" onRetry={fetchDashboardData} />
            ) : (
              <ActivityAreaChart data={dailySeries} />
            )}
          </article>

          <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="mb-3">
              <h2 className="text-lg font-semibold text-fg">Feature Usage Mix</h2>
              <p className="text-xs text-fg-3">Most used actions in your current range</p>
            </div>
            {loading ? (
              <div className="h-[260px] animate-pulse rounded-[var(--radius-lg)] bg-surface-2" />
            ) : error ? (
              <ChartUnavailable heightClass="h-[260px]" onRetry={fetchDashboardData} />
            ) : (
              <FeatureUsageBars data={featureSeries} />
            )}
          </article>

          <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <JobQueue maxJobs={10} showFilters={false} showSearch={false} />
          </article>
        </section>

        <aside className="space-y-6">
          <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2">Run Status Distribution</h2>
            <div className="mt-4">
              {loading ? (
                <div className="h-[220px] animate-pulse rounded-[var(--radius-lg)] bg-surface-2" />
              ) : error ? (
                <ChartUnavailable heightClass="h-[220px]" onRetry={fetchDashboardData} />
              ) : (
                <StatusDonutChart data={statusSeries} />
              )}
            </div>
          </article>

          <article className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-fg-2">Recent Runs</h2>
              <Link href="/workspace/history" className="text-[10px] uppercase tracking-[0.12em] text-accent-strong hover:brightness-110">
                Full history
              </Link>
            </div>
            {loading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="h-14 animate-pulse rounded-[var(--radius-md)] bg-surface-2" />
                ))}
              </div>
            ) : recentJobs.length === 0 ? (
              <p className="text-sm text-fg-3">No recent jobs recorded.</p>
            ) : (
              <div className="space-y-2">
                {recentJobs.map((job, index) => (
                  <div key={job.job_id ?? `${job.last_updated}-${index}`} className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
                    <p className="text-xs uppercase tracking-[0.12em] text-fg-3">{job.stage || 'Pipeline'}</p>
                    <p className="mt-1 text-sm capitalize text-fg">{job.status}</p>
                    <p className="mt-1 text-xs text-fg-3">{new Date(job.last_updated * 1000).toLocaleString()}</p>
                  </div>
                ))}
              </div>
            )}
          </article>
        </aside>
      </div>
    </div>
  )
}

function ChartUnavailable({ heightClass, onRetry }: { heightClass: string; onRetry: () => void }) {
  return (
    <div className={`flex ${heightClass} flex-col items-center justify-center gap-3 rounded-[var(--radius-md)] border border-dashed border-err/30 text-center`}>
      <p className="text-sm font-semibold text-err">Couldn&apos;t load</p>
      <button
        onClick={onRetry}
        className="rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-3 py-1 text-xs font-semibold text-err transition hover:bg-err/20"
      >
        Retry
      </button>
    </div>
  )
}
