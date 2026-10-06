'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'
import { PreviewScheduler } from '@/lib/preview-scheduler'
import { trackWebVital } from '@/lib/telemetry'

const actionStarts = new Map<string, number>()
export function recordPreviewAction(jobId: string, startedAt: number) {
  actionStarts.set(jobId, startedAt)
  if (actionStarts.size > 50) actionStarts.delete(actionStarts.keys().next().value!)
}
export function recordPreviewFirstPaint(jobId: string) {
  const start = actionStarts.get(jobId)
  if (start == null) return
  actionStarts.delete(jobId)
  trackWebVital({ id: 'preview-action', name: 'PDF_USER_ACTION_PAINT', value: performance.now() - start },
    window.location.pathname === '/try' ? '/try' : '/workspace')
}

export function usePreviewScheduler(options: {
  identity: string; enabled: boolean; blocked: boolean; jobId: string | null; status: string
  submit: (source: string) => Promise<string | null>
}) {
  const submitRef = useRef(options.submit)
  submitRef.current = options.submit
  const identityRef = useRef(options.identity)
  identityRef.current = options.identity
  const scheduler = useMemo(() => {
    const identity = options.identity
    return new PreviewScheduler(async (source, editedAt) => {
    if (identityRef.current !== identity) return null
    const jobId = await submitRef.current(source)
    if (jobId) {
      recordPreviewAction(jobId, editedAt)
    }
    return jobId
    })
  }, [options.identity])
  useEffect(() => { scheduler.activate(); return () => scheduler.dispose() }, [scheduler])
  useEffect(() => { scheduler.update(options.enabled, options.blocked) }, [scheduler, options.enabled, options.blocked])
  useEffect(() => {
    if (options.jobId && ['completed', 'failed', 'cancelled'].includes(options.status)) scheduler.complete(options.jobId)
  }, [scheduler, options.jobId, options.status])
  return useCallback((source: string, editedAt?: number, force = false) => scheduler.request(source, editedAt, force), [scheduler])
}
