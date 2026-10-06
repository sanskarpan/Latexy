'use client'

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type CreateApplicationRequest, type JobApplication, type ResumeResponse } from '@/lib/api-client'
import type { ExtensionJobCapture } from '@/lib/extension-capture'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'

const STATUSES = [
  { value: 'applied', label: 'Applied' },
  { value: 'phone_screen', label: 'Phone Screen' },
  { value: 'technical', label: 'Technical' },
  { value: 'onsite', label: 'On-Site' },
  { value: 'offer', label: 'Offer' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'withdrawn', label: 'Withdrawn' },
]

interface AddApplicationModalProps {
  onClose: () => void
  onCreated: (app: JobApplication) => void
  // Pre-fill when opened from workspace card
  prefillResumeId?: string
  prefillResumeTitle?: string
  prefillCapture?: ExtensionJobCapture | null
}

export default function AddApplicationModal({
  onClose,
  onCreated,
  prefillResumeId,
  prefillResumeTitle,
  prefillCapture,
}: AddApplicationModalProps) {
  const [companyName, setCompanyName] = useState(prefillCapture?.company ?? '')
  const [roleTitle, setRoleTitle] = useState(prefillCapture?.title ?? '')
  const [status, setStatus] = useState('applied')
  const [jobUrl, setJobUrl] = useState(prefillCapture?.url ?? '')
  const [resumeId, setResumeId] = useState(prefillResumeId ?? '')
  const [jobDescription, setJobDescription] = useState(prefillCapture?.description ?? '')
  const [notes, setNotes] = useState(
    prefillCapture?.location ? `Location: ${prefillCapture.location}` : '',
  )
  const [appliedAt, setAppliedAt] = useState(new Date().toISOString().slice(0, 10))
  const [showJD, setShowJD] = useState(Boolean(prefillCapture?.description))
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [resumesLoading, setResumesLoading] = useState(true)
  const [resumesError, setResumesError] = useState<string | null>(null)
  const [resumesReloadNonce, setResumesReloadNonce] = useState(0)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const firstInputRef = useRef<HTMLInputElement>(null)
  const modalRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)

  // Open lifecycle: capture the trigger, move focus into the dialog, and
  // restore focus to the trigger on close.
  useEffect(() => {
    triggerRef.current = document.activeElement as HTMLElement | null
    firstInputRef.current?.focus()
    return () => {
      triggerRef.current?.focus?.()
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    setResumesLoading(true)
    setResumesError(null)
    apiClient.listAllResumes().then((data) => {
      if (!cancelled) setResumes(Array.isArray(data) ? data : [])
    }).catch((error) => {
      if (!cancelled) {
        setResumesError(error instanceof Error ? error.message : 'Failed to load resumes')
      }
    }).finally(() => {
      if (!cancelled) setResumesLoading(false)
    })
    return () => { cancelled = true }
  }, [resumesReloadNonce])

  // Keyboard handling: Escape closes the dialog, Tab is trapped within it.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
        return
      }
      if (e.key === 'Tab' && modalRef.current) {
        const focusables = Array.from(
          modalRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)
        ).filter((el) => el.offsetParent !== null || el === document.activeElement)
        if (focusables.length === 0) {
          e.preventDefault()
          modalRef.current.focus()
          return
        }
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        const active = document.activeElement
        if (e.shiftKey) {
          if (active === first || active === modalRef.current) {
            e.preventDefault()
            last.focus()
          }
        } else if (active === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onClose])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!companyName.trim() || !roleTitle.trim()) return

    setIsSubmitting(true)
    try {
      const body: CreateApplicationRequest = {
        company_name: companyName.trim(),
        role_title: roleTitle.trim(),
        status,
        job_url: jobUrl.trim() || undefined,
        resume_id: resumeId || undefined,
        job_description_text: jobDescription.trim() || undefined,
        notes: notes.trim() || undefined,
        applied_at: appliedAt ? new Date(appliedAt).toISOString() : undefined,
      }
      const created = await apiClient.createApplication(body)
      toast.success('Application added')
      onCreated(created)
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to add application')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        ref={modalRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-application-title"
        tabIndex={-1}
        className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-lg flex-col overflow-hidden rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)] focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-line px-5 py-4">
          <h2 id="add-application-title" className="text-sm font-semibold text-fg">Add Application</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="min-h-0 space-y-4 overflow-y-auto p-5">
          {prefillCapture && (
            <div className="rounded-[var(--radius-md)] border border-accent/30 bg-accent-soft px-3 py-2 text-xs leading-relaxed text-fg-2">
              Imported from the browser extension. Review every field before saving;
              this has not submitted an application to the employer.
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 sm:col-span-1">
              <label htmlFor="application-company" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Company *
              </label>
              <input
                id="application-company"
                ref={firstInputRef}
                type="text"
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="e.g. Google"
                required
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
            </div>
            <div className="col-span-2 sm:col-span-1">
              <label htmlFor="application-role" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Role *
              </label>
              <input
                id="application-role"
                type="text"
                value={roleTitle}
                onChange={(e) => setRoleTitle(e.target.value)}
                placeholder="e.g. Software Engineer"
                required
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="application-status" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Status
              </label>
              <select
                id="application-status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              >
                {STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="application-date" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Applied On
              </label>
              <input
                id="application-date"
                type="date"
                value={appliedAt}
                onChange={(e) => setAppliedAt(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
            </div>
          </div>

          <div>
            <label htmlFor="application-url" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Job URL
            </label>
            <input
              id="application-url"
              type="url"
              value={jobUrl}
              onChange={(e) => setJobUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            />
          </div>

          <div>
            <label htmlFor="application-resume" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Linked Resume
            </label>
            <select
              id="application-resume"
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              disabled={resumesLoading}
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            >
              <option value="">{resumesLoading ? 'Loading resumes…' : '— None —'}</option>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                  {prefillResumeId === r.id && prefillResumeTitle ? ` (${prefillResumeTitle})` : ''}
                </option>
              ))}
            </select>
            {resumesError && (
              <div role="alert" className="mt-2 flex items-center justify-between gap-3 text-xs text-err">
                <span>Resumes could not be loaded. You can add the application without one.</span>
                <button
                  type="button"
                  onClick={() => setResumesReloadNonce((value) => value + 1)}
                  className="shrink-0 font-semibold underline underline-offset-2"
                >
                  Retry
                </button>
              </div>
            )}
          </div>

          <div>
            <label htmlFor="application-notes" className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Notes
            </label>
            <textarea
              id="application-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Referral, recruiter name, etc."
              rows={2}
              className="w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            />
          </div>

          <div>
            <button
              type="button"
              onClick={() => setShowJD((v) => !v)}
              className="text-xs font-semibold text-fg-3 transition hover:text-fg-2"
            >
              {showJD ? '▲ Hide' : '▼ Show'} job description
            </button>
            {showJD && (
              <textarea
                aria-label="Job description"
                value={jobDescription}
                onChange={(e) => setJobDescription(e.target.value)}
                placeholder="Paste the full job description..."
                rows={5}
                className="mt-2 w-full resize-none rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
            )}
          </div>

          <div className="flex justify-end gap-2 border-t border-line pt-4">
            <button
              type="button"
              onClick={onClose}
              className="rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-semibold text-fg-2 transition hover:text-fg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting || !companyName.trim() || !roleTitle.trim()}
              className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-50"
            >
              {isSubmitting ? 'Adding…' : 'Add Application'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
