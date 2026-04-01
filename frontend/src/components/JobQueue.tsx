'use client'

import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Clock,
  CheckCircle,
  XCircle,
  Loader2,
  Play,
  Square,
  RefreshCw,
  Search,
  MoreHorizontal,
  FileText,
  Zap,
  Target,
  Eye,
} from 'lucide-react'
import { useJobManagement } from '@/hooks/useJobManagement'
import { useJobStatus } from '@/hooks/useJobStatus'

interface JobQueueProps {
  maxJobs?: number
  showFilters?: boolean
  showSearch?: boolean
  onJobClick?: (jobId: string) => void
  onJobComplete?: (jobId: string, result: any) => void
  className?: string
}

const jobTypeConfig = {
  latex_compilation: {
    icon: FileText,
    label: 'LaTeX Compilation',
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
  },
  llm_optimization: {
    icon: Zap,
    label: 'LLM Optimization',
    color: 'text-orange-300',
    bgColor: 'bg-orange-500/10',
  },
  combined: {
    icon: Play,
    label: 'Optimize & Compile',
    color: 'text-purple-300',
    bgColor: 'bg-purple-500/10',
  },
  ats_scoring: {
    icon: Target,
    label: 'ATS Scoring',
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
  },
  jd_analysis: {
    icon: Search,
    label: 'JD Analysis',
    color: 'text-indigo-300',
    bgColor: 'bg-indigo-500/10',
  },
}

const statusConfig = {
  pending: {
    icon: Clock,
    color: 'text-yellow-300',
    bgColor: 'bg-yellow-500/10',
    ringColor: 'ring-yellow-400/20',
    label: 'Pending',
  },
  processing: {
    icon: Loader2,
    color: 'text-blue-400',
    bgColor: 'bg-blue-500/10',
    ringColor: 'ring-blue-400/20',
    label: 'Processing',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/10',
    ringColor: 'ring-emerald-400/20',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-rose-400',
    bgColor: 'bg-rose-500/10',
    ringColor: 'ring-rose-400/20',
    label: 'Failed',
  },
  cancelled: {
    icon: Square,
    color: 'text-zinc-400',
    bgColor: 'bg-zinc-500/10',
    ringColor: 'ring-zinc-400/20',
    label: 'Cancelled',
  },
}

interface JobItemProps {
  job: any
  onJobClick?: (jobId: string) => void
  onJobComplete?: (jobId: string, result: any) => void
}

