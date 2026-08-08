'use client'

import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ArrowRight, CheckCircle, Loader2, X, Zap } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useJobStream } from '@/hooks/useJobStream'
import { apiClient, type QuickTailorRequest } from '@/lib/api-client'

type Step = 'form' | 'progress' | 'done' | 'error'

interface Props {
  resumeId: string
  resumeTitle: string
  onClose: () => void
  onDone?: (forkId: string) => void
}

export default function QuickTailorModal({ resumeId, resumeTitle, onClose, onDone }: Props) {
  const router = useRouter()
  const [step, setStep] = useState<Step>('form')
  const [jobDescription, setJobDescription] = useState('')
  const [companyName, setCompanyName] = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [forkId, setForkId] = useState<string | null>(null)
  const [jobId, setJobId] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const { state, cancel, reset } = useJobStream(jobId)

  // Watch job completion / failure
  useEffect(() => {
    if (!jobId || step !== 'progress') return
    if (state.status === 'completed') {
      const saveAndFinish = async () => {
        if (forkId && state.streamingLatex) {
          try {
            await apiClient.updateResume(forkId, { latex_content: state.streamingLatex })
          } catch {
            setStep('error')
            setErrorMessage('Tailoring finished but saving the result failed. Please try again.')
            return
          }
        }
        setStep('done')
        onDone?.(forkId!)
      }
      void saveAndFinish()
    } else if (state.status === 'failed' || state.status === 'cancelled') {
      setStep('error')
      setErrorMessage(state.error ?? 'Optimization failed. Please try again.')
    }
  }, [state.status, state.error, state.streamingLatex, jobId, step, forkId, onDone])

  const handleSubmit = useCallback(async () => {
    if (jobDescription.trim().length < 10) return
    setIsSubmitting(true)
    setErrorMessage(null)
    try {
      const req: QuickTailorRequest = {
        job_description: jobDescription.trim(),
        company_name: companyName.trim() || undefined,
        role_title: roleTitle.trim() || undefined,
      }
      const res = await apiClient.quickTailorResume(resumeId, req)
      setForkId(res.fork_id)
      setJobId(res.job_id)
      setStep('progress')
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Failed to start tailoring')
      setStep('error')
    } finally {
      setIsSubmitting(false)
    }
  }, [resumeId, jobDescription, companyName, roleTitle])

  const handleCancel = useCallback(() => {
    cancel()
    onClose()
  }, [cancel, onClose])

  const handleTryAgain = useCallback(() => {
    reset()
    setStep('form')
    setJobId(null)
    setForkId(null)
    setErrorMessage(null)
  }, [reset])

  const handleDismiss = useCallback(() => {
    if (step === 'progress') {
      handleCancel()
    } else {
      onClose()
    }
  }, [step, handleCancel, onClose])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleDismiss()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [handleDismiss])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] backdrop-blur-sm"
      onClick={handleDismiss}
    >
      <div
        className="w-full max-w-lg rounded-[var(--radius-lg)] border border-line bg-bg p-6 shadow-[var(--shadow-2)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap size={16} className="text-accent-strong" />
            <h3 className="text-base font-semibold text-fg">Quick Tailor</h3>
          </div>
          <button
            onClick={handleDismiss}
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={16} />
          </button>
        </div>
        <p className="mb-5 text-xs text-fg-3">
          A tailored copy of{' '}
          <span className="text-fg-2">&ldquo;{resumeTitle}&rdquo;</span> will be created and
          optimized for the job description. The original is never modified.
        </p>

        {/* Step 1: Form */}
        {step === 'form' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-2">
                  Company <span className="text-fg-3">(optional)</span>
                </label>
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Google"
                  maxLength={200}
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-fg-2">
                  Role <span className="text-fg-3">(optional)</span>
                </label>
                <input
                  type="text"
                  value={roleTitle}
                  onChange={(e) => setRoleTitle(e.target.value)}
                  placeholder="e.g. Senior SWE"
                  maxLength={200}
                  className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-fg-2">
                Job Description <span className="text-err">*</span>
              </label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste the full job description here..."
                rows={9}
                maxLength={10000}
                autoFocus
                className="w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
              <p className="mt-1 text-right text-[10px] text-fg-3">
                {jobDescription.length}/10000
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={jobDescription.trim().length < 10 || isSubmitting}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-xs font-semibold text-accent-strong ring-1 ring-accent transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isSubmitting ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Zap size={13} />
                )}
                Start Tailoring
              </button>
            </div>
          </div>
        )}

        {/* Step 2: Progress */}
        {step === 'progress' && (
          <div className="space-y-5">
            <div className="rounded-[var(--radius-md)] border border-line bg-surface p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-fg-2">
                  {state.stage || 'Initializing...'}
                </span>
                <span className="text-xs tabular-nums text-fg-3">{state.percent}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-2">
                <div
                  className="h-full rounded-full bg-accent transition-all duration-500"
                  style={{ width: `${state.percent}%` }}
                />
              </div>
              {state.message && (
                <p className="mt-2 text-xs text-fg-3">{state.message}</p>
              )}
            </div>
            <p className="text-center text-xs text-fg-3">
              This typically takes 30–90 seconds. Don&apos;t close this window.
            </p>
            <div className="flex justify-end">
              <button
                onClick={handleCancel}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === 'done' && (
          <div className="space-y-5">
            <div className="flex flex-col items-center gap-3 py-4">
              <CheckCircle size={40} className="text-ok" />
              <p className="text-base font-semibold text-fg">Tailored resume created!</p>
              <p className="text-center text-xs text-fg-2">
                The optimized version has been saved as a new variant.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Close
              </button>
              <button
                onClick={() => forkId && router.push(`/workspace/${forkId}/edit`)}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110"
              >
                Open Tailored Resume
                <ArrowRight size={13} />
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {step === 'error' && (
          <div className="space-y-5">
            <div className="flex flex-col items-center gap-3 py-4">
              <AlertCircle size={40} className="text-err" />
              <p className="text-base font-semibold text-fg">Tailoring failed</p>
              <p className="text-center text-xs text-fg-2">{errorMessage}</p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
              >
                Close
              </button>
              <button
                onClick={handleTryAgain}
                className="rounded-[var(--radius-md)] border border-accent bg-accent-soft px-4 py-2 text-xs font-semibold text-accent-strong transition hover:brightness-110"
              >
                Try Again
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
