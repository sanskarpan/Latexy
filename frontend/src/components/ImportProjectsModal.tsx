'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { ExternalLink, FileUp, Globe, Loader2, Star, X } from 'lucide-react'
import { toast } from 'sonner'
import { Github } from '@/components/icons/brand-icons'
import { apiClient, type ProjectEvidence } from '@/lib/api-client'
import { projectsToLatex, type ProjectSelection } from '@/lib/github-projects-latex'

/**
 * Unified external-source import (External-Sources-to-Resume, F1). One modal, three
 * sources — GitHub (top public repos, ranked + AI-summarized), a portfolio/site
 * URL, or a user-uploaded LinkedIn data-export / resume file — all producing the
 * same `ProjectEvidence` records, reviewed and selected in one shared list, then
 * inserted into the resume as LaTeX. Nothing is written without the user choosing it.
 *
 * LinkedIn is compliant-only: the file is uploaded by the user and parsed
 * server-side; Latexy never scrapes LinkedIn.
 */

const POLL_INTERVAL_MS = 2500
const POLL_TIMEOUT_MS = 120_000

type Source = 'github' | 'url' | 'linkedin'
type Phase = 'input' | 'checking' | 'disconnected' | 'importing' | 'ready' | 'error'
type Selection = { included: boolean; bullets: Set<number> }

const SOURCES: { key: Source; label: string; icon: React.ReactNode }[] = [
  { key: 'github', label: 'GitHub', icon: <Github size={13} /> },
  { key: 'url', label: 'Website', icon: <Globe size={13} /> },
  { key: 'linkedin', label: 'LinkedIn', icon: <FileUp size={13} /> },
]