const JobItem: React.FC<JobItemProps> = ({ job, onJobClick, onJobComplete }) => {
  const { cancel } = useJobStatus(job.job_id, {
    onComplete: (result) => {
      onJobComplete?.(job.job_id, result)
    },
  })

  const jobType = job.metadata?.job_type || 'latex_compilation'
  const typeConf = jobTypeConfig[jobType as keyof typeof jobTypeConfig] || jobTypeConfig.latex_compilation
  const statConf = statusConfig[job.status as keyof typeof statusConfig] || statusConfig.pending

  const TypeIcon = typeConf.icon
  const StatusIcon = statConf.icon

  const formatTime = (timestamp?: number) => {
    if (!timestamp) return 'Unknown'
    const diff = Date.now() - timestamp * 1000
    if (diff < 60_000) return 'Just now'
    if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`
    if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`
    return new Date(timestamp * 1000).toLocaleDateString()
  }

  const canCancel = !['completed', 'failed', 'cancelled'].includes(job.status)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      className="rounded-xl border border-white/[0.07] bg-white/[0.02] p-4 transition hover:border-white/15 cursor-pointer"
      onClick={() => onJobClick?.(job.job_id)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          <div className={`w-9 h-9 ${typeConf.bgColor} rounded-lg flex items-center justify-center shrink-0`}>
            <TypeIcon className={`w-4 h-4 ${typeConf.color}`} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-0.5">
              <h3 className="text-sm font-medium text-zinc-100 truncate">{typeConf.label}</h3>
              <span
                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold ring-1 ${statConf.color} ${statConf.bgColor} ${statConf.ringColor}`}
              >
                <StatusIcon className={`w-3 h-3 ${job.status === 'processing' ? 'animate-spin' : ''}`} />
                {statConf.label}
              </span>
            </div>

            <div className="flex items-center gap-3 text-xs text-zinc-500">
              <span className="font-mono">{job.job_id.substring(0, 8)}</span>
              <span>{formatTime(job.created_at ?? job.last_updated)}</span>
              {job.progress !== undefined && <span>{job.progress}%</span>}
            </div>

            {job.message && (
              <p className="mt-1 text-xs text-zinc-500 truncate">{job.message}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1 ml-3 shrink-0">
          {job.status === 'completed' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
              }}
              className="rounded-lg p-2 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
            >
              <Eye className="w-4 h-4" />
            </button>
          )}
          {canCancel && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                cancel()
              }}
              className="rounded-lg p-2 text-zinc-500 transition hover:bg-rose-500/10 hover:text-rose-400"
            >
              <Square className="w-3.5 h-3.5" />
            </button>
          )}
          <button
            onClick={(e) => e.stopPropagation()}
            className="rounded-lg p-2 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <MoreHorizontal className="w-4 h-4" />
          </button>
        </div>
      </div>

      {job.progress !== undefined && job.status === 'processing' && (
        <div className="mt-3">
          <div className="w-full rounded-full h-1 bg-white/10">
            <motion.div
              className="h-1 rounded-full bg-blue-500"
              initial={{ width: 0 }}
              animate={{ width: `${job.progress}%` }}
              transition={{ duration: 0.5 }}
            />
          </div>
        </div>
      )}
    </motion.div>
  )
}

export const JobQueue: React.FC<JobQueueProps> = ({
  maxJobs = 50,
  showFilters = true,
  showSearch = true,
  onJobClick,
  onJobComplete,
  className = '',
}) => {
  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all')
  const [typeFilter, setTypeFilter] = useState<string>('all')

  const {
    jobs,
    isLoadingJobs,
    jobsError,
    refreshJobs,
    systemHealth,
    getActiveJobs,
    getCompletedJobs,
    getFailedJobs,
  } = useJobManagement({ maxJobs })

  const filteredJobs =
    jobs?.jobs.filter((job) => {
      const matchesSearch =
        !searchQuery ||
        job.job_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.metadata?.job_type || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (job.message || '').toLowerCase().includes(searchQuery.toLowerCase())

      const matchesStatus = statusFilter === 'all' || job.status === statusFilter
      const matchesType = typeFilter === 'all' || (job.metadata?.job_type || 'latex_compilation') === typeFilter

      return matchesSearch && matchesStatus && matchesType
    }) || []

  const activeJobs = getActiveJobs()
  const completedJobs = getCompletedJobs()
  const failedJobs = getFailedJobs()

  return (
    <div className={className}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="flex items-center gap-2 text-lg font-semibold text-white">
            <Clock className="w-5 h-5 text-blue-400" />
            Job Queue
          </h2>
          <p className="text-xs text-zinc-500">
            {jobs ? `${jobs.total_count} total jobs` : 'Loading jobs\u2026'}
          </p>
        </div>

        <button
          onClick={refreshJobs}
          disabled={isLoadingJobs}
          className="rounded-lg border border-white/10 bg-white/[0.03] p-2 text-zinc-400 transition hover:bg-white/[0.06] hover:text-zinc-200 disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isLoadingJobs ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Stats */}
      {jobs && (
        <div className="grid grid-cols-4 gap-3 mb-5">
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 text-center">
            <p className="text-xl font-bold text-blue-400">{activeJobs.length}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Active</p>
          </div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 text-center">
            <p className="text-xl font-bold text-emerald-400">{completedJobs.length}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Done</p>
          </div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 text-center">
            <p className="text-xl font-bold text-rose-400">{failedJobs.length}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Failed</p>
          </div>
          <div className="rounded-lg border border-white/[0.07] bg-white/[0.02] p-3 text-center">
            <p className="text-xl font-bold text-zinc-300">{systemHealth?.active_jobs_count || 0}</p>
            <p className="text-[10px] uppercase tracking-wider text-zinc-500">Queued</p>
          </div>
        </div>
      )}

      {/* Search & Filters */}
      {(showSearch || showFilters) && (
        <div className="flex flex-col sm:flex-row gap-3 mb-4">
          {showSearch && (
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-600" />
              <input
                type="text"
                placeholder="Search jobs\u2026"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-black/40 pl-9 pr-3 py-2 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-orange-300/40"
              />
            </div>
          )}

          {showFilters && (
            <div className="flex gap-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-orange-300/40"
              >
                <option value="all">All Status</option>
                <option value="pending">Pending</option>
                <option value="processing">Processing</option>
                <option value="completed">Completed</option>
                <option value="failed">Failed</option>
                <option value="cancelled">Cancelled</option>
              </select>

              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-xs text-zinc-300 outline-none focus:border-orange-300/40"
              >
                <option value="all">All Types</option>
                <option value="latex_compilation">LaTeX Compilation</option>
                <option value="llm_optimization">LLM Optimization</option>
                <option value="combined">Optimize & Compile</option>
                <option value="ats_scoring">ATS Scoring</option>
                <option value="jd_analysis">JD Analysis</option>
              </select>
            </div>
          )}
        </div>
      )}

      {/* Error */}
      {jobsError && (
        <div className="mb-4 rounded-lg border border-rose-500/20 bg-rose-500/[0.06] p-4">
          <div className="flex items-center gap-2">
            <XCircle className="w-5 h-5 text-rose-400 shrink-0" />
            <div>
              <p className="text-sm font-medium text-rose-300">Failed to load jobs</p>
              <p className="text-xs text-rose-400/80">{jobsError}</p>
            </div>
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {isLoadingJobs && !jobs && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="animate-pulse rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-lg bg-white/5" />
                <div className="flex-1">
                  <div className="h-4 w-1/3 rounded bg-white/5 mb-2" />
                  <div className="h-3 w-1/2 rounded bg-white/5" />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Jobs list */}
      {jobs && (
        <div className="space-y-2">
          <AnimatePresence>
            {filteredJobs.length > 0 ? (
              filteredJobs.map((job) => (
                <JobItem key={job.job_id} job={job} onJobClick={onJobClick} onJobComplete={onJobComplete} />
              ))
            ) : (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="py-10 text-center"
              >
                <Clock className="w-7 h-7 mx-auto mb-2 text-zinc-700" />
                <p className="text-sm text-zinc-500">No jobs found</p>
                <p className="text-xs text-zinc-600">
                  {searchQuery || statusFilter !== 'all' || typeFilter !== 'all'
                    ? 'Try adjusting your filters'
                    : 'Submit a job to get started'}
                </p>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}

      {/* System health */}
      {systemHealth && (
        <div className="mt-5 pt-4 border-t border-white/[0.07]">
          <div className="flex items-center justify-between text-xs">
            <span className="text-zinc-500">System Status</span>
            <span
              className={`rounded-md px-2 py-0.5 text-[10px] font-bold ring-1 ${
                systemHealth.status === 'healthy'
                  ? 'text-emerald-400 bg-emerald-500/10 ring-emerald-400/20'
                  : systemHealth.status === 'degraded'
                    ? 'text-yellow-300 bg-yellow-500/10 ring-yellow-400/20'
                    : 'text-rose-400 bg-rose-500/10 ring-rose-400/20'
              }`}
            >
              {systemHealth.status}
            </span>
          </div>
          <div className="flex items-center justify-between text-[10px] text-zinc-600 mt-1">
            <span>{systemHealth.websocket_connections} WS connections</span>
            <span>{systemHealth.active_jobs_count} active</span>
          </div>
        </div>
      )}
    </div>
  )
}

export default JobQueue
