'use client'

import React from 'react'
import { motion } from 'framer-motion'
import { 
  Clock, 
  CheckCircle, 
  XCircle, 
  AlertCircle, 
  Loader2, 
  Play,
  Pause,
  Square,
  RefreshCw
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useJobStatus } from '@/hooks/useJobStatus'

interface JobStatusTrackerProps {
  jobId: string | null
  title?: string
  showActions?: boolean
  showProgress?: boolean
  showMetadata?: boolean
  onComplete?: (result: any) => void
  onError?: (error: string) => void
  className?: string
}

const statusConfig = {
  pending: {
    icon: Clock,
    color: 'text-yellow-600',
    bgColor: 'bg-yellow-100',
    borderColor: 'border-yellow-200',
    label: 'Pending',
    description: 'Job is queued and waiting to be processed',
  },
  processing: {
    icon: Loader2,
    color: 'text-blue-600',
    bgColor: 'bg-blue-100',
    borderColor: 'border-blue-200',
    label: 'Processing',
    description: 'Job is currently being processed',
  },
  completed: {
    icon: CheckCircle,
    color: 'text-green-600',
    bgColor: 'bg-green-100',
    borderColor: 'border-green-200',
    label: 'Completed',
    description: 'Job completed successfully',
  },
  failed: {
    icon: XCircle,
    color: 'text-red-600',
    bgColor: 'bg-red-100',
    borderColor: 'border-red-200',
    label: 'Failed',
    description: 'Job failed to complete',
  },
  cancelled: {
    icon: Square,
    color: 'text-gray-600',
    bgColor: 'bg-gray-100',
    borderColor: 'border-gray-200',
    label: 'Cancelled',
    description: 'Job was cancelled',
  },
}

export const JobStatusTracker: React.FC<JobStatusTrackerProps> = ({
  jobId,
  title = 'Job Status',
  showActions = true,
  showProgress = true,
  showMetadata = false,
  onComplete,
  onError,
  className = '',
}) => {
  const {
    status,
    result,
    isLoading,
    error,
    progress,
    isComplete,
    isFailed,
    refresh,
    cancel,
    clearError,
  } = useJobStatus(jobId, {
    onComplete,
    onError,
  })

  if (!jobId) {
    return (
      <Card className={`${className}`}>
        <CardContent className="flex items-center justify-center py-8">
          <div className="text-center text-gray-500">
            <AlertCircle className="w-8 h-8 mx-auto mb-2" />
            <p>No job selected</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const currentStatus = status?.status || 'pending'
  const config = statusConfig[currentStatus as keyof typeof statusConfig] || statusConfig.pending
  const StatusIcon = config.icon

  const formatTime = (timestamp?: number) => {
    if (!timestamp) return 'Unknown'
    return new Date(timestamp * 1000).toLocaleString()
  }

  const formatDuration = (start?: number, end?: number) => {
    if (!start) return 'Unknown'
    const endTime = end || Date.now() / 1000
    const duration = endTime - start
    
    if (duration < 60) {
      return `${Math.round(duration)}s`
    } else if (duration < 3600) {
      return `${Math.round(duration / 60)}m ${Math.round(duration % 60)}s`
    } else {
      return `${Math.round(duration / 3600)}h ${Math.round((duration % 3600) / 60)}m`
    }
  }

  return (
    <Card className={`${className} ${config.borderColor} border-2`}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-10 h-10 rounded-full ${config.bgColor} flex items-center justify-center`}>
              <StatusIcon 
                className={`w-5 h-5 ${config.color} ${currentStatus === 'processing' ? 'animate-spin' : ''}`} 
              />
            </div>
            <div>
              <CardTitle className="text-lg">{title}</CardTitle>
              <CardDescription>
                Job ID: {jobId.substring(0, 8)}...
              </CardDescription>
            </div>
          </div>
          
          <Badge 
            variant="outline" 
            className={`${config.color} ${config.bgColor} ${config.borderColor}`}
          >
            {config.label}
          </Badge>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Status Description */}
        <p className="text-sm text-gray-600">
          {status?.message || config.description}
        </p>

        {/* Progress Bar */}
        {showProgress && (
          <div className="space-y-2">
            <div className="flex justify-between text-sm">
              <span>Progress</span>
              <span>{progress}%</span>
            </div>
            <div className="w-full bg-gray-200 rounded-full h-2">
              <motion.div
                className={`h-2 rounded-full ${
                  isFailed ? 'bg-red-500' : 
                  isComplete ? 'bg-green-500' : 
                  'bg-blue-500'
                }`}
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </div>
        )}

        {/* Error Display */}
        {error && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-3 bg-red-50 border border-red-200 rounded-lg"
          >
            <div className="flex items-start gap-2">
              <XCircle className="w-4 h-4 text-red-600 mt-0.5 flex-shrink-0" />
              <div className="flex-1">
                <p className="text-sm font-medium text-red-800">Error</p>
                <p className="text-sm text-red-700">{error}</p>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearError}
                className="text-red-600 hover:text-red-800"
              >
                ×
              </Button>
            </div>
          </motion.div>
        )}

        {/* Metadata */}
        {showMetadata && status && (
          <div className="space-y-2 text-sm text-gray-600">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <span className="font-medium">Created:</span>
                <br />
                {formatTime(status.created_at)}
              </div>
              <div>
                <span className="font-medium">Updated:</span>
                <br />
                {formatTime(status.updated_at)}
              </div>
            </div>
            
            {status.created_at && (
              <div>
                <span className="font-medium">Duration:</span> {formatDuration(status.created_at, status.updated_at)}
              </div>
            )}

            {status.estimated_completion && (
              <div>
                <span className="font-medium">Estimated completion:</span>
                <br />
                {formatTime(status.estimated_completion)}
              </div>
            )}
          </div>
        )}

        {/* Actions */}
        {showActions && (
          <div className="flex gap-2 pt-2">
            <Button
              variant="outline"
              size="sm"
              onClick={refresh}
              disabled={isLoading}
              className="flex items-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>

            {!isComplete && !isFailed && currentStatus !== 'cancelled' && (
              <Button
                variant="outline"
                size="sm"
                onClick={cancel}
                className="flex items-center gap-2 text-red-600 hover:text-red-700"
              >
                <Square className="w-4 h-4" />
                Cancel
              </Button>
            )}

            {isComplete && result && (
              <Button
                variant="default"
                size="sm"
                onClick={() => onComplete?.(result)}
                className="flex items-center gap-2"
              >
                <CheckCircle className="w-4 h-4" />
                View Result
              </Button>
            )}
          </div>
        )}

        {/* Loading Overlay */}
        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="absolute inset-0 bg-white/50 flex items-center justify-center rounded-lg"
          >
            <Loader2 className="w-6 h-6 animate-spin text-blue-600" />
          </motion.div>
        )}
      </CardContent>
    </Card>
  )
}

export default JobStatusTracker
