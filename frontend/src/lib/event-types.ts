/**
 * Typed event definitions for the Latexy event-driven architecture.
 * Shared between WebSocket messages and the useJobStream hook.
 */

export type EventType =
  | 'job.queued'
  | 'job.started'
  | 'job.progress'
  | 'job.completed'
  | 'job.failed'
  | 'job.cancelled'
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

// ------------------------------------------------------------------ //
//  Job Lifecycle Events                                               //
// ------------------------------------------------------------------ //

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

export interface ATSDetails {
  category_scores: Record<string, number>
  recommendations: string[]
  strengths: string[]
  warnings: string[]
}

export interface ChangeEntry {
  section: string
  change_type: 'added' | 'modified' | 'removed'
  reason: string
}

export interface JobCompletedEvent extends BaseEvent {
  type: 'job.completed'
  pdf_job_id: string
  ats_score: number
  ats_details: ATSDetails
  changes_made: ChangeEntry[]
  compilation_time: number
  optimization_time: number
  tokens_used: number
}

export interface JobFailedEvent extends BaseEvent {
  type: 'job.failed'
  stage: string
  error_code: string
  error_message: string
  retryable: boolean
  /** Present when compilation failed after LLM succeeded — allows "apply anyway" UX */
  optimized_latex?: string
  changes_made?: Array<{ section: string; change_type: string; reason: string }>
}

export interface JobCancelledEvent extends BaseEvent {
  type: 'job.cancelled'
}

// ------------------------------------------------------------------ //
//  Streaming Events                                                   //
// ------------------------------------------------------------------ //

export interface LLMTokenEvent extends BaseEvent {
  type: 'llm.token'
  token: string
}

export interface LLMStreamCompleteEvent extends BaseEvent {
  type: 'llm.complete'
  full_content: string
  tokens_total: number
}

export interface LogLineEvent extends BaseEvent {
  type: 'log.line'
  source: string
  line: string
  is_error: boolean
}

// ------------------------------------------------------------------ //
//  ATS Deep Analysis Events (Layer 2)                                //
// ------------------------------------------------------------------ //

export interface ATSDeepSection {
  name: string
  score: number
  strengths: string[]
  improvements: string[]
  rewrite_suggestion?: string
}

export interface ATSDeepCompatibility {
  score: number
  issues: string[]
  keyword_gaps: string[]
}

export interface ATSJobMatch {
  score: number
  matched_requirements: string[]
  missing_requirements: string[]
  recommendation: string
}

export interface ATSDeepAnalysis {
  overall_score: number
  overall_feedback: string
  sections: ATSDeepSection[]
  ats_compatibility: ATSDeepCompatibility
  job_match: ATSJobMatch | null
  tokens_used: number
  analysis_time: number
}

export interface ATSDeepCompleteEvent extends BaseEvent {
  type: 'ats.deep_complete'
  overall_score: number
  overall_feedback: string
  sections: ATSDeepSection[]
  ats_compatibility: ATSDeepCompatibility
  job_match: ATSJobMatch | null
  tokens_used: number
  analysis_time: number
}

// ------------------------------------------------------------------ //
//  System Events                                                      //
// ------------------------------------------------------------------ //

export interface HeartbeatEvent extends BaseEvent {
  type: 'sys.heartbeat'
  server_time: number
}

export interface SystemErrorEvent extends BaseEvent {
  type: 'sys.error'
  message: string
}

export interface DocumentConvertCompleteEvent extends BaseEvent {
  type: 'document.convert_complete'
  source_format: string
  latex_content: string
  tokens_used: number
  conversion_time: number
}

// ------------------------------------------------------------------ //
//  Union type                                                         //
// ------------------------------------------------------------------ //

export type AnyEvent =
  | JobQueuedEvent
  | JobStartedEvent
  | JobProgressEvent
  | JobCompletedEvent
  | JobFailedEvent
  | JobCancelledEvent
  | LLMTokenEvent
  | LLMStreamCompleteEvent
  | LogLineEvent
  | ATSDeepCompleteEvent
  | HeartbeatEvent
  | SystemErrorEvent
  | DocumentConvertCompleteEvent

// ------------------------------------------------------------------ //
//  WebSocket protocol messages                                        //
// ------------------------------------------------------------------ //

export type WSClientMessage =
  | { type: 'subscribe'; job_id: string; last_event_id?: string }
  | { type: 'unsubscribe'; job_id: string }
  | { type: 'cancel'; job_id: string }
  | { type: 'ping' }

export type WSServerMessage =
  | { type: 'subscribed'; job_id: string; replayed_count: number }
  | { type: 'unsubscribed'; job_id: string }
  | { type: 'cancelled'; job_id: string }
  | { type: 'pong'; server_time: number }
  | { type: 'event'; event: AnyEvent }
  | { type: 'error'; code: string; message: string }
