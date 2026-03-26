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

  const { state, cancel } = useJobStream(jobId)

  // Watch job completion / failure
  useEffect(() => {
    if (!jobId || step !== 'progress') return
    if (state.status === 'completed') {
      if (forkId && state.streamingLatex) {
        apiClient.updateResume(forkId, { latex_content: state.streamingLatex }).catch(() => {
          // Non-fatal — fork still exists with original content
        })
      }
      setStep('done')
      onDone?.(forkId!)
    } else if (state.status === 'failed' || state.status === 'cancelled') {
      setStep('error')
      setErrorMessage(state.error ?? 'Optimization failed. Please try again.')
    }
  }, [state.status, jobId, step, forkId, state.streamingLatex, onDone])

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
    setStep('form')
    setJobId(null)
    setForkId(null)
    setErrorMessage(null)
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap size={16} className="text-amber-400" />
            <h3 className="text-base font-semibold text-white">Quick Tailor</h3>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={16} />
          </button>
        </div>
        <p className="mb-5 text-xs text-zinc-500">
          A tailored copy of{' '}
          <span className="text-zinc-300">&ldquo;{resumeTitle}&rdquo;</span> will be created and
          optimized for the job description. The original is never modified.
        </p>

        {/* Step 1: Form */}
        {step === 'form' && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                  Company <span className="text-zinc-600">(optional)</span>
                </label>
                <input
                  type="text"
                  value={companyName}
                  onChange={(e) => setCompanyName(e.target.value)}
                  placeholder="e.g. Google"
                  maxLength={200}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-amber-300/40"
                />
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                  Role <span className="text-zinc-600">(optional)</span>
                </label>
                <input
                  type="text"
                  value={roleTitle}
                  onChange={(e) => setRoleTitle(e.target.value)}
                  placeholder="e.g. Senior SWE"
                  maxLength={200}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-amber-300/40"
                />
              </div>
            </div>
            <div>
              <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                Job Description <span className="text-rose-400">*</span>
              </label>
              <textarea
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste the full job description here..."
                rows={9}
                maxLength={10000}
                autoFocus
                className="w-full resize-none rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-zinc-100 outline-none transition focus:border-amber-300/40"
              />
              <p className="mt-1 text-right text-[10px] text-zinc-600">
                {jobDescription.length}/10000
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={jobDescription.trim().length < 10 || isSubmitting}
                className="flex items-center gap-1.5 rounded-lg bg-amber-500/20 px-4 py-2 text-xs font-semibold text-amber-300 ring-1 ring-amber-400/30 transition hover:bg-amber-500/30 disabled:cursor-not-allowed disabled:opacity-50"
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
            <div className="rounded-xl border border-white/[0.06] bg-white/[0.02] p-4">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-xs font-medium text-zinc-300">
                  {state.stage || 'Initializing...'}
                </span>
                <span className="text-xs tabular-nums text-zinc-500">{state.percent}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-amber-400 transition-all duration-500"
                  style={{ width: `${state.percent}%` }}
                />
              </div>
              {state.message && (
                <p className="mt-2 text-xs text-zinc-500">{state.message}</p>
              )}
            </div>
            <p className="text-center text-xs text-zinc-600">
              This typically takes 30–90 seconds. Don&apos;t close this window.
            </p>
            <div className="flex justify-end">
              <button
                onClick={handleCancel}
                className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
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
              <CheckCircle size={40} className="text-emerald-400" />
              <p className="text-base font-semibold text-white">Tailored resume created!</p>
              <p className="text-center text-xs text-zinc-400">
                The optimized version has been saved as a new variant.
              </p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
              >
                Close
              </button>
              <button
                onClick={() => forkId && router.push(`/workspace/${forkId}/edit`)}
                className="flex items-center gap-1.5 rounded-lg bg-emerald-500/20 px-4 py-2 text-xs font-semibold text-emerald-300 ring-1 ring-emerald-400/30 transition hover:bg-emerald-500/30"
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
              <AlertCircle size={40} className="text-rose-400" />
              <p className="text-base font-semibold text-white">Tailoring failed</p>
              <p className="text-center text-xs text-zinc-400">{errorMessage}</p>
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={onClose}
                className="rounded-lg border border-white/10 px-4 py-2 text-xs font-semibold text-zinc-400 transition hover:text-zinc-200"
              >
                Close
              </button>
              <button
                onClick={handleTryAgain}
                className="rounded-lg border border-amber-400/20 bg-amber-500/10 px-4 py-2 text-xs font-semibold text-amber-300 transition hover:bg-amber-500/20"
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
