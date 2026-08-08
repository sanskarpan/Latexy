'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { motion, AnimatePresence } from 'framer-motion'
import {
  ArrowLeft, CheckCircle2, ExternalLink, Loader2,
  Plus, Trash2, XCircle, Zap,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type BatchJobItem,
  type BatchJobStatus,
  type BatchStatusResponse,
} from '@/lib/api-client'
// Note: bulkExport exports all user resumes, not batch-specific ones.
// Per-variant "View" links are used instead for individual access.

// ------------------------------------------------------------------ //
//  Types                                                               //
// ------------------------------------------------------------------ //

type RowData = {
  id: string
  company_name: string
  role_title: string
  job_description: string
  job_url: string
}

function emptyRow(): RowData {
  return {
    id: crypto.randomUUID(),
    company_name: '',
    role_title: '',
    job_description: '',
    job_url: '',
  }
}

// ------------------------------------------------------------------ //
//  Status badge                                                        //
// ------------------------------------------------------------------ //

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    queued:    { label: 'Queued',     cls: 'bg-surface-2 text-fg-2', icon: null },
    running:   { label: 'Running',    cls: 'bg-accent-soft text-accent-strong animate-pulse', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    processing:{ label: 'Running',    cls: 'bg-accent-soft text-accent-strong animate-pulse', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    completed: { label: 'Complete',   cls: 'bg-ok/20 text-ok', icon: <CheckCircle2 className="w-3 h-3" /> },
    failed:    { label: 'Failed',     cls: 'bg-err/20 text-err', icon: <XCircle className="w-3 h-3" /> },
    cancelled: { label: 'Cancelled',  cls: 'bg-surface-2 text-fg-3', icon: null },
  }
  const cfg = map[status] ?? map['queued']
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cfg.cls}`}>
      {cfg.icon}
      {cfg.label}
    </span>
  )
}

// ------------------------------------------------------------------ //
//  Page                                                                //
// ------------------------------------------------------------------ //

export default function BatchTailorPage() {
  const params = useParams()
  const resumeId = params.resumeId as string

  const [rows, setRows] = useState<RowData[]>([emptyRow()])
  const [submitting, setSubmitting] = useState(false)

  // Batch state (after submission)
  const [batchId, setBatchId] = useState<string | null>(null)
  const [batchStatus, setBatchStatus] = useState<BatchStatusResponse | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // ---------------------------------------------------------------- //
  //  Row helpers                                                       //
  // ---------------------------------------------------------------- //

  function updateRow(id: string, field: keyof RowData, value: string) {
    setRows(prev => {
      const updated = prev.map(r => r.id === id ? { ...r, [field]: value } : r)
      // Auto-add new row if the last row starts being filled in
      const last = updated[updated.length - 1]
      if (last.id === id && (last.company_name || last.role_title || last.job_description) && updated.length < 10) {
        return [...updated, emptyRow()]
      }
      return updated
    })
  }

  function removeRow(id: string) {
    setRows(prev => {
      const next = prev.filter(r => r.id !== id)
      return next.length === 0 ? [emptyRow()] : next
    })
  }

  function addRow() {
    if (rows.length >= 10) return
    setRows(prev => [...prev, emptyRow()])
  }

  // ---------------------------------------------------------------- //
  //  Submit                                                            //
  // ---------------------------------------------------------------- //

  async function handleSubmit() {
    const filled = rows.filter(r => r.company_name.trim() && r.role_title.trim() && r.job_description.trim())
    if (filled.length === 0) {
      toast.error('Fill in at least one complete job entry')
      return
    }

    const items: BatchJobItem[] = filled.map(r => ({
      company_name: r.company_name.trim(),
      role_title: r.role_title.trim(),
      job_description: r.job_description.trim(),
      job_url: r.job_url.trim() || undefined,
    }))

    setSubmitting(true)
    try {
      const res = await apiClient.createBatchTailor({ resume_id: resumeId, jobs: items })
      setBatchId(res.batch_id)
      toast.success(`Batch started — ${items.length} job${items.length > 1 ? 's' : ''} queued`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Failed to start batch: ${msg}`)
    } finally {
      setSubmitting(false)
    }
  }

  // ---------------------------------------------------------------- //
  //  Polling                                                           //
  // ---------------------------------------------------------------- //

  const fetchBatchStatus = useCallback(async () => {
    if (!batchId) return
    try {
      const status = await apiClient.getBatchStatus(batchId)
      setBatchStatus(status)
      // Stop polling when all jobs are in a terminal state
      const terminal = new Set(['completed', 'failed', 'cancelled'])
      const done = status.jobs.every(j => terminal.has(j.status))
      if (done && pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
    } catch {
      // swallow — network hiccup shouldn't crash UI
    }
  }, [batchId])

  useEffect(() => {
    if (!batchId) return
    fetchBatchStatus()
    pollRef.current = setInterval(fetchBatchStatus, 3000)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [batchId, fetchBatchStatus])

  // ---------------------------------------------------------------- //
  //  Helpers                                                           //
  // ---------------------------------------------------------------- //

  const allComplete = batchStatus
    ? batchStatus.jobs.every(j => j.status === 'completed')
    : false

  // ---------------------------------------------------------------- //
  //  Render                                                            //
  // ---------------------------------------------------------------- //

  return (
    <div className="min-h-screen bg-bg text-fg">
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <Link
            href={`/workspace/${resumeId}/edit`}
            className="p-2 rounded-[var(--radius-md)] text-fg-2 hover:text-fg hover:bg-surface-2 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-fg flex items-center gap-2">
              <Zap className="w-6 h-6 text-accent" />
              Batch Tailor
            </h1>
            <p className="text-sm text-fg-2 mt-0.5">
              Submit up to 10 job descriptions — get a tailored resume variant for each.
            </p>
          </div>
        </div>

        {/* Input form — shown before submission */}
        {!batchId && (
          <div className="space-y-4">
            <AnimatePresence initial={false}>
              {rows.map((row, idx) => (
                <motion.div
                  key={row.id}
                  initial={{ opacity: 0, y: -8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, height: 0, marginBottom: 0, overflow: 'hidden' }}
                  transition={{ duration: 0.15 }}
                  className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 space-y-3"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-fg-3 uppercase tracking-wider">
                      Job {idx + 1}
                    </span>
                    {rows.length > 1 && (
                      <button
                        onClick={() => removeRow(row.id)}
                        className="p-1 rounded-[var(--radius-md)] text-fg-3 hover:text-err hover:bg-surface-2 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-fg-3 mb-1">Company *</label>
                      <input
                        className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:border-accent"
                        placeholder="Acme Corp"
                        value={row.company_name}
                        onChange={e => updateRow(row.id, 'company_name', e.target.value)}
                        maxLength={200}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-fg-3 mb-1">Role Title *</label>
                      <input
                        className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:border-accent"
                        placeholder="Software Engineer"
                        value={row.role_title}
                        onChange={e => updateRow(row.id, 'role_title', e.target.value)}
                        maxLength={200}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs text-fg-3 mb-1">Job Description *</label>
                    <textarea
                      className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:border-accent resize-none"
                      rows={4}
                      placeholder="Paste the full job description here…"
                      value={row.job_description}
                      onChange={e => updateRow(row.id, 'job_description', e.target.value)}
                      maxLength={20000}
                    />
                    <p className="text-right text-xs text-fg-3 mt-0.5">
                      {row.job_description.length.toLocaleString()} / 20,000
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs text-fg-3 mb-1">Job URL (optional)</label>
                    <input
                      className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:border-accent"
                      placeholder="https://linkedin.com/jobs/…"
                      value={row.job_url}
                      onChange={e => updateRow(row.id, 'job_url', e.target.value)}
                      maxLength={500}
                    />
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>

            <div className="flex items-center justify-between pt-2">
              <button
                onClick={addRow}
                disabled={rows.length >= 10}
                className="flex items-center gap-2 px-4 py-2 rounded-[var(--radius-md)] border border-line-2 text-fg-2 hover:text-fg hover:bg-surface-2 text-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Plus className="w-4 h-4" />
                Add Row
                <span className="text-fg-3 text-xs">{rows.length}/10</span>
              </button>

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="flex items-center gap-2 px-6 py-2.5 rounded-[var(--radius-md)] bg-accent hover:brightness-110 text-accent-fg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {submitting ? (
                  <><Loader2 className="w-4 h-4 animate-spin" /> Starting…</>
                ) : (
                  <><Zap className="w-4 h-4" /> Start Batch Tailor</>
                )}
              </button>
            </div>
          </div>
        )}

        {/* Progress board — shown after submission */}
        {batchId && batchStatus && (
          <div className="space-y-4">
            <div className="flex items-center justify-between mb-2">
              <div>
                <p className="text-sm text-fg-2">
                  Batch <span className="font-mono text-fg-2">{batchId.slice(0, 8)}…</span>
                  {' · '}
                  <span className="capitalize">{batchStatus.status}</span>
                </p>
              </div>
              <div className="flex items-center gap-3">
                {allComplete && (
                  <span className="text-xs text-ok font-medium">All complete — use View links below</span>
                )}
                <button
                  onClick={() => {
                    setBatchId(null)
                    setBatchStatus(null)
                    setRows([emptyRow()])
                  }}
                  className="px-4 py-2 rounded-[var(--radius-md)] border border-line-2 text-fg-2 hover:text-fg hover:bg-surface-2 text-sm transition-colors"
                >
                  New Batch
                </button>
              </div>
            </div>

            <div className="space-y-3">
              {batchStatus.jobs.map(job => (
                <JobCard key={job.job_id} job={job} resumeId={resumeId} />
              ))}
            </div>

            {!allComplete && (
              <p className="text-center text-xs text-fg-3 pt-2">
                Polling every 3s…
              </p>
            )}
          </div>
        )}

        {/* Loading state before first poll result */}
        {batchId && !batchStatus && (
          <div className="flex justify-center py-16">
            <Loader2 className="w-8 h-8 animate-spin text-accent" />
          </div>
        )}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ //
//  Job card                                                            //
// ------------------------------------------------------------------ //

function JobCard({ job, resumeId }: { job: BatchJobStatus; resumeId: string }) {
  return (
    <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-4 flex items-center gap-4">
      <div className="flex-1 min-w-0">
        <p className="font-medium text-fg truncate">{job.role_title}</p>
        <p className="text-sm text-fg-2 truncate">{job.company_name}</p>
      </div>

      <StatusBadge status={job.status} />

      {job.status === 'completed' && job.variant_resume_id && (
        <Link
          href={`/workspace/${job.variant_resume_id}/edit`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-[var(--radius-md)] border border-line-2 text-fg-2 hover:text-fg hover:bg-surface-2 text-xs transition-colors"
        >
          View <ExternalLink className="w-3 h-3" />
        </Link>
      )}
    </div>
  )
}
