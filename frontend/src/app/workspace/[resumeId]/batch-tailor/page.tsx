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
    queued:    { label: 'Queued',     cls: 'bg-zinc-700 text-zinc-300', icon: null },
    running:   { label: 'Running',    cls: 'bg-blue-600/30 text-blue-300 animate-pulse', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    processing:{ label: 'Running',    cls: 'bg-blue-600/30 text-blue-300 animate-pulse', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    completed: { label: 'Complete',   cls: 'bg-emerald-600/30 text-emerald-300', icon: <CheckCircle2 className="w-3 h-3" /> },
    failed:    { label: 'Failed',     cls: 'bg-red-600/30 text-red-300', icon: <XCircle className="w-3 h-3" /> },
    cancelled: { label: 'Cancelled',  cls: 'bg-zinc-600/30 text-zinc-400', icon: null },
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

  const variantIds = batchStatus
    ? batchStatus.jobs.map(j => j.variant_resume_id).filter(Boolean) as string[]
    : []

  async function downloadAll() {
    if (variantIds.length === 0) return
    try {
      const blob = await apiClient.bulkExport('pdf')
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'batch-tailored-resumes.zip'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      toast.error('Export failed')
    }
  }

  // ---------------------------------------------------------------- //
  //  Render                                                            //
  // ---------------------------------------------------------------- //

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <Link
            href={`/workspace/${resumeId}/edit`}
            className="p-2 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-zinc-100 flex items-center gap-2">
              <Zap className="w-6 h-6 text-violet-400" />
              Bulk Tailor
            </h1>
            <p className="text-sm text-zinc-400 mt-0.5">
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
                  className="border border-zinc-800 rounded-xl p-4 bg-zinc-900/50 space-y-3"
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                      Job {idx + 1}
                    </span>
                    {rows.length > 1 && (
                      <button
                        onClick={() => removeRow(row.id)}
                        className="p-1 rounded text-zinc-600 hover:text-red-400 hover:bg-zinc-800 transition-colors"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">Company *</label>
                      <input
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500"
                        placeholder="Acme Corp"
                        value={row.company_name}
                        onChange={e => updateRow(row.id, 'company_name', e.target.value)}
                        maxLength={200}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-zinc-500 mb-1">Role Title *</label>
                      <input
                        className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500"
                        placeholder="Software Engineer"
                        value={row.role_title}
                        onChange={e => updateRow(row.id, 'role_title', e.target.value)}
                        maxLength={200}
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs text-zinc-500 mb-1">Job Description *</label>
                    <textarea
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500 resize-none"
                      rows={4}
                      placeholder="Paste the full job description here…"
                      value={row.job_description}
                      onChange={e => updateRow(row.id, 'job_description', e.target.value)}
                      maxLength={20000}
                    />
                    <p className="text-right text-xs text-zinc-600 mt-0.5">
                      {row.job_description.length.toLocaleString()} / 20,000
                    </p>
                  </div>

                  <div>
                    <label className="block text-xs text-zinc-500 mb-1">Job URL (optional)</label>
                    <input
                      className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none focus:border-violet-500"
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
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-zinc-700 text-zinc-400 hover:text-zinc-100 hover:border-zinc-500 text-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
              >
                <Plus className="w-4 h-4" />
                Add Row
                <span className="text-zinc-600 text-xs">{rows.length}/10</span>
              </button>

              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="flex items-center gap-2 px-6 py-2.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
                <p className="text-sm text-zinc-400">
                  Batch <span className="font-mono text-zinc-300">{batchId.slice(0, 8)}…</span>
                  {' · '}
                  <span className="capitalize">{batchStatus.status}</span>
                </p>
              </div>
              <div className="flex items-center gap-3">
                {allComplete && (
                  <button
                    onClick={downloadAll}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors"
                  >
                    Download All as ZIP
                  </button>
                )}
                <button
                  onClick={() => {
                    setBatchId(null)
                    setBatchStatus(null)
                    setRows([emptyRow()])
                  }}
                  className="px-4 py-2 rounded-lg border border-zinc-700 text-zinc-400 hover:text-zinc-100 text-sm transition-colors"
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
              <p className="text-center text-xs text-zinc-600 pt-2">
                Polling every 3s…
              </p>
            )}
          </div>
        )}

        {/* Loading state before first poll result */}
        {batchId && !batchStatus && (
          <div className="flex justify-center py-16">
            <Loader2 className="w-8 h-8 animate-spin text-violet-400" />
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
    <div className="border border-zinc-800 rounded-xl p-4 bg-zinc-900/50 flex items-center gap-4">
      <div className="flex-1 min-w-0">
        <p className="font-medium text-zinc-100 truncate">{job.role_title}</p>
        <p className="text-sm text-zinc-400 truncate">{job.company_name}</p>
      </div>

      <StatusBadge status={job.status} />

      {job.status === 'completed' && job.variant_resume_id && (
        <Link
          href={`/workspace/${job.variant_resume_id}/edit`}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-700 text-zinc-300 hover:text-zinc-100 hover:border-zinc-500 text-xs transition-colors"
        >
          View <ExternalLink className="w-3 h-3" />
        </Link>
      )}
    </div>
  )
}
