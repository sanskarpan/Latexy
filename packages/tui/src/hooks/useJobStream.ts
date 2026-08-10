import { useEffect, useRef } from 'react'
import { wsClient } from '../lib/ws-client.js'
import type { WSServerError } from '../lib/ws-client.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import { resolveAtsScore } from '../lib/event-types.js'
import type {
  AnyEvent,
  LogLineEvent,
  JobProgressEvent,
  JobCompletedEvent,
  JobFailedEvent,
  JobCancelledEvent,
} from '../lib/event-types.js'

// Server-side rejections that will never resolve on their own — mirrors headless.ts
const FATAL_WS_ERROR_CODES = new Set(['forbidden', 'invalid_request'])

/** Only the job that owns the spinner may clear it — a background job settling must not. */
function clearActiveJob(jobId: string): void {
  if ($activeJobId.get() === jobId) $activeJobId.set(null)
}

export class JobController {
  private logMsgId: string | null = null
  private toolMsgId: string | null = null
  private logLines: string[] = []
  private llmBuffer = ''
  private llmMsgId: string | null = null
  private lastFlushedLen = 0
  private flushTimer: NodeJS.Timeout | null = null
  private startedAt = Date.now()
  private seenEventIds = new Set<string>()

  constructor(private readonly jobId: string) {}

  setToolMsgId(id: string): void {
    this.toolMsgId = id
  }

  /**
   * Drop an event this controller has already applied.
   *
   * The client resumes a reconnect from its last event id now, so a full replay
   * should not happen — but a replay is silently destructive here (onLogLine and
   * onLLMToken both append), so this is a cheap second line of defence against
   * any path that still delivers an event twice.
   */
  private alreadyApplied(ev: { event_id?: string }): boolean {
    const id = ev.event_id
    if (typeof id !== 'string' || id === '') return false
    if (this.seenEventIds.has(id)) return true
    // An /optimize streams a token event per chunk, and a job that never reaches
    // a terminal state is never released — so this set would grow for the whole
    // session. Reset rather than grow without bound: the resume position is the
    // real defence, and this is only a backstop.
    if (this.seenEventIds.size > 20_000) this.seenEventIds.clear()
    this.seenEventIds.add(id)
    return false
  }

  /**
   * Write out any buffered LLM text immediately and stop the pending flush.
   *
   * The 16ms flush timer used to outlive the job: if completion arrived first,
   * llmMsgId was still null, so onComplete's `streaming: false` had nothing to
   * apply to and the timer then created the message with `streaming: true` —
   * leaving a finished answer rendering as though it were still being written,
   * forever. The timer also kept the event loop alive.
   */
  private flushLLM(): void {
    if (this.flushTimer) {
      clearTimeout(this.flushTimer)
      this.flushTimer = null
    }
    if (this.llmBuffer === '') return
    this.lastFlushedLen = this.llmBuffer.length
    if (!this.llmMsgId) {
      this.llmMsgId = addMessage({
        role: 'assistant',
        content: this.llmBuffer,
        jobId: this.jobId,
        streaming: false,
      })
    } else {
      updateMessage(this.llmMsgId, { content: this.llmBuffer, streaming: false })
    }
  }

  onLogLine(ev: LogLineEvent): void {
    if (this.alreadyApplied(ev)) return
    if (!this.logMsgId) {
      this.logMsgId = addMessage({
        role: 'log_stream',
        content: '',
        jobId: this.jobId,
        resultData: { lines: [] as string[] },
      })
    }
    this.logLines.push(ev.line)
    updateMessage(this.logMsgId, { resultData: { lines: [...this.logLines] } })
  }

  onLLMToken(token: string, ev?: { event_id?: string }): void {
    // Replayed tokens append, so a replay used to render the answer twice over.
    if (ev && this.alreadyApplied(ev)) return
    this.llmBuffer += token
    if (!this.flushTimer) {
      this.flushTimer = setTimeout(() => {
        const delta = this.llmBuffer.slice(this.lastFlushedLen)
        this.lastFlushedLen = this.llmBuffer.length
        this.flushTimer = null
        if (!this.llmMsgId) {
          this.llmMsgId = addMessage({
            role: 'assistant',
            content: delta,
            jobId: this.jobId,
            streaming: true,
          })
        } else {
          updateMessage(this.llmMsgId, { content: this.llmBuffer })
        }
      }, 16)
    }
  }

