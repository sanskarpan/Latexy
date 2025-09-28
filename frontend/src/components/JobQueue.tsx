'use client'

import React, { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Clock, 
  CheckCircle, 
  XCircle, 
  AlertCircle, 
  Loader2, 
  Play,
  Square,
  RefreshCw,
  Filter,
  Search,
  MoreHorizontal,
  FileText,
  Zap,
  Target,
  Eye,
  Download,
  Trash2
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
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
    color: 'text-blue-600',
    bgColor: 'bg-blue-100',
  },
  llm_optimization: {
    icon: Zap,
    label: 'LLM Optimization',
    color: 'text-orange-600',
    bgColor: 'bg-orange-100',
  },
  combined: {
    icon: Play,
    label: 'Optimize & Compile',
    color: 'text-purple-600',
    bgColor: 'bg-purple-100',
  },
  ats_scoring: {
    icon: Target,
    label: 'ATS Scoring',
    color: 'text-green-600',
    bgColor: 'bg-green-100',
  },
  jd_analysis: {
    icon: Search,
    label: 'Job Description Analysis',
    color: 'text-indigo-600',
    bgColor: 'bg-indigo-100',
  },
}

const statusConfig = {
  pending: {
    icon: Clock,
    color: 'text-yellow-600',
    bgColor: 'bg-yellow-100',
    label: 'Pending',
  },
  processing: {
    icon: Loader2,
    color: 'text-blue-600',
    bgColor: 'bg-blue-100',
    label: 'Processing',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-600',
    bgColor: 'bg-green-100',
    label: 'Completed',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-600',
    bgColor: 'bg-red-100',
    label: 'Failed',
  },
  cancelled: {
    icon: Square,
    color: 'text-gray-600',
    bgColor: 'bg-gray-100',
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
    }
  })

  const jobType = job.metadata?.job_type || 'latex_compilation'
  const typeConfig = jobTypeConfig[jobType as keyof typeof jobTypeConfig] || jobTypeConfig.latex_compilation
  const statusConfig_ = statusConfig[job.status as keyof typeof statusConfig] || statusConfig.pending
  
  const TypeIcon = typeConfig.icon
  const StatusIcon = statusConfig_.icon

  const formatTime = (timestamp?: number) => {
    if (!timestamp) return 'Unknown'
    const date = new Date(timestamp * 1000)
    const now = new Date()
    const diff = now.getTime() - date.getTime()
    
    if (diff < 60000) return 'Just now'
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`
    return date.toLocaleDateString()
  }

  const canCancel = !['completed', 'failed', 'cancelled'].includes(job.status)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow cursor-pointer"
      onClick={() => onJobClick?.(job.job_id)}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 flex-1">
          <div className={`w-10 h-10 ${typeConfig.bgColor} rounded-lg flex items-center justify-center`}>
            <TypeIcon className={`w-5 h-5 ${typeConfig.color}`} />
          </div>
          
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h3 className="font-medium text-gray-900 truncate">
                {typeConfig.label}
              </h3>
              <Badge variant="outline" className={`${statusConfig_.color} ${statusConfig_.bgColor}`}>
                <StatusIcon className={`w-3 h-3 mr-1 ${job.status === 'processing' ? 'animate-spin' : ''}`} />
                {statusConfig_.label}
              </Badge>
            </div>
            
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>ID: {job.job_id.substring(0, 8)}...</span>
              <span>{formatTime(job.created_at)}</span>
              {job.progress !== undefined && (
                <span>{job.progress}% complete</span>
              )}
            </div>
            
            {job.message && (
              <p className="text-sm text-gray-600 mt-1 truncate">
                {job.message}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 ml-4">
          {job.status === 'completed' && (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                // Handle view result
              }}
            >
              <Eye className="w-4 h-4" />
            </Button>
          )}
          
          {canCancel && (
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation()
                cancel()
              }}
              className="text-red-600 hover:text-red-700"
            >
              <Square className="w-4 h-4" />
            </Button>
          )}
          
          <Button
            variant="ghost"
            size="sm"
            onClick={(e) => {
              e.stopPropagation()
              // Handle more actions
            }}
          >
            <MoreHorizontal className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Progress Bar */}
      {job.progress !== undefined && job.status === 'processing' && (
        <div className="mt-3">
          <div className="w-full bg-gray-200 rounded-full h-1.5">
            <motion.div
              className="bg-blue-500 h-1.5 rounded-full"
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

  const filteredJobs = jobs?.jobs.filter(job => {
    const matchesSearch = !searchQuery || 
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
    <Card className={className}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-blue-600" />
              Job Queue
            </CardTitle>
            <CardDescription>
              {jobs ? `${jobs.total_count} total jobs` : 'Loading jobs...'}
            </CardDescription>
          </div>
          
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={refreshJobs}
              disabled={isLoadingJobs}
            >
              <RefreshCw className={`w-4 h-4 ${isLoadingJobs ? 'animate-spin' : ''}`} />
            </Button>
          </div>
        </div>

        {/* Stats */}
        {jobs && (
          <div className="grid grid-cols-4 gap-4 mt-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">{activeJobs.length}</div>
              <div className="text-sm text-gray-600">Active</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">{completedJobs.length}</div>
              <div className="text-sm text-gray-600">Completed</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">{failedJobs.length}</div>
              <div className="text-sm text-gray-600">Failed</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-600">{systemHealth?.active_jobs_count || 0}</div>
              <div className="text-sm text-gray-600">System Queue</div>
            </div>
          </div>
        )}
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Filters and Search */}
        {(showSearch || showFilters) && (
          <div className="flex flex-col sm:flex-row gap-4">
            {showSearch && (
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                <Input
                  placeholder="Search jobs..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10"
                />
              </div>
            )}
            
            {showFilters && (
              <div className="flex gap-2">
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="px-3 py-2 border border-gray-300 rounded-md text-sm"
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
                  className="px-3 py-2 border border-gray-300 rounded-md text-sm"
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

        {/* Error State */}
        {jobsError && (
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-center gap-2">
              <XCircle className="w-5 h-5 text-red-600" />
              <div>
                <p className="font-medium text-red-800">Failed to load jobs</p>
                <p className="text-sm text-red-700">{jobsError}</p>
              </div>
            </div>
          </div>
        )}

        {/* Loading State */}
        {isLoadingJobs && !jobs && (
          <div className="space-y-4">
            {[...Array(3)].map((_, i) => (
              <div key={i} className="animate-pulse border border-gray-200 rounded-lg p-4">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-gray-200 rounded-lg"></div>
                  <div className="flex-1">
                    <div className="h-4 bg-gray-200 rounded w-1/3 mb-2"></div>
                    <div className="h-3 bg-gray-200 rounded w-1/2"></div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Jobs List */}
        {jobs && (
          <div className="space-y-3">
            <AnimatePresence>
              {filteredJobs.length > 0 ? (
                filteredJobs.map((job) => (
                  <JobItem
                    key={job.job_id}
                    job={job}
                    onJobClick={onJobClick}
                    onJobComplete={onJobComplete}
                  />
                ))
              ) : (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="text-center py-8 text-gray-500"
                >
                  <Clock className="w-8 h-8 mx-auto mb-2" />
                  <p>No jobs found</p>
                  {searchQuery || statusFilter !== 'all' || typeFilter !== 'all' ? (
                    <p className="text-sm">Try adjusting your filters</p>
                  ) : (
                    <p className="text-sm">Submit a job to get started</p>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* System Health Indicator */}
        {systemHealth && (
          <div className="mt-6 pt-4 border-t border-gray-200">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600">System Status:</span>
              <Badge 
                variant="outline" 
                className={
                  systemHealth.status === 'healthy' ? 'text-green-600 bg-green-50 border-green-200' :
                  systemHealth.status === 'degraded' ? 'text-yellow-600 bg-yellow-50 border-yellow-200' :
                  'text-red-600 bg-red-50 border-red-200'
                }
              >
                {systemHealth.status}
              </Badge>
            </div>
            <div className="flex items-center justify-between text-xs text-gray-500 mt-1">
              <span>{systemHealth.websocket_connections} WebSocket connections</span>
              <span>{systemHealth.active_jobs_count} active jobs</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default JobQueue
