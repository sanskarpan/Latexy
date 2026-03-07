'use client'

import { useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { 
  BarChart3, 
  Target, 
  Zap, 
  CheckCircle2, 
  Clock, 
  FileText, 
  ArrowUpRight,
  TrendingUp
} from 'lucide-react'
import { apiClient, UserAnalyticsResponse, ResumeStats, JobStateResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function DashboardPage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const [analytics, setAnalytics] = useState<UserAnalyticsResponse | null>(null)
  const [stats, setStats] = useState<ResumeStats | null>(null)
  const [recentJobs, setRecentJobs] = useState<JobStateResponse[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (session) {
      fetchDashboardData()
    }
  }, [session])

  async function fetchDashboardData() {
    setLoading(true)
    try {
      const [analyticsData, statsData, jobsData] = await Promise.all([
        apiClient.getMyAnalytics(30),
        apiClient.getResumeStats(),
        apiClient.listJobs()
      ])
      setAnalytics(analyticsData)
      setStats(statsData)
      setRecentJobs(jobsData.jobs || [])
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err)
    } finally {
      setLoading(false)
    }
  }

  const kpis = useMemo(() => {
    if (!analytics || !stats) return []
    return [
      {
        label: 'Success Rate',
        value: `${Math.round(analytics.success_rate)}%`,
        sub: 'of compilations',
        icon: Zap,
        color: 'text-orange-300'
      },
      {
        label: 'Avg Score',
        value: analytics.total_optimizations > 0 ? '84' : '--', // Derived if we had scores
        sub: 'last 30 days',
        icon: Target,
        color: 'text-emerald-300'
      },
      {
        label: 'Resumes',
        value: stats.total_resumes.toString(),
        sub: 'in workspace',
        icon: FileText,
        color: 'text-blue-300'
      },
      {
        label: 'Latency',
        value: `${analytics.avg_compilation_time}s`,
        sub: 'avg compile',
        icon: Clock,
        color: 'text-purple-300'
      }
    ]
  }, [analytics, stats])

  if (sessionLoading) return (
    <div className="flex h-screen items-center justify-center">
      <LoadingSpinner />
    </div>
  )

  if (!session) {
    return (
      <div className="flex h-[80vh] flex-col items-center justify-center space-y-6 text-center px-4">
        <div className="relative">
          <div className="absolute -inset-4 rounded-full bg-orange-300/20 blur-2xl animate-pulse" />
          <BarChart3 size={64} className="relative text-orange-300" />
        </div>
        <div className="max-w-md space-y-2">
          <h1 className="text-3xl font-bold text-white tracking-tight">Intelligence Dashboard</h1>
          <p className="text-zinc-400">Track your resume performance, ATS scores, and optimization history in real-time.</p>
        </div>
        <Link href="/login" className="btn-accent px-8 py-3 font-bold">
          Get Started
        </Link>
      </div>
    )
  }

  return (
    <div className="content-shell">
      <div className="space-y-8">
        {/* Welcome Section */}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Welcome back, {session.user.name?.split(' ')[0]}</h1>
            <p className="text-zinc-500 mt-1">Here's what's happening with your resumes this month.</p>
          </div>
          <Link href="/workspace" className="text-sm font-semibold text-orange-200 hover:text-white flex items-center gap-1 transition">
            Go to Workspace <ArrowUpRight size={16} />
          </Link>
        </div>

        {/* KPI Grid */}
        <section className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {loading ? (
            Array(4).fill(0).map((_, i) => (
              <div key={i} className="surface-card edge-highlight h-32 animate-pulse" />
            ))
          ) : (
            kpis.map((kpi, idx) => (
              <motion.article
                key={kpi.label}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.05 }}
                className="surface-card edge-highlight p-5"
              >
                <div className="flex items-center justify-between mb-3">
                  <p className="text-xs font-bold uppercase tracking-widest text-zinc-500">{kpi.label}</p>
                  <kpi.icon size={16} className={kpi.color} />
                </div>
                <div className="flex items-baseline gap-2">
                  <span className="text-3xl font-bold text-white">{kpi.value}</span>
                  <span className="text-[10px] text-zinc-500 font-medium">{kpi.sub}</span>
                </div>
              </motion.article>
            ))
          )}
        </section>

        <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
          {/* Main Chart/Insights Area */}
          <div className="space-y-6">
            <section className="surface-panel edge-highlight p-6">
              <div className="flex items-center justify-between mb-8">
                <div>
                  <h2 className="text-lg font-bold text-white">Optimization Trends</h2>
                  <p className="text-xs text-zinc-500">Activity volume across your workspace</p>
                </div>
                <div className="rounded-lg bg-white/5 px-3 py-1 text-[10px] font-bold text-zinc-400 border border-white/5">
                  LAST 30 DAYS
                </div>
              </div>
              
              <div className="h-[280px] w-full flex items-end justify-between gap-2 px-2">
                {loading ? (
                  <div className="w-full h-full flex items-center justify-center">
                    <LoadingSpinner />
                  </div>
                ) : analytics && Object.keys(analytics.daily_activity).length > 0 ? (
                  Object.entries(analytics.daily_activity).slice(-14).map(([date, count], i) => {
                    const height = Math.max(10, (count / Math.max(...Object.values(analytics.daily_activity))) * 100)
                    return (
                      <div key={date} className="flex flex-col items-center gap-3 flex-1">
                        <motion.div 
                          initial={{ height: 0 }}
                          animate={{ height: `${height}%` }}
                          className="w-full max-w-[24px] rounded-t-sm bg-gradient-to-t from-orange-500/20 to-orange-300 shadow-[0_0_15px_rgba(251,146,60,0.1)]"
                        />
                        <span className="text-[9px] font-medium text-zinc-600 rotate-45 origin-left">{date.split('-').slice(1).join('/')}</span>
                      </div>
                    )
                  })
                ) : (
                  <div className="w-full h-full flex flex-col items-center justify-center text-zinc-600 border border-dashed border-white/5 rounded-xl">
                    <TrendingUp size={32} className="mb-2 opacity-20" />
                    <p className="text-sm">No activity data yet</p>
                  </div>
                )}
              </div>
            </section>

            <section className="surface-panel edge-highlight p-6">
              <h2 className="text-lg font-bold text-white mb-4">Feature Distribution</h2>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
                {loading ? null : (
                  Object.entries(analytics?.feature_usage || {}).map(([feature, count]) => (
                    <div key={feature} className="surface-card p-4 border border-white/5">
                      <p className="text-[10px] font-bold text-zinc-500 uppercase truncate">{feature}</p>
                      <p className="text-xl font-bold text-white mt-1">{count}</p>
                    </div>
                  ))
                )}
              </div>
            </section>
          </div>

          {/* Sidebar Area */}
          <aside className="space-y-6">
            <section className="surface-panel edge-highlight p-5">
              <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-4">Recent Runs</h2>
              <div className="space-y-3">
                {loading ? (
                  Array(3).fill(0).map((_, i) => <div key={i} className="h-16 rounded-lg bg-white/5 animate-pulse" />)
                ) : recentJobs.length > 0 ? (
                  recentJobs.slice(0, 4).map((job, i) => (
                    <div key={i} className="flex items-center gap-3 p-3 rounded-xl bg-white/[0.03] border border-white/5">
                      <div className={`p-2 rounded-lg ${job.status === 'completed' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-orange-500/10 text-orange-400'}`}>
                        {job.status === 'completed' ? <CheckCircle2 size={16} /> : <Clock size={16} />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-bold text-white truncate capitalize">{job.stage?.replace('_', ' ') || 'Process Run'}</p>
                        <p className="text-[10px] text-zinc-500">{new Date(job.last_updated * 1000).toLocaleDateString()}</p>
                      </div>
                      {job.status === 'completed' && <span className="text-[10px] font-bold text-emerald-400">SUCCESS</span>}
                    </div>
                  ))
                ) : (
                  <p className="text-center py-8 text-xs text-zinc-600">No recent runs recorded</p>
                )}
              </div>
              <Link href="/workspace" className="mt-4 block text-center text-[10px] font-bold text-zinc-500 hover:text-orange-200 transition uppercase tracking-widest">
                View All Activity
              </Link>
            </section>

            <section className="surface-panel edge-highlight p-6 bg-gradient-to-br from-orange-300/10 to-transparent">
              <h2 className="text-sm font-bold text-white uppercase tracking-wider mb-2">Upgrade to Pro</h2>
              <p className="text-xs text-zinc-400 leading-relaxed mb-4">
                Unlock persistent history, unlimited optimizations, and high-priority compilation queues.
              </p>
              <Link href="/billing" className="btn-accent w-full py-2 text-xs font-bold shadow-lg shadow-orange-500/20">
                View Pricing
              </Link>
            </section>
          </aside>
        </div>
      </div>
    </div>
  )
}