export default function ImportProjectsModal({
  isOpen,
  onClose,
  onInsert,
}: {
  isOpen: boolean
  onClose: () => void
  onInsert: (latex: string) => void
}) {
  const [source, setSource] = useState<Source>('github')
  const [phase, setPhase] = useState<Phase>('input')
  const [projects, setProjects] = useState<ProjectEvidence[]>([])
  const [selection, setSelection] = useState<Record<number, Selection>>({})
  const [error, setError] = useState<string | null>(null)
  const [urlInput, setUrlInput] = useState('')
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelledRef = useRef(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const clearTimer = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current)
      pollTimer.current = null
    }
  }

  // Every project starts included with all its suggested bullets checked.
  const loadProjects = useCallback((list: ProjectEvidence[]) => {
    const init: Record<number, Selection> = {}
    list.forEach((p, i) => {
      init[i] = { included: true, bullets: new Set(p.suggested_bullets.map((_, bi) => bi)) }
    })
    setProjects(list)
    setSelection(init)
    setPhase('ready')
  }, [])

  const reset = useCallback(() => {
    clearTimer()
    setPhase('input')
    setProjects([])
    setSelection({})
    setError(null)
  }, [])

  // ── GitHub: connection check → async import job → poll ──────────────────────
  const startGithubImport = useCallback(async () => {
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
          if (res.status === 'completed') return loadProjects(res.projects)
          if (res.status === 'failed') {
            setError(res.error || 'Import failed')
            return setPhase('error')
          }
          if (Date.now() > deadline) {
            setError('Import timed out. Please try again.')
            return setPhase('error')
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
      if (/not connected/i.test(msg)) setPhase('disconnected')
      else {
        setError(msg)
        setPhase('error')
      }
    }
  }, [loadProjects])

  const beginGithub = useCallback(async () => {
    setPhase('checking')
    try {
      const status = await apiClient.getGitHubStatus()
      if (cancelledRef.current) return
      if (status.connected) startGithubImport()
      else setPhase('disconnected')
    } catch {
      if (!cancelledRef.current) startGithubImport() // status best-effort
    }
  }, [startGithubImport])

  const retry = useCallback(() => {
    clearTimer()
    setProjects([])
    setSelection({})
    setError(null)
    if (source === 'github') {
      void beginGithub()
    } else {
      setPhase('input')
    }
  }, [beginGithub, source])

  // ── URL: synchronous fetch + summarize ──────────────────────────────────────
  const runUrlImport = useCallback(async () => {
    const url = urlInput.trim()
    if (!url) return
    setPhase('importing')
    setError(null)
    try {
      const res = await apiClient.importFromUrl(url)
      if (cancelledRef.current) return
      if (res.projects.length === 0) {
        setError('No projects found on that page.')
        return setPhase('error')
      }
      loadProjects(res.projects)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to import from URL')
      setPhase('error')
    }
  }, [urlInput, loadProjects])

  // ── LinkedIn / resume file: synchronous upload + parse ──────────────────────
  const runLinkedInImport = useCallback(
    async (file: File) => {
      setPhase('importing')
      setError(null)
      try {
        const res = await apiClient.importLinkedIn(file)
        if (cancelledRef.current) return
        if (res.projects.length === 0) {
          setError('No projects or experience found in that file.')
          return setPhase('error')
        }
        loadProjects(res.projects)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to parse the file')
        setPhase('error')
      }
    },
    [loadProjects]
  )

  // Reset on open + when the source changes; auto-start GitHub (its input is implicit).
  useEffect(() => {
    if (!isOpen) return
    cancelledRef.current = false
    reset()
    if (source === 'github') beginGithub()
    return () => {
      cancelledRef.current = true
      clearTimer()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, source])

  const switchSource = (s: Source) => {
    cancelledRef.current = true
    clearTimer()
    cancelledRef.current = false
    setSource(s)
  }

  const toggleProject = (i: number) =>
    setSelection((prev) => ({ ...prev, [i]: { ...prev[i], included: !prev[i].included } }))

  const toggleBullet = (i: number, bi: number) =>
    setSelection((prev) => {
      const bullets = new Set(prev[i].bullets)
      if (bullets.has(bi)) bullets.delete(bi)
      else bullets.add(bi)
      return { ...prev, [i]: { ...prev[i], bullets } }
    })

  const updateProject = (i: number, patch: Partial<ProjectEvidence>) =>
    setProjects((prev) => prev.map((project, index) => (
      index === i ? { ...project, ...patch } : project
    )))

  const updateBullet = (i: number, bi: number, value: string) =>
    setProjects((prev) => prev.map((project, index) => {
      if (index !== i) return project
      const suggested_bullets = [...project.suggested_bullets]
      suggested_bullets[bi] = value
      return { ...project, suggested_bullets }
    }))

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
        className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-sm"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.97, y: 8 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97 }}
          className="flex max-h-[88vh] w-full max-w-2xl flex-col overflow-hidden rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="flex items-center justify-between border-b border-line px-5 py-4">
            <div>
              <h2 className="text-sm font-semibold text-fg">Import projects</h2>
              <p className="mt-0.5 text-[11px] text-fg-3">
                Pull projects from a source, review them, and insert the ones you pick.
              </p>
            </div>
            <button onClick={onClose} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg">
              <X size={16} />
            </button>
          </div>

          {/* Source tabs */}
          <div className="flex gap-1 border-b border-line px-4 py-2">
            {SOURCES.map((s) => (
              <button
                key={s.key}
                onClick={() => switchSource(s.key)}
                className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-medium transition ${
                  source === s.key ? 'bg-surface-2 text-fg' : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                {s.icon}
                {s.label}
              </button>
            ))}
          </div>

          <div className="scrollbar-subtle min-h-0 flex-1 overflow-y-auto px-5 py-4">
            {/* Per-source input (only before results are ready) */}
            {phase === 'input' && source === 'url' && (
              <div className="py-6">
                <label className="text-[11px] font-semibold uppercase tracking-[0.14em] text-fg-2">Portfolio / project URL</label>
                <div className="mt-2 flex gap-2">
                  <input
                    type="url"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') runUrlImport() }}
                    placeholder="https://yoursite.com/projects"
                    className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
                  />
                  <button onClick={runUrlImport} disabled={!urlInput.trim()} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:opacity-40">
                    Import
                  </button>
                </div>
                <p className="mt-2 text-[10px] text-fg-3">Public pages only. We fetch the page once (no scripts) and summarize it.</p>
              </div>
            )}

            {phase === 'input' && source === 'linkedin' && (
              <div className="py-6 text-center">
                <input
                  ref={fileRef}
                  type="file"
                  accept=".zip,.pdf,.docx"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) runLinkedInImport(f)
                  }}
                />
                <button
                  onClick={() => fileRef.current?.click()}
                  className="mx-auto flex flex-col items-center gap-2 rounded-[var(--radius-lg)] border border-dashed border-line-2 bg-surface px-8 py-8 text-fg-2 transition hover:border-accent hover:text-fg"
                >
                  <FileUp size={22} />
                  <span className="text-sm font-medium">Upload LinkedIn export or resume</span>
                  <span className="text-[10px] text-fg-3">.zip (LinkedIn “Get a copy of your data”) · .pdf · .docx</span>
                </button>
                <p className="mx-auto mt-3 max-w-sm text-[10px] leading-relaxed text-fg-3">
                  Compliant by design — we never scrape LinkedIn. Your file is parsed in the request and not stored.
                </p>
              </div>
            )}

            {/* Shared status states */}
            {phase === 'checking' && (
              <div className="flex items-center justify-center gap-2 py-16 text-sm text-fg-3">
                <Loader2 size={16} className="animate-spin" /> Checking GitHub connection…
              </div>
            )}
            {phase === 'importing' && (
              <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
                <Loader2 size={20} className="animate-spin text-accent-strong" />
                <p className="text-sm text-fg-2">Fetching and summarizing…</p>
                <p className="text-[11px] text-fg-3">This can take up to a minute.</p>
              </div>
            )}
            {phase === 'disconnected' && (
              <div className="py-12 text-center">
                <p className="text-sm text-fg-2">GitHub isn&apos;t connected yet.</p>
                <p className="mx-auto mt-1 max-w-sm text-[11px] text-fg-3">
                  Connect your account in Settings → GitHub Integration, then reopen this import.
                </p>
                <a href="/settings" className="mt-4 inline-block rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-semibold text-fg transition hover:bg-surface-2">
                  Go to Settings
                </a>
              </div>
            )}
            {phase === 'error' && (
              <div className="py-12 text-center">
                <div className="mx-auto max-w-md rounded-[var(--radius-md)] border border-err/20 bg-err/10 px-4 py-3 text-sm text-err">
                  {error || 'Something went wrong.'}
                </div>
                <button onClick={retry} className="mt-4 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-xs font-semibold text-fg transition hover:bg-surface-2">
                  Try again
                </button>
              </div>
            )}

            {/* Shared review list */}
            {phase === 'ready' && (
              <ul className="space-y-3">
                {projects.map((p, i) => {
                  const sel = selection[i]
                  if (!sel) return null
                  return (
                    <li
                      key={`${p.title}-${i}`}
                      className={`rounded-[var(--radius-lg)] border p-3 transition ${
                        sel.included ? 'border-line bg-surface' : 'border-line opacity-55'
                      }`}
                    >
                      <div className="flex items-start gap-2.5">
                        <input type="checkbox" checked={sel.included} onChange={() => toggleProject(i)} className="mt-1 h-3.5 w-3.5 accent-accent" />
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <input
                              aria-label={`Project title ${i + 1}`}
                              value={p.title}
                              onChange={(event) => updateProject(i, { title: event.target.value })}
                              className="min-w-0 flex-1 rounded border border-transparent bg-transparent px-1 py-0.5 text-sm font-semibold text-fg outline-none transition hover:border-line focus:border-accent focus:bg-bg"
                            />
                            {p.metrics?.stars > 0 && (
                              <span className="flex items-center gap-0.5 text-[10px] text-fg-3"><Star size={10} /> {p.metrics.stars}</span>
                            )}
                            {p.url && (
                              <a href={p.url} target="_blank" rel="noopener noreferrer" className="text-fg-3 hover:text-fg-2"><ExternalLink size={11} /></a>
                            )}
                          </div>
                          <textarea
                            aria-label={`Project description ${i + 1}`}
                            value={p.description}
                            onChange={(event) => updateProject(i, { description: event.target.value })}
                            rows={2}
                            placeholder="Add a concise project description"
                            className="mt-1 w-full resize-y rounded border border-transparent bg-transparent px-1 py-0.5 text-[11px] leading-relaxed text-fg-2 outline-none transition placeholder:text-fg-3 hover:border-line focus:border-accent focus:bg-bg"
                          />
                          {p.tech?.length > 0 && (
                            <div className="mt-1 flex flex-wrap gap-1">
                              {p.tech.slice(0, 8).map((t) => (
                                <span key={t} className="rounded bg-surface-2 px-1.5 py-0.5 text-[9px] text-fg-2">{t}</span>
                              ))}
                            </div>
                          )}
                          {sel.included && p.suggested_bullets.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {p.suggested_bullets.map((b, bi) => (
                                <div key={bi} className="flex items-start gap-2 text-[11px] text-fg-2">
                                  <input
                                    aria-label={`Include project bullet ${i + 1}.${bi + 1}`}
                                    type="checkbox"
                                    checked={sel.bullets.has(bi)}
                                    onChange={() => toggleBullet(i, bi)}
                                    className="mt-1 h-3 w-3 accent-accent"
                                  />
                                  <textarea
                                    aria-label={`Project bullet ${i + 1}.${bi + 1}`}
                                    value={b}
                                    onChange={(event) => updateBullet(i, bi, event.target.value)}
                                    disabled={!sel.bullets.has(bi)}
                                    rows={2}
                                    className="min-w-0 flex-1 resize-y rounded border border-transparent bg-transparent px-1 py-0.5 leading-relaxed outline-none transition hover:border-line focus:border-accent focus:bg-bg disabled:opacity-50"
                                  />
                                </div>
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

          <div className="flex items-center justify-between gap-3 border-t border-line px-5 py-3.5">
            <span className="text-[11px] text-fg-3">
              {phase === 'ready' ? `${selectedCount} of ${projects.length} selected` : ''}
            </span>
            <div className="flex items-center gap-3">
              <button onClick={onClose} className="text-xs font-semibold text-fg-2 transition hover:text-fg">Cancel</button>
              <button
                onClick={handleInsert}
                disabled={phase !== 'ready' || selectedCount === 0}
                className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
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
