/**
 * Pure reducer for useJobStream — no browser dependencies.
 * Extracted so it can be unit-tested in a node environment.
 */

import type { AnyEvent, ATSDeepAnalysis, ATSDetails, ArtifactReadyEvent } from '@/lib/event-types'

// ------------------------------------------------------------------ //
//  State shape                                                        //
// ------------------------------------------------------------------ //

export interface LogLine {
  source: string
  line: string
  is_error: boolean
}

export interface TimeoutError {
  plan: string
  upgradeMessage: string
  seconds: number
}

export interface JobStreamState {
  status: 'idle' | 'queued' | 'processing' | 'completed' | 'failed' | 'cancelled'
  stage: string
  percent: number
  message: string
  /** Accumulated LLM token stream - update Monaco model directly */
  streamingLatex: string
  logLines: LogLine[]
  atsScore: number | null
  atsDetails: ATSDetails | null
  industryLabel: string | null
  deepAnalysis: ATSDeepAnalysis | null
  changesMade: Array<{ section: string; change_type: string; reason: string }>
  pdfJobId: string | null
  artifact: ArtifactReadyEvent | null
  semanticPatches: import('@/lib/resume-engine-types').SemanticPatch[]
  semanticReviewFinal: boolean
  semanticSourceHash: string | null
  semanticRevision: number | null
  compilationTime: number | null
  optimizationTime: number | null
  tokensUsed: number | null
  /** Page count from last successful pdflatex compile */
  pageCount: number | null
  /** Plain text extracted from the compiled PDF via pdftotext (ATS pre-flight) */
  extractedPdfText: string | null
  error: string | null
  errorCode: string | null
  retryable: boolean
  /** Set when error_code === 'compile_timeout' — used to show upgrade CTA */
  timeoutError: TimeoutError | null
}

export const initialState: JobStreamState = {
  status: 'idle',
  stage: '',
  percent: 0,
  message: '',
  streamingLatex: '',
  logLines: [],
  atsScore: null,
  atsDetails: null,
  industryLabel: null,
  deepAnalysis: null,
  changesMade: [],
  pdfJobId: null,
  artifact: null,
  semanticPatches: [],
  semanticReviewFinal: false,
  semanticSourceHash: null,
  semanticRevision: null,
  compilationTime: null,
  optimizationTime: null,
  tokensUsed: null,
  pageCount: null,
  extractedPdfText: null,
  error: null,
  errorCode: null,
  retryable: false,
  timeoutError: null,
}

// ------------------------------------------------------------------ //
//  Reducer                                                            //
// ------------------------------------------------------------------ //

export type ReducerAction =
  | AnyEvent
  | { type: '__reset__' }
  | {
      type: '__snapshot__'
      status: 'queued' | 'processing'
      stage: string
      percent: number
      message?: string
    }

const TERMINAL_STATES = new Set<JobStreamState['status']>(['completed', 'failed', 'cancelled'])
const TERMINAL_EVENT_TYPES = new Set<AnyEvent['type']>(['job.completed', 'job.failed', 'job.cancelled'])

