'use client'

import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type CreateApplicationRequest, type JobApplication, type ResumeResponse } from '@/lib/api-client'

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
}

export default function AddApplicationModal({
  onClose,
  onCreated,
  prefillResumeId,
  prefillResumeTitle,
}: AddApplicationModalProps) {
  const [companyName, setCompanyName] = useState('')
  const [roleTitle, setRoleTitle] = useState('')
  const [status, setStatus] = useState('applied')
  const [jobUrl, setJobUrl] = useState('')
  const [resumeId, setResumeId] = useState(prefillResumeId ?? '')
  const [jobDescription, setJobDescription] = useState('')
  const [notes, setNotes] = useState('')
  const [appliedAt, setAppliedAt] = useState(new Date().toISOString().slice(0, 10))
  const [showJD, setShowJD] = useState(false)
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [isSubmitting, setIsSubmitting] = useState(false)

  const firstInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    firstInputRef.current?.focus()
    apiClient.listResumes().then((data) => {
      setResumes(Array.isArray(data) ? data : [])
    }).catch(() => {})
  }, [])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
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
        className="relative w-full max-w-lg rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <h2 className="text-sm font-semibold text-fg">Add Application</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <X size={16} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4 p-5">
          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2 sm:col-span-1">
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Company *
              </label>
              <input
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
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Role *
              </label>
              <input
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
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Status
              </label>
              <select
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
              <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
                Applied On
              </label>
              <input
                type="date"
                value={appliedAt}
                onChange={(e) => setAppliedAt(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
              />
            </div>
          </div>

          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Job URL
            </label>
            <input
              type="url"
              value={jobUrl}
              onChange={(e) => setJobUrl(e.target.value)}
              placeholder="https://..."
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            />
          </div>

          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Linked Resume
            </label>
            <select
              value={resumeId}
              onChange={(e) => setResumeId(e.target.value)}
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
            >
              <option value="">— None —</option>
              {resumes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                  {prefillResumeId === r.id && prefillResumeTitle ? ` (${prefillResumeTitle})` : ''}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-widest text-fg-3">
              Notes
            </label>
            <textarea
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
