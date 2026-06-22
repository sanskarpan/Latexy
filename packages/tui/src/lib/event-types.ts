export type EventType =
  | 'job.queued'
  | 'job.started'
  | 'job.progress'
  | 'job.completed'
  | 'job.failed'
  | 'job.cancelled'
  | 'job.pdf_extracted'
  | 'llm.token'
  | 'llm.complete'
  | 'log.line'
  | 'ats.deep_complete'
  | 'sys.heartbeat'
  | 'sys.error'
  | 'document.convert_complete'

export interface BaseEvent {
  event_id: string
  job_id: string
  timestamp: number
  sequence: number
  type: EventType
}

export interface JobQueuedEvent extends BaseEvent {
  type: 'job.queued'
  job_type: string
  user_id: string | null
  estimated_seconds: number
}

export interface JobStartedEvent extends BaseEvent {
  type: 'job.started'
  worker_id: string
  stage: string
}

export interface JobProgressEvent extends BaseEvent {
  type: 'job.progress'
  percent: number
  stage: string
  message: string
}

export interface JobCompletedEvent extends BaseEvent {
  type: 'job.completed'
  pdf_job_id?: string
  page_count?: number | null
  ats_score?: number | null
  compilation_time?: number | null
  optimization_time?: number | null
  compiler?: string
  is_beamer?: boolean
  // Legacy / fallback: some paths wrap fields under result
  result?: Record<string, unknown>
}

export interface JobFailedEvent extends BaseEvent {
  type: 'job.failed'
  error: string
  error_code?: string
  retryable?: boolean
}

export interface JobCancelledEvent extends BaseEvent {
  type: 'job.cancelled'
}

export interface JobPdfExtractedEvent extends BaseEvent {
  type: 'job.pdf_extracted'
  pdf_url: string
  pages: number
  size_bytes: number
}

export interface LLMTokenEvent extends BaseEvent {
  type: 'llm.token'
  token: string
}

export interface LLMCompleteEvent extends BaseEvent {
  type: 'llm.complete'
  total_tokens: number
  content: string
}

export interface LogLineEvent extends BaseEvent {
  type: 'log.line'
  line: string
  level: 'info' | 'warning' | 'error' | 'debug'
}

export interface ATSDeepCompleteEvent extends BaseEvent {
  type: 'ats.deep_complete'
  overall_score: number
  category_scores: Record<string, number>
  recommendations: string[]
  strengths: string[]
  warnings: string[]
  industry_label: string | null
}

export interface SysHeartbeatEvent extends BaseEvent {
  type: 'sys.heartbeat'
  server_time: string
}

export interface SysErrorEvent extends BaseEvent {
  type: 'sys.error'
  error: string
}

export interface DocumentConvertCompleteEvent extends BaseEvent {
  type: 'document.convert_complete'
  latex_content: string
  detected_format: string
}

export type AnyEvent =
  | JobQueuedEvent
  | JobStartedEvent
  | JobProgressEvent
  | JobCompletedEvent
  | JobFailedEvent
  | JobCancelledEvent
  | JobPdfExtractedEvent
  | LLMTokenEvent
  | LLMCompleteEvent
  | LogLineEvent
  | ATSDeepCompleteEvent
  | SysHeartbeatEvent
  | SysErrorEvent
  | DocumentConvertCompleteEvent