  onProgress(ev: JobProgressEvent): void {
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, { content: `${ev.stage} ${ev.percent}%` })
    }
  }

  onComplete(ev: JobCompletedEvent): void {
    if (this.alreadyApplied(ev)) return
    const durationMs = Date.now() - this.startedAt
    const atsScore = resolveAtsScore(ev)
    // Land any buffered tokens before the card settles, so the streamed answer
    // is not left half-written or stuck rendering as in-progress.
    this.flushLLM()
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'success',
        toolResult: {
          pdf_job_id: ev.pdf_job_id,
          page_count: ev.page_count,
          ats_score: atsScore,
          compiler: ev.compiler,
        },
        durationMs,
      })
    }
    clearActiveJob(this.jobId)
    // job.completed carries these at the top level — there is no `result` wrapper
    if (ev.pdf_job_id != null || ev.page_count != null) {
      addMessage({
        role: 'compile_result',
        content: '',
        jobId: this.jobId,
        resultData: {
          pages: ev.page_count ?? null,
          sizeBytes: null,
          compilationTimeMs: ev.compilation_time != null
            ? Math.round(ev.compilation_time * 1000)
            : durationMs,
          pdfUrl: ev.pdf_job_id != null ? `/download/${ev.pdf_job_id}` : null,
          atsScore,
          compiler: ev.compiler ?? null,
        },
      })
    }
  }

  onFailed(ev: JobFailedEvent): void {
    if (this.alreadyApplied(ev)) return
    const durationMs = Date.now() - this.startedAt
    // Keep whatever the model had produced, but stop it rendering as streaming.
    this.flushLLM()
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'error',
        toolResult: { error: ev.error_message, error_code: ev.error_code },
        durationMs,
      })
    }
    clearActiveJob(this.jobId)
  }

  onCancelled(ev: JobCancelledEvent): void {
    if (this.alreadyApplied(ev)) return
    this.flushLLM()
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, { toolState: 'cancelled' })
    }
    clearActiveJob(this.jobId)
  }
}

const controllers = new Map<string, JobController>()

export function createJobController(jobId: string): JobController {
  const ctrl = new JobController(jobId)
  controllers.set(jobId, ctrl)
  return ctrl
}

function failController(jobId: string, code: string, message: string): void {
  const ctrl = controllers.get(jobId)
  if (!ctrl) return
  ctrl.onFailed({
    event_id: `ws-error-${jobId}`,
    job_id: jobId,
    timestamp: Date.now(),
    sequence: -1,
    type: 'job.failed',
    error_code: code,
    error_message: message,
    retryable: false,
  })
  controllers.delete(jobId)
}

/**
 * A fatal {type:"error"} frame means the rejected subscribe will never resolve; without this
 * the TUI spins forever on a forbidden/invalid_request subscribe.
 *
 * The relay tags per-job rejections with job_id (ws_routes._send_error), so those only kill the
 * one stream — other jobs on the same socket are unaffected. Only untagged frames, which are
 * connection-wide, fail everything.
 */
export function handleFatalServerError(err: WSServerError): void {
  if (!FATAL_WS_ERROR_CODES.has(err.code)) return
  const message = `Event stream rejected by server (${err.code}): ${err.message}`

  if (err.job_id) {
    // Unknown job_id → not ours (another client's stream, or already settled); stay quiet.
    if (!controllers.has(err.job_id)) return
    addMessage({ role: 'error', content: message })
    failController(err.job_id, err.code, message)
    return
  }

  addMessage({ role: 'error', content: message })
  for (const jobId of [...controllers.keys()]) {
    failController(jobId, err.code, message)
  }
  $activeJobId.set(null)
}

export function useWSEventRouter(): void {
  const mounted = useRef(false)

  useEffect(() => {
    if (mounted.current) return
    mounted.current = true

    const releaseJob = (jobId: string) => {
      controllers.delete(jobId)
      wsClient.unsubscribe(jobId)
    }

    const handleEvent = (ev: AnyEvent) => {
      const ctrl = controllers.get(ev.job_id)
      if (!ctrl) return
      switch (ev.type) {
        case 'log.line':      ctrl.onLogLine(ev); break
        case 'llm.token':     ctrl.onLLMToken(ev.token, ev); break
        case 'job.progress':  ctrl.onProgress(ev); break
        // Release the websocket subscription alongside the controller. Without
        // this the subscription map grew for the whole session, and every
        // reconnect re-subscribed to every job ever run — replaying long-finished
        // jobs back to a client that has nothing left to do with them.
        case 'job.completed': ctrl.onComplete(ev); releaseJob(ev.job_id); break
        case 'job.failed':    ctrl.onFailed(ev); releaseJob(ev.job_id); break
        case 'job.cancelled': ctrl.onCancelled(ev); releaseJob(ev.job_id); break
      }
    }

    const handleServerError = (err: WSServerError) => { handleFatalServerError(err) }

    wsClient.on('event', handleEvent)
    wsClient.on('server_error', handleServerError)
    return () => {
      wsClient.off('event', handleEvent)
      wsClient.off('server_error', handleServerError)
    }
  }, [])
}
