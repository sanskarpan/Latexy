'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import {
  apiClient,
  type JobStateResponse,
  type ResumeStats,
  type UserAnalyticsResponse,
  type UserAnalyticsTimeseriesResponse,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'
import { ActivityAreaChart, FeatureUsageBars, StatusDonutChart } from '@/components/analytics/MetricCharts'

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
  const [recentJobs, setRecentJobs] = useState<JobStateResponse[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!sessionLoading && !session) {
      router.push('/login')
    }
  }, [session, sessionLoading, router])

  useEffect(() => {
    if (!session) return

    const fetchDashboardData = async () => {
      setLoading(true)
      try {
        const [analyticsData, timeseriesData, statsData, jobsData] = await Promise.all([
          apiClient.getMyAnalytics(selectedRange),
          apiClient.getMyAnalyticsTimeseries(selectedRange),
          apiClient.getResumeStats(),
          apiClient.listJobs(),
        ])

        setAnalytics(analyticsData)
        setTimeseries(timeseriesData)
        setStats(statsData)
        setRecentJobs([...(jobsData.jobs || [])].sort((a, b) => b.last_updated - a.last_updated).slice(0, 10))
      } catch (error) {
        if (process.env.NODE_ENV === 'development') {
          console.error('Failed to fetch dashboard data', error)
        }
      } finally {
        setLoading(false)
      }
    }

    fetchDashboardData()
  }, [session, selectedRange])

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
        label: 'Usage Velocity',
        value: `${avgDailyActions}/day`,
        note: 'Average tracked actions',
      },
    ]
  }, [analytics, stats, selectedRange])

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
        <section className="surface-panel edge-highlight mx-auto max-w-3xl p-8 text-center">
          <p className="overline">Analytics</p>
          <h1 className="mt-2 text-3xl font-semibold text-white">Usage Intelligence Dashboard</h1>
          <p className="mx-auto mt-3 max-w-xl text-zinc-400">
            Signed-in users get pipeline analytics, feature usage charts, and run-performance signals over configurable time windows.
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/login" className="btn-accent px-6 py-2.5 text-sm">
              Sign In
            </Link>
            <Link href="/" className="btn-ghost px-6 py-2.5 text-sm">
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
          <p className="overline">Dashboard</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Usage Intelligence</h1>
          <p className="mt-1 text-sm text-zinc-400">Detailed analytics for your personal resume optimization workflow.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {ranges.map((range) => (
            <button
              key={range.days}
              onClick={() => setSelectedRange(range.days)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.12em] transition ${
                selectedRange === range.days
                  ? 'border-orange-300/45 bg-orange-300/10 text-orange-200'
                  : 'border-white/10 bg-white/5 text-zinc-400 hover:border-white/20 hover:text-white'
              }`}
            >
              {range.label}
            </button>
          ))}
          <Link href="/workspace" className="btn-ghost px-4 py-1.5 text-xs">
            Workspace
          </Link>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {loading
          ? Array.from({ length: 4 }).map((_, index) => <div key={index} className="surface-card h-28 animate-pulse" />)
          : kpis.map((item) => (
              <article key={item.label} className="surface-card edge-highlight p-4">
                <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">{item.label}</p>
                <p className="mt-2 text-3xl font-semibold text-white">{item.value}</p>
                <p className="mt-1 text-xs text-zinc-400">{item.note}</p>
              </article>
            ))}
      </section>

      <div className="grid gap-6 xl:grid-cols-[1fr_340px]">
        <section className="space-y-6">
          <article className="surface-panel edge-highlight p-5">
            <div className="mb-3 flex items-end justify-between gap-4">
              <div>
                <h2 className="text-lg font-semibold text-white">Activity Trend</h2>
                <p className="text-xs text-zinc-500">Daily action density over the selected window</p>
              </div>
              <span className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-[10px] uppercase tracking-[0.14em] text-zinc-500">
                {selectedRange} day window
              </span>
            </div>
            {loading ? <div className="h-[280px] animate-pulse rounded-xl bg-white/5" /> : <ActivityAreaChart data={dailySeries} />}
          </article>

          <article className="surface-panel edge-highlight p-5">
            <div className="mb-3">
              <h2 className="text-lg font-semibold text-white">Feature Usage Mix</h2>
              <p className="text-xs text-zinc-500">Most used actions in your current range</p>
            </div>
            {loading ? <div className="h-[260px] animate-pulse rounded-xl bg-white/5" /> : <FeatureUsageBars data={featureSeries} />}
          </article>
        </section>

        <aside className="space-y-6">
          <article className="surface-panel edge-highlight p-5">
            <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-300">Run Status Distribution</h2>
            <div className="mt-4">{loading ? <div className="h-[220px] animate-pulse rounded-xl bg-white/5" /> : <StatusDonutChart data={statusSeries} />}</div>
          </article>

          <article className="surface-panel edge-highlight p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold uppercase tracking-[0.12em] text-zinc-300">Recent Runs</h2>
              <Link href="/workspace/history" className="text-[10px] uppercase tracking-[0.12em] text-orange-200 hover:text-orange-100">
                Full history
              </Link>
            </div>
            {loading ? (
              <div className="space-y-2">
                {Array.from({ length: 4 }).map((_, index) => (
                  <div key={index} className="h-14 animate-pulse rounded-lg bg-white/5" />
                ))}
              </div>
            ) : recentJobs.length === 0 ? (
              <p className="text-sm text-zinc-500">No recent jobs recorded.</p>
            ) : (
              <div className="space-y-2">
                {recentJobs.map((job, index) => (
                  <div key={job.job_id ?? `${job.last_updated}-${index}`} className="rounded-lg border border-white/10 bg-black/20 p-3">
                    <p className="text-xs uppercase tracking-[0.12em] text-zinc-500">{job.stage || 'Pipeline'}</p>
                    <p className="mt-1 text-sm capitalize text-zinc-200">{job.status}</p>
                    <p className="mt-1 text-xs text-zinc-500">{new Date(job.last_updated * 1000).toLocaleString()}</p>
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