export function jobStreamReducer(state: JobStreamState, action: ReducerAction): JobStreamState {
  if (action.type === '__reset__') return { ...initialState }
  if (action.type === '__snapshot__') {
    if (TERMINAL_STATES.has(state.status)) return state
    return {
      ...state,
      status: action.status,
      stage: action.stage,
      percent: action.percent,
      message: action.message ?? state.message,
    }
  }
  const event = action as AnyEvent

  // REST fallback can deliver the authoritative completion payload after a
  // live WebSocket terminal event. Keep completion idempotent, but allow that
  // same-job event to fill fields the first event did not carry (most notably
  // pdf_job_id). Cancellation and other terminal transitions remain blocked
  // below so a late disconnect cannot undo a completed job.
  if (state.status === 'completed' && event.type === 'job.completed') {
    return {
      ...state,
      pdfJobId: event.pdf_job_id ?? state.pdfJobId,
      atsScore: event.ats_score ?? state.atsScore,
      atsDetails: event.ats_details ?? state.atsDetails,
      industryLabel: (event.ats_details as ATSDetails | null)?.industry_label ?? state.industryLabel,
      changesMade: event.changes_made?.length ? event.changes_made : state.changesMade,
      compilationTime: event.compilation_time ?? state.compilationTime,
      optimizationTime: event.optimization_time ?? state.optimizationTime,
      tokensUsed: event.tokens_used ?? state.tokensUsed,
      pageCount: event.page_count ?? state.pageCount,
    }
  }

  // CANCEL-02: once a terminal state is reached, ignore any subsequent
  // terminal-state transitions (e.g. a late job.cancelled after job.completed).
  if (TERMINAL_STATES.has(state.status) && TERMINAL_EVENT_TYPES.has(event.type)) {
    return state
  }

  switch (event.type) {
    case 'context.ready':
    case 'section.ready':
    case 'patch.ready':
    case 'review.ready': {
      if (state.status === 'cancelled' || state.status === 'failed' || event.branch !== 'candidate'
          || (state.semanticSourceHash && (state.semanticSourceHash !== event.source_sha256 || state.semanticRevision !== event.content_revision))) return state
      if (state.semanticReviewFinal && event.provisional) return state
      let patches = state.semanticPatches
      if (event.patch && !patches.some((patch) => patch.patch_id === event.patch?.patch_id) && patches.length < 100) patches = [...patches, event.patch]
      if (event.type === 'review.ready' && event.final_patch_ids) patches = patches.filter((patch) => event.final_patch_ids!.includes(patch.patch_id))
      return { ...state, semanticPatches: patches, semanticReviewFinal: state.semanticReviewFinal || event.type === 'review.ready',
        semanticSourceHash: event.source_sha256, semanticRevision: event.content_revision }
    }
    case 'artifact.ready':
      // Cancellation/failure and older attempt replay cannot resurrect a
      // preview. Accepted/candidate identity remains separate from completion.
      if (state.status === 'cancelled' || state.status === 'failed'
          || (state.artifact && event.owner_epoch < state.artifact.owner_epoch)) return state
      if (state.artifact?.artifact_id === event.artifact_id) return state
      return { ...state, artifact: event, pageCount: event.page_count }
    case 'job.queued':
      return { ...state, status: 'queued', stage: '', percent: 0, extractedPdfText: null, pageCount: null }

    case 'job.started':
      return {
        ...state,
        status: 'processing',
        stage: event.stage,
        message: `Starting ${event.stage}`,
      }

    case 'job.progress':
      return {
        ...state,
        status: 'processing',
        stage: event.stage,
        percent: event.percent,
        message: event.message,
      }

    case 'llm.token':
      return { ...state, streamingLatex: state.streamingLatex + event.token }

    case 'llm.complete':
      return {
        ...state,
        streamingLatex: event.full_content,
        tokensUsed: event.tokens_total,
      }

    case 'log.line': {
      const pageCountMatch = event.line?.match(/Output written on .+?\((\d+) page/)
      const newLine: LogLine = { source: event.source, line: event.line, is_error: event.is_error }
      return {
        ...state,
        // PERF-009: cap accumulated log lines to prevent unbounded memory growth
        logLines: [...state.logLines, newLine].slice(-2000),
        ...(pageCountMatch ? { pageCount: parseInt(pageCountMatch[1], 10) } : {}),
      }
    }

    case 'job.completed':
      return {
        ...state,
        status: 'completed',
        percent: 100,
        stage: '',
        message: 'Completed',
        pdfJobId: event.pdf_job_id,
        atsScore: event.ats_score,
        atsDetails: event.ats_details as ATSDetails | null,
        industryLabel: (event.ats_details as ATSDetails | null)?.industry_label ?? null,
        changesMade: event.changes_made,
        compilationTime: event.compilation_time,
        optimizationTime: event.optimization_time,
        tokensUsed: event.tokens_used,
        pageCount: event.page_count ?? state.pageCount,
        error: null,
        errorCode: null,
        timeoutError: null,
      }

    case 'job.pdf_extracted':
      return {
        ...state,
        extractedPdfText: event.text,
        pageCount: event.page_count ?? state.pageCount,
      }

    case 'ats.deep_complete':
      return {
        ...state,
        deepAnalysis: {
          overall_score: event.overall_score,
          overall_feedback: event.overall_feedback,
          sections: event.sections,
          ats_compatibility: event.ats_compatibility,
          job_match: event.job_match,
          tokens_used: event.tokens_used,
          analysis_time: event.analysis_time,
          multi_dim_scores: event.multi_dim_scores,
          industry_key: event.industry_key,
          industry_label: event.industry_label,
        },
      }

    case 'job.failed':
      return {
        ...state,
        status: 'failed',
        stage: event.stage,
        error: event.error_message,
        errorCode: event.error_code,
        retryable: event.retryable,
        streamingLatex: event.optimized_latex ?? state.streamingLatex,
        changesMade: event.changes_made ?? state.changesMade,
        timeoutError: event.error_code === 'compile_timeout'
          ? {
              plan: event.user_plan ?? 'free',
              upgradeMessage: event.upgrade_message ?? 'Upgrade to Pro for a 4-minute compile timeout',
              seconds: event.timeout_seconds ?? (
                event.user_plan === 'basic' ? 120 : event.user_plan === 'free' || !event.user_plan ? 30 : 240
              ),
            }
          : null,
      }

    case 'job.cancelled':
      return { ...state, status: 'cancelled', percent: 0, message: 'Cancelled' }

    default:
      return state
  }
}
