'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink, Loader2, Star, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ProjectEvidence } from '@/lib/api-client'
import { projectsToLatex, type ProjectSelection } from '@/lib/github-projects-latex'

/**
 * Import top PUBLIC GitHub projects and insert selected ones into the resume
 * (External-Sources-to-Resume, F1). Flow: check connection → start import job →
 * poll → render ranked ProjectEvidence cards with per-bullet checkboxes → build
 * a LaTeX block from the selection and hand it to the editor via onInsert.
 *
 * Everything routes through this review step — nothing is written to the resume
 * without the user choosing it.
 */

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 120_000

type Phase = 'checking' | 'disconnected' | 'importing' | 'ready' | 'error'

// Per-project selection: which suggested bullets are checked, keyed by project index.
type Selection = { included: boolean; bullets: Set<number> }

export default function GithubImportModal({
  isOpen,
  onClose,
  onInsert,
}: {
  isOpen: boolean
  onClose: () => void
  onInsert: (latex: string) => void
}) {
  const [phase, setPhase] = useState<Phase>('checking')
  const [projects, setProjects] = useState<ProjectEvidence[]>([])
  const [selection, setSelection] = useState<Record<number, Selection>>({})
  const [error, setError] = useState<string | null>(null)
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelledRef = useRef(false)

  const clearTimer = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }

  const startImport = useCallback(async () => {
    setPhase('importing')
    setError(null)
    try {
      const { job_id } = await apiClient.importGitHubProjects()
      const deadline = Date.now() + POLL_TIMEOUT_MS
      const poll = async () => {
        if (cancelledRef.current) return
        try {
          const res = await apiClient.getGitHubImportResult(job_id)
          if (cancelledRef.current) return
          if (res.status === 'completed') {
            setProjects(res.projects)
            // Default: include every project with all its suggested bullets checked.
            const init: Record<number, Selection> = {}
            res.projects.forEach((p, i) => {
              init[i] = { included: true, bullets: new Set(p.suggested_bullets.map((_, bi) => bi)) }
            })
            setSelection(init)
            setPhase('ready')
            return
          }
          if (res.status === 'failed') {
            setError(res.error || 'Import failed')
            setPhase('error')
            return
          }
          if (Date.now() > deadline) {
            setError('Import timed out. Please try again.')
            setPhase('error')
            return
          }
          pollTimer.current = setTimeout(poll, POLL_INTERVAL_MS)
        } catch (e) {
          if (cancelledRef.current) return
          setError(e instanceof Error ? e.message : 'Failed to load import result')
          setPhase('error')
        }
      }
      pollTimer.current = setTimeout(poll, POLL_INTERVAL_MS)
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Failed to start import'
      // The backend returns 400 with a "GitHub not connected" message.
      if (/not connected/i.test(msg)) setPhase('disconnected')
      else {
        setError(msg)
        setPhase('error')
      }
    }
  }, [])

  useEffect(() => {
    if (!isOpen) return
    cancelledRef.current = false
    let active = true
    const check = async () => {
      setPhase('checking')
      try {
        const status = await apiClient.getGitHubStatus()
        if (!active) return
        if (status.connected) startImport()
        else setPhase('disconnected')
      } catch {
        if (active) startImport() // status is best-effort; let import surface the real error
      }
    }
    check()
    return () => {
      active = false
      cancelledRef.current = true
      clearTimer()
    }
  }, [isOpen, startImport])

  const toggleProject = (i: number) =>
    setSelection((prev) => ({ ...prev, [i]: { ...prev[i], included: !prev[i].included } }))

  const toggleBullet = (i: number, bi: number) =>
    setSelection((prev) => {
      const bullets = new Set(prev[i].bullets)
      if (bullets.has(bi)) bullets.delete(bi)
      else bullets.add(bi)
      return { ...prev, [i]: { ...prev[i], bullets } }
    })

  const selectedCount = Object.values(selection).filter((s) => s.included).length

  const handleInsert = () => {
    const selections: ProjectSelection[] = projects
      .map((p, i) => ({ p, i }))
      .filter(({ i }) => selection[i]?.included)
      .map(({ p, i }) => ({
        project: p,
        bullets: p.suggested_bullets.filter((_, bi) => selection[i].bullets.has(bi)),
      }))
    const latex = projectsToLatex(selections)
    if (!latex) {
      toast.error('Select at least one project')
      return
    }
    onInsert(latex)
    toast.success(`Inserted ${selectedCount} project${selectedCount === 1 ? '' : 's'}`)
    onClose()
  }

  if (!isOpen) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.97, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97 }}
          className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">Import from GitHub</h2>
              <p className="mt-0.5 text-[11px] text-zinc-500">
                Your top public projects, AI-summarized into resume bullets. Public data only.
              </p>
            </div>
            <button onClick={onClose} className="rounded-lg p-1.5 text-zinc-500 transition hover:bg-white/5 hover:text-zinc-200">
              <X size={16} />
            </button>
          </div>

          <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {phase === 'checking' && (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-zinc-500">
                <Loader2 size={16} className="animate-spin" /> Checking GitHub connection…
              </div>
            )}

            {phase === 'importing' && (
              <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
                <Loader2 size={20} className="animate-spin text-orange-300" />
                <p className="text-sm text-zinc-300">Fetching and summarizing your projects…</p>
                <p className="text-[11px] text-zinc-600">This can take up to a minute for the LLM pass.</p>
              </div>
            )}

            {phase === 'disconnected' && (
              <div className="py-12 text-center">
                <p className="text-sm text-zinc-300">GitHub isn&apos;t connected yet.</p>
                <p className="mx-auto mt-1 max-w-sm text-[11px] text-zinc-500">
                  Connect your account in Settings → GitHub Integration, then reopen this import.
                </p>
                <a
                  href="/settings"
                  className="mt-4 inline-block rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/10"
                >
                  Go to Settings
                </a>
              </div>
            )}

            {phase === 'error' && (
              <div className="py-12 text-center">
                <div className="mx-auto max-w-md rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                  {error || 'Something went wrong.'}
                </div>
                <button
                  onClick={startImport}
                  className="mt-4 rounded-lg border border-white/10 bg-white/5 px-4 py-2 text-xs font-semibold text-zinc-200 transition hover:bg-white/10"
                >
                  Try again
                </button>
              </div>
            )}

            {phase === 'ready' && projects.length === 0 && (
              <div className="py-16 text-center text-sm text-zinc-500">
                No documented public projects found to import.
              </div>
            )}

            {phase === 'ready' && projects.length > 0 && (
              <ul className="space-y-3">
                {projects.map((p, i) => {
                  const sel = selection[i]
                  if (!sel) return null
                  return (
                    <li
                      key={`${p.title}-${i}`}
                      className={`rounded-xl border p-3 transition ${
                        sel.included ? 'border-white/10 bg-white/[0.02]' : 'border-white/5 opacity-55'
                      }`}
                    >
                      <div className="flex items-start gap-2.5">
                        <input
                          type="checkbox"
                          checked={sel.included}
                          onChange={() => toggleProject(i)}
                          className="mt-1 h-3.5 w-3.5 accent-orange-400"
                        />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <p className="truncate text-sm font-semibold text-zinc-100">{p.title}</p>
                            {p.metrics?.stars > 0 && (
                              <span className="flex items-center gap-0.5 text-[10px] text-zinc-500">
                                <Star size={10} /> {p.metrics.stars}
                              </span>
                            )}
                            {p.url && (
                              <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-zinc-500 hover:text-zinc-300">
                                <ExternalLink size={11} />
                              </a>
                            )}
                          </div>
                          {p.description && <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-400">{p.description}</p>}
                          {p.tech?.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {p.tech.slice(0, 8).map((t) => (
                                <span key={t} className="rounded bg-white/[0.05] px-1.5 py-0.5 text-[9px] text-zinc-400">
                                  {t}
                                </span>
                              ))}
                            </div>
                          )}
                          {sel.included && p.suggested_bullets.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {p.suggested_bullets.map((b, bi) => (
                                <label key={bi} className="flex cursor-pointer items-start gap-2 text-[11px] text-zinc-300">
                                  <input
                                    type="checkbox"
                                    checked={sel.bullets.has(bi)}
                                    onChange={() => toggleBullet(i, bi)}
                                    className="mt-0.5 h-3 w-3 accent-emerald-400"
                                  />
                                  <span className="leading-relaxed">{b}</span>
                                </label>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t border-white/10 px-5 py-3.5">
            <span className="text-[11px] text-zinc-500">
              {phase === 'ready' ? `${selectedCount} of ${projects.length} selected` : ''}
            </span>
            <div className="flex items-center gap-3">
              <button onClick={onClose} className="text-xs font-semibold text-zinc-400 transition hover:text-zinc-200">
                Cancel
              </button>
              <button
                onClick={handleInsert}
                disabled={phase !== 'ready' || selectedCount === 0}
                className="btn-accent px-4 py-2 text-xs font-semibold disabled:cursor-not-allowed disabled:opacity-50"
              >
                Insert into resume
              </button>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
