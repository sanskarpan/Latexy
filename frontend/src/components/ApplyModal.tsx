'use client'

/**
 * ApplyModal — Feature 87: One-Click Job Application Integration
 *
 * Multi-step modal:
 *  1. Paste job URL → auto-detect platform (Greenhouse / Lever)
 *  2. Show detected job details (title, company, location)
 *  3. Fill applicant info + optional cover letter
 *  4. Submit → success screen with tracker link or error fallback
 */

import { useState, useCallback } from 'react'
import {
  X,
  ArrowRight,
  ArrowLeft,
  Loader2,
  CheckCircle2,
  AlertCircle,
  ExternalLink,
  Briefcase,
  MapPin,
  Building2,
  Send,
} from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import type {
  JobPreviewResponse,
  ApplicationSubmission,
  GreenhouseApplyRequest,
  LeverApplyRequest,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'

// ── Types ────────────────────────────────────────────────────────────────────

type Step = 'url' | 'preview' | 'form' | 'success' | 'error'

interface Props {
  resumeId: string
  resumeTitle?: string
  defaultJobUrl?: string
  onClose: () => void
}

// ── Component ────────────────────────────────────────────────────────────────

export default function ApplyModal({ resumeId, resumeTitle, defaultJobUrl = '', onClose }: Props) {
  const { data: session } = useSession()
  const user = session?.user

  // Step state
  const [step, setStep] = useState<Step>('url')

  // URL / detection
  const [jobUrl, setJobUrl] = useState(defaultJobUrl)
  const [detecting, setDetecting] = useState(false)
  const [preview, setPreview] = useState<JobPreviewResponse | null>(null)

  // Form fields
  const firstName = session?.user?.name?.split(' ')[0] ?? ''
  const lastName = session?.user?.name?.split(' ').slice(1).join(' ') ?? ''
  const [formFirst, setFormFirst] = useState(firstName)
  const [formLast, setFormLast] = useState(lastName)
  const [formEmail, setFormEmail] = useState(user?.email ?? '')
  const [formPhone, setFormPhone] = useState('')
  const [formOrg, setFormOrg] = useState('')       // Lever only
  const [coverLetter, setCoverLetter] = useState('')

  // Submission
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<ApplicationSubmission | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  // ── Step 1: detect platform from URL ─────────────────────────────────────

  const handleDetect = useCallback(async () => {
    if (!jobUrl.trim()) return
    setDetecting(true)
    try {
      const detected = await apiClient.detectJobPlatform(jobUrl.trim())
      if (detected.platform === 'unknown') {
        toast.error('Could not detect job platform. Only Greenhouse and Lever URLs are supported.')
        setDetecting(false)
        return
      }

      // Fetch full preview
      const prev = detected.platform === 'greenhouse'
        ? await apiClient.previewGreenhouseJob(jobUrl.trim())
        : await apiClient.previewLeverJob(jobUrl.trim())

      setPreview(prev)
      setStep('preview')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to fetch job details'
      toast.error(msg)
    } finally {
      setDetecting(false)
    }
  }, [jobUrl])

  // ── Step 3: submit application ────────────────────────────────────────────

  const handleSubmit = useCallback(async () => {
    if (!preview) return
    setSubmitting(true)
    try {
      let sub: ApplicationSubmission

      if (preview.platform === 'greenhouse') {
        const body: GreenhouseApplyRequest = {
          job_url: jobUrl,
          resume_id: resumeId,
          first_name: formFirst,
          last_name: formLast,
          email: formEmail,
          phone: formPhone,
          cover_letter: coverLetter || undefined,
        }
        sub = await apiClient.applyGreenhouse(body)
      } else {
        const body: LeverApplyRequest = {
          job_url: jobUrl,
          resume_id: resumeId,
          name: `${formFirst} ${formLast}`.trim(),
          email: formEmail,
          phone: formPhone,
          org: formOrg || undefined,
          cover_letter: coverLetter || undefined,
        }
        sub = await apiClient.applyLever(body)
      }

      setResult(sub)
      setStep('success')
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : 'Submission failed. Try applying directly on the job board.'
      setErrorMessage(msg)
      setStep('error')
    } finally {
      setSubmitting(false)
    }
  }, [preview, jobUrl, resumeId, formFirst, formLast, formEmail, formPhone, formOrg, coverLetter])

  // ── Render ────────────────────────────────────────────────────────────────

  const platformLabel = preview?.platform === 'greenhouse' ? 'Greenhouse' : 'Lever'
  const platformColor = preview?.platform === 'greenhouse'
    ? 'text-emerald-300'
    : 'text-violet-300'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
      <div className="relative w-full max-w-lg rounded-2xl border border-white/[0.08] bg-[#0f0f0f] shadow-2xl">

        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-6 py-4">
          <div>
            <h2 className="text-base font-semibold text-white">Apply with One Click</h2>
            {resumeTitle && (
              <p className="mt-0.5 text-xs text-zinc-500">Using: {resumeTitle}</p>
            )}
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={15} />
          </button>
        </div>

        {/* Step indicator */}
        <div className="flex gap-1 px-6 pt-4">
          {(['url', 'preview', 'form'] as Step[]).map((s, i) => (
            <div
              key={s}
              className={`h-1 flex-1 rounded-full transition-all ${
                step === 'success' || step === 'error'
                  ? 'bg-emerald-500/30'
                  : i <= (['url', 'preview', 'form'] as Step[]).indexOf(step as Step)
                  ? 'bg-orange-400/60'
                  : 'bg-white/[0.06]'
              }`}
            />
          ))}
        </div>

        <div className="px-6 py-5 space-y-5">

          {/* ── STEP: URL ──────────────────────────────────────── */}
          {step === 'url' && (
            <>
              <div>
                <label className="mb-1.5 block text-xs font-medium text-zinc-400">
                  Job URL
                </label>
                <input
                  type="url"
                  placeholder="https://boards.greenhouse.io/company/jobs/123456"
                  value={jobUrl}
                  onChange={e => setJobUrl(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleDetect() }}
                  className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-sm text-white outline-none transition placeholder:text-zinc-600 focus:border-orange-300/40"
                  autoFocus
                />
                <p className="mt-1.5 text-[11px] text-zinc-600">
                  Supports Greenhouse (boards.greenhouse.io) and Lever (jobs.lever.co)
                </p>
              </div>

              <button
                onClick={handleDetect}
                disabled={!jobUrl.trim() || detecting}
                className="flex w-full items-center justify-center gap-2 rounded-xl bg-orange-400/15 border border-orange-400/25 px-4 py-3 text-sm font-semibold text-orange-200 transition hover:bg-orange-400/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {detecting ? (
                  <><Loader2 size={14} className="animate-spin" /> Fetching job details…</>
                ) : (
                  <><ArrowRight size={14} /> Continue</>
                )}
              </button>
            </>
          )}

          {/* ── STEP: PREVIEW ─────────────────────────────────── */}
          {step === 'preview' && preview && (
            <>
              <div className="rounded-xl border border-white/[0.07] bg-white/[0.03] p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] font-bold uppercase tracking-[0.12em] ${platformColor}`}>
                    {platformLabel}
                  </span>
                </div>
                <div>
                  <h3 className="text-base font-semibold text-white line-clamp-2">
                    {preview.title || 'Unknown role'}
                  </h3>
                  <div className="mt-2 flex flex-wrap gap-3 text-xs text-zinc-400">
                    <span className="flex items-center gap-1">
                      <Building2 size={11} />
                      {preview.company}
                    </span>
                    {preview.location && (
                      <span className="flex items-center gap-1">
                        <MapPin size={11} />
                        {preview.location}
                      </span>
                    )}
                    {preview.team && (
                      <span className="flex items-center gap-1">
                        <Briefcase size={11} />
                        {preview.team}
                      </span>
                    )}
                  </div>
                </div>
                <a
                  href={preview.apply_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-300 transition"
                >
                  View on {platformLabel} <ExternalLink size={10} />
                </a>
              </div>

              <p className="text-xs text-zinc-500">
                We will submit your compiled resume PDF directly to this posting. You&apos;ll fill in your
                contact details next.
              </p>

              <div className="flex gap-3">
                <button
                  onClick={() => setStep('url')}
                  className="flex items-center gap-1.5 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-zinc-400 transition hover:text-zinc-200"
                >
                  <ArrowLeft size={13} /> Back
                </button>
                <button
                  onClick={() => setStep('form')}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-orange-400/15 border border-orange-400/25 px-4 py-2.5 text-sm font-semibold text-orange-200 transition hover:bg-orange-400/20"
                >
                  Fill in details <ArrowRight size={13} />
                </button>
              </div>
            </>
          )}

          {/* ── STEP: FORM ────────────────────────────────────── */}
          {step === 'form' && preview && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1 block text-[11px] text-zinc-500">First name *</label>
                  <input
                    value={formFirst}
                    onChange={e => setFormFirst(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-[11px] text-zinc-500">Last name *</label>
                  <input
                    value={formLast}
                    onChange={e => setFormLast(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                  />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[11px] text-zinc-500">Email *</label>
                <input
                  type="email"
                  value={formEmail}
                  onChange={e => setFormEmail(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                />
              </div>

              <div>
                <label className="mb-1 block text-[11px] text-zinc-500">Phone</label>
                <input
                  type="tel"
                  value={formPhone}
                  onChange={e => setFormPhone(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                />
              </div>

              {preview.platform === 'lever' && (
                <div>
                  <label className="mb-1 block text-[11px] text-zinc-500">Company / School</label>
                  <input
                    value={formOrg}
                    onChange={e => setFormOrg(e.target.value)}
                    placeholder="Current employer or university"
                    className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                  />
                </div>
              )}

              <div>
                <label className="mb-1 block text-[11px] text-zinc-500">
                  Cover letter <span className="text-zinc-700">(optional)</span>
                </label>
                <textarea
                  value={coverLetter}
                  onChange={e => setCoverLetter(e.target.value)}
                  rows={4}
                  placeholder="Write a short cover letter or leave blank…"
                  className="w-full resize-none rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none focus:border-orange-300/40"
                />
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => setStep('preview')}
                  className="flex items-center gap-1.5 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-zinc-400 transition hover:text-zinc-200"
                >
                  <ArrowLeft size={13} /> Back
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={submitting || !formFirst || !formLast || !formEmail}
                  className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-orange-400/15 border border-orange-400/25 px-4 py-2.5 text-sm font-semibold text-orange-200 transition hover:bg-orange-400/20 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {submitting ? (
                    <><Loader2 size={14} className="animate-spin" /> Submitting…</>
                  ) : (
                    <><Send size={13} /> Submit Application</>
                  )}
                </button>
              </div>
            </>
          )}

          {/* ── STEP: SUCCESS ─────────────────────────────────── */}
          {step === 'success' && result && (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <CheckCircle2 size={40} className="text-emerald-400" />
              <div>
                <h3 className="text-base font-semibold text-white">Application Submitted!</h3>
                <p className="mt-1 text-sm text-zinc-400">
                  Your resume was sent to{' '}
                  <span className="font-medium text-zinc-200">
                    {result.company_name || preview?.company}
                  </span>{' '}
                  for <span className="font-medium text-zinc-200">{result.job_title || 'the role'}</span>.
                </p>
              </div>
              {result.job_tracker_id && (
                <a
                  href="/tracker"
                  className="rounded-xl border border-sky-400/25 bg-sky-400/10 px-4 py-2 text-sm font-semibold text-sky-300 transition hover:bg-sky-400/20"
                >
                  View in Job Tracker →
                </a>
              )}
              <button onClick={onClose} className="text-xs text-zinc-600 hover:text-zinc-400 transition">
                Close
              </button>
            </div>
          )}

          {/* ── STEP: ERROR ───────────────────────────────────── */}
          {step === 'error' && (
            <div className="flex flex-col items-center gap-4 py-4 text-center">
              <AlertCircle size={36} className="text-rose-400" />
              <div>
                <h3 className="text-base font-semibold text-white">Submission Failed</h3>
                <p className="mt-1 text-sm text-zinc-400 break-words">
                  {errorMessage || 'An unexpected error occurred.'}
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => setStep('form')}
                  className="rounded-xl border border-white/10 px-4 py-2 text-sm text-zinc-400 transition hover:text-zinc-200"
                >
                  Try Again
                </button>
                {preview?.apply_url && (
                  <a
                    href={preview.apply_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1.5 rounded-xl border border-amber-400/25 bg-amber-400/10 px-4 py-2 text-sm font-semibold text-amber-300 transition hover:bg-amber-400/20"
                  >
                    Open on {platformLabel} <ExternalLink size={12} />
                  </a>
                )}
              </div>
            </div>
          )}

        </div>
      </div>
    </div>
  )
}
