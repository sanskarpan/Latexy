import { useEffect, useRef } from 'react'
import { wsClient } from '../lib/ws-client.js'
import { addMessage, updateMessage, $activeJobId } from '../stores/messages.js'
import type {
  AnyEvent,
  LogLineEvent,
  JobProgressEvent,
  JobCompletedEvent,
  JobFailedEvent,
  JobCancelledEvent,
} from '../lib/event-types.js'

export class JobController {
  private logMsgId: string | null = null
  private toolMsgId: string | null = null
  private logLines: string[] = []
  private llmBuffer = ''
  private llmMsgId: string | null = null
  private lastFlushedLen = 0
  private flushTimer: NodeJS.Timeout | null = null
  private startedAt = Date.now()

  constructor(private readonly jobId: string) {}

  setToolMsgId(id: string): void {
    this.toolMsgId = id
  }

  onLogLine(ev: LogLineEvent): void {
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

  onLLMToken(token: string): void {
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
    const durationMs = Date.now() - this.startedAt
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'success',
        toolResult: ev.result,
        durationMs,
      })
    }
    if (this.llmMsgId) {
      updateMessage(this.llmMsgId, { streaming: false })
    }
    $activeJobId.set(null)
    const result = ev.result as Record<string, unknown>
    if (result['pdf_url'] != null || result['pages'] != null) {
      addMessage({
        role: 'compile_result',
        content: '',
        jobId: this.jobId,
        resultData: {
          pages: result['pages'],
          sizeBytes: result['size_bytes'],
          compilationTimeMs: durationMs,
          pdfUrl: result['pdf_url'],
          atsScore: result['ats_score'],
        },
      })
    }
  }

  onFailed(ev: JobFailedEvent): void {
    const durationMs = Date.now() - this.startedAt
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, {
        toolState: 'error',
        toolResult: { error: ev.error },
        durationMs,
      })
    }
    $activeJobId.set(null)
  }

  onCancelled(_ev: JobCancelledEvent): void {
    if (this.toolMsgId) {
      updateMessage(this.toolMsgId, { toolState: 'cancelled' })
    }
    $activeJobId.set(null)
  }
}

const controllers = new Map<string, JobController>()

export function createJobController(jobId: string): JobController {
  const ctrl = new JobController(jobId)
  controllers.set(jobId, ctrl)
  return ctrl
}

export function useWSEventRouter(): void {
  const mounted = useRef(false)

  useEffect(() => {
    if (mounted.current) return
    mounted.current = true

    const handleEvent = (ev: AnyEvent) => {
      const ctrl = controllers.get(ev.job_id)
      if (!ctrl) return
      switch (ev.type) {
        case 'log.line':      ctrl.onLogLine(ev); break
        case 'llm.token':     ctrl.onLLMToken(ev.token); break
        case 'job.progress':  ctrl.onProgress(ev); break
        case 'job.completed': ctrl.onComplete(ev); controllers.delete(ev.job_id); break
        case 'job.failed':    ctrl.onFailed(ev); controllers.delete(ev.job_id); break
        case 'job.cancelled': ctrl.onCancelled(ev); controllers.delete(ev.job_id); break
      }
    }

    wsClient.on('event', handleEvent)
    return () => { wsClient.off('event', handleEvent) }
  }, [])
}
