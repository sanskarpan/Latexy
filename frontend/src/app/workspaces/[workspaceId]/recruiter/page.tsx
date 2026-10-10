'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, FileText, StickyNote, Plus, Pencil, Trash2,
  Loader2, ChevronDown, ChevronRight, Check, X, Download,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type WorkspaceDetailResponse,
  type WorkspaceResumeItem,
  type RecruiterNoteResponse,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import CapabilityGate from '@/components/CapabilityGate'
import CommentsPanel from '@/components/CommentsPanel'
import { downloadBlob } from '@/lib/download'

interface ResumeWithNotes {
  resume: WorkspaceResumeItem
  notes: RecruiterNoteResponse[]
  expanded: boolean
  loading: boolean
}

export default function RecruiterDashboardPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const router = useRouter()
  const searchParams = useSearchParams()
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()

  const { can } = useEntitlements()
  const recruiterEnabled = can('f09')
  const recruiterEnabledRef = useRef(recruiterEnabled)
  recruiterEnabledRef.current = recruiterEnabled

  const [ws, setWs] = useState<WorkspaceDetailResponse | null>(null)
  const [items, setItems] = useState<ResumeWithNotes[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadNonce, setReloadNonce] = useState(0)

  // Per-resume note drafts
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // Per-note edit state: noteId → draft content
  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  const userId = session?.user?.id ?? ''
  const requestedResumeId = searchParams.get('resume_id')
  const requestedCommentId = searchParams.get('comment_id') ?? undefined
  const memberRole = ws?.members.find((member) => member.user_id === userId)?.role
  const canReview = memberRole === 'owner' || memberRole === 'editor'
  const canWrite = canReview && recruiterEnabled

  const loadNotes = useCallback(async (resumeId: string) => {
    setItems((prev) =>
      prev.map((item) => item.resume.id === resumeId ? { ...item, loading: true } : item)
    )
    try {
      const notes = await apiClient.listRecruiterNotes(workspaceId, resumeId)
      setItems((prev) =>
        prev.map((item) => item.resume.id === resumeId ? { ...item, notes, loading: false } : item)
      )
    } catch {
      toast.error('Failed to load notes')
      setItems((prev) =>
        prev.map((item) => item.resume.id === resumeId ? { ...item, loading: false } : item)
      )
    }
  }, [workspaceId])

  useEffect(() => {
    if (!session?.user) {
      setLoading(false)
      return
    }
    setLoading(true)
    setLoadError(null)
    Promise.all([
      apiClient.getWorkspace(workspaceId),
      apiClient.listWorkspaceResumes(workspaceId),
    ])
      .then(([detail, resumes]) => {
        const reviewer = detail.members.find((member) => member.user_id === session.user.id)
        if (!reviewer) {
          router.replace(`/workspaces/${workspaceId}`)
          return
        }
        const reviewerCanWrite = reviewer.role === 'owner' || reviewer.role === 'editor'
        setWs(detail)
        setItems(resumes.map((r) => ({
          resume: r,
          notes: [],
          expanded: r.id === requestedResumeId,
          loading: false,
        })))
        if (reviewerCanWrite && requestedResumeId && resumes.some((resume) => resume.id === requestedResumeId)) {
          void loadNotes(requestedResumeId)
        }
      })
      .catch((error) => {
        setLoadError(error instanceof Error ? error.message : 'Failed to load workspace')
        toast.error('Failed to load workspace')
      })
      .finally(() => setLoading(false))
  }, [session, workspaceId, router, reloadNonce, requestedResumeId, loadNotes])

  async function toggleExpand(resumeId: string) {
    setItems((prev) =>
      prev.map((item) => {
        if (item.resume.id !== resumeId) return item
        if (item.expanded) return { ...item, expanded: false }
        // Load notes on first expand
        if (canReview && item.notes.length === 0 && !item.loading) {
          loadNotes(resumeId)
        }
        return { ...item, expanded: true }
      })
    )
  }

  async function handleAddNote(resumeId: string) {
    if (!recruiterEnabledRef.current || !canReview) return
    const content = (drafts[resumeId] ?? '').trim()
    if (!content) return
    setSaving((p) => ({ ...p, [`add-${resumeId}`]: true }))
    try {
      const note = await apiClient.createRecruiterNote(workspaceId, resumeId, content)
      setItems((prev) =>
        prev.map((item) =>
          item.resume.id === resumeId ? { ...item, notes: [...item.notes, note] } : item
        )
      )
      setDrafts((p) => ({ ...p, [resumeId]: '' }))
      toast.success('Note added')
    } catch {
      toast.error('Failed to add note')
    } finally {
      setSaving((p) => ({ ...p, [`add-${resumeId}`]: false }))
    }
  }

  async function handleUpdateNote(resumeId: string, noteId: string) {
    if (!recruiterEnabledRef.current || !canReview) return
    const content = (editDrafts[noteId] ?? '').trim()
    if (!content) return
    setSaving((p) => ({ ...p, [`edit-${noteId}`]: true }))
    try {
      const updated = await apiClient.updateRecruiterNote(workspaceId, resumeId, noteId, content)
      setItems((prev) =>
        prev.map((item) =>
          item.resume.id === resumeId
            ? { ...item, notes: item.notes.map((n) => (n.id === noteId ? updated : n)) }
            : item
        )
      )
      setEditDrafts((p) => { const next = { ...p }; delete next[noteId]; return next })
      toast.success('Note updated')
    } catch {
      toast.error('Failed to update note')
    } finally {
      setSaving((p) => ({ ...p, [`edit-${noteId}`]: false }))
    }
  }

  async function handleDeleteNote(resumeId: string, noteId: string) {
    if (!confirm('Delete this note?')) return
    try {
      await apiClient.deleteRecruiterNote(workspaceId, resumeId, noteId)
      setItems((prev) =>
        prev.map((item) =>
          item.resume.id === resumeId
            ? { ...item, notes: item.notes.filter((n) => n.id !== noteId) }
            : item
        )
      )
      toast.success('Note deleted')
    } catch {
      toast.error('Failed to delete note')
    }
  }

  async function handleDownload(resume: WorkspaceResumeItem) {
    try {
      const blob = await apiClient.downloadWorkspaceResume(workspaceId, resume.id)
      downloadBlob(blob, `${resume.title.replace(/[^a-z0-9_-]+/gi, '_') || 'resume'}.pdf`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Resume download failed')
    }
  }

  if (sessionLoading || loading) return <LoadingSpinner />
  if (sessionError && !session) return <SessionLoadError area="Recruiter dashboard" />
  if (!session?.user) return null
  if (loadError || !ws) {
    return (
      <div className="min-h-screen bg-bg text-fg p-6">
        <div role="alert" className="mx-auto max-w-xl rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.07] p-6 text-center">
          <p className="text-sm font-semibold text-err">Recruiter dashboard could not be loaded</p>
          <p className="mt-1 text-xs text-fg-2">{loadError ?? 'The workspace response was empty.'}</p>
          <div className="mt-4 flex justify-center gap-3">
            <Link
              href={`/workspaces/${workspaceId}`}
              className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2"
            >
              Back to workspace
            </Link>
            <button
              type="button"
              onClick={() => setReloadNonce((value) => value + 1)}
              className="rounded-[var(--radius-md)] border border-err/30 px-4 py-2 text-xs font-semibold text-err transition hover:bg-err/10"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-bg text-fg p-6 max-w-4xl mx-auto">
      {/* Back nav */}
      <Link
        href={`/workspaces/${workspaceId}`}
        className="inline-flex items-center gap-1.5 text-sm text-fg-2 hover:text-fg mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" /> {ws.name}
      </Link>

      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <div className="h-10 w-10 rounded-[var(--radius-lg)] bg-accent-soft flex items-center justify-center">
          <StickyNote className="h-5 w-5 text-accent-strong" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold">Recruiter Dashboard</h1>
          <p className="text-sm text-fg-2">{ws.name} · {items.length} resumes</p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="text-center py-20 text-fg-3">
          <FileText className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="text-lg mb-1">No resumes shared yet</p>
          <p className="text-sm">Share resumes from the workspace overview to annotate them here.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map(({ resume, notes, expanded, loading: notesLoading }) => (
            <div
              key={resume.id}
              className="bg-surface border border-line rounded-[var(--radius-lg)] overflow-hidden"
            >
              {/* Resume header row */}
              <div className="flex items-stretch hover:bg-surface-2 transition-colors">
                <button
                  onClick={() => toggleExpand(resume.id)}
                  className="flex min-w-0 flex-1 items-center justify-between px-5 py-4 text-left"
                >
                  <span className="flex min-w-0 items-center gap-3">
                  <FileText className="h-4 w-4 text-fg-2 shrink-0" />
                  <span className="font-medium text-fg">{resume.title}</span>
                  {notes.length > 0 && (
                    <span className="text-xs bg-accent-soft text-accent-strong border border-accent px-2 py-0.5 rounded-full">
                      {notes.length} {notes.length === 1 ? 'note' : 'notes'}
                    </span>
                  )}
                  <span className="text-[10px] text-fg-3">
                    submitted {new Date(resume.shared_at).toLocaleDateString()}
                    {resume.opened_at && resume.opened_actor === 'candidate' && resume.opened_source === 'candidate_self'
                      ? ' · candidate viewed their submission'
                      : ''}
                    {resume.downloaded_at && resume.downloaded_actor === 'candidate' && resume.downloaded_source === 'candidate_self'
                      ? ' · candidate downloaded their PDF'
                      : ''}
                  </span>
                  </span>
                  {expanded
                    ? <ChevronDown className="h-4 w-4 text-fg-3" />
                    : <ChevronRight className="h-4 w-4 text-fg-3" />
                  }
                </button>
                <button
                  type="button"
                  onClick={() => void handleDownload(resume)}
                  className="px-5 text-fg-3 hover:text-accent-strong"
                  aria-label={`Download ${resume.title}`}
                ><Download className="h-4 w-4" /></button>
              </div>

              {/* Expanded notes section */}
              {canReview && expanded && (
                <div className="border-t border-line px-5 pb-5 pt-4">
                  {notesLoading ? (
                    <div className="flex justify-center py-4">
                      <Loader2 className="h-5 w-5 animate-spin text-fg-3" />
                    </div>
                  ) : (
                    <>
                      {/* Existing notes */}
                      {notes.length === 0 ? (
                        <p className="text-sm text-fg-3 mb-4">No notes yet.</p>
                      ) : (
                        <ul className="space-y-3 mb-4">
                          {notes.map((note) => (
                            <li
                              key={note.id}
                              className="bg-surface-2 rounded-[var(--radius-md)] p-3"
                            >
                              {canWrite && editDrafts[note.id] !== undefined ? (
                                <div className="space-y-2">
                                  <textarea
                                    value={editDrafts[note.id]}
                                    onChange={(e) =>
                                      setEditDrafts((p) => ({ ...p, [note.id]: e.target.value }))
                                    }
                                    rows={3}
                                    className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:border-accent resize-none"
                                  />
                                  <div className="flex gap-2">
                                    <button
                                      onClick={() => handleUpdateNote(resume.id, note.id)}
                                      disabled={saving[`edit-${note.id}`]}
                                      className="flex items-center gap-1 px-3 py-1.5 bg-accent hover:brightness-110 text-accent-fg disabled:opacity-50 rounded-[var(--radius-md)] text-xs font-medium transition-colors"
                                    >
                                      {saving[`edit-${note.id}`]
                                        ? <Loader2 className="h-3 w-3 animate-spin" />
                                        : <Check className="h-3 w-3" />
                                      }
                                      Save
                                    </button>
                                    <button
                                      onClick={() =>
                                        setEditDrafts((p) => { const next = { ...p }; delete next[note.id]; return next })
                                      }
                                      className="flex items-center gap-1 px-3 py-1.5 text-fg-2 hover:text-fg text-xs transition-colors"
                                    >
                                      <X className="h-3 w-3" /> Cancel
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-start justify-between gap-2">
                                  <div className="flex-1 min-w-0">
                                    <p className="text-sm text-fg whitespace-pre-wrap">{note.content}</p>
                                    <p className="text-xs text-fg-3 mt-1">
                                      {note.author_name ?? note.author_email ?? 'You'} ·{' '}
                                      {new Date(note.created_at).toLocaleDateString()}
                                    </p>
                                  </div>
                                  {canReview && (note.author_id === userId || memberRole === 'owner') && (
                                    <div className="flex items-center gap-1 shrink-0">
                                      {canWrite && note.author_id === userId && <button
                                        onClick={() =>
                                          setEditDrafts((p) => ({ ...p, [note.id]: note.content }))
                                        }
                                        className="p-1 text-fg-3 hover:text-accent-strong transition-colors"
                                        title="Edit note"
                                      >
                                        <Pencil className="h-3.5 w-3.5" />
                                      </button>}
                                      <button
                                        onClick={() => handleDeleteNote(resume.id, note.id)}
                                        className="p-1 text-fg-3 hover:text-err transition-colors"
                                        title="Delete note"
                                      >
                                        <Trash2 className="h-3.5 w-3.5" />
                                      </button>
                                    </div>
                                  )}
                                </div>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}

                      {/* Add note form */}
                      {canWrite && <div className="space-y-2">
                        <textarea
                          value={drafts[resume.id] ?? ''}
                          onChange={(e) =>
                            setDrafts((p) => ({ ...p, [resume.id]: e.target.value }))
                          }
                          placeholder="Add a recruiter note…"
                          rows={3}
                          className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-sm focus:outline-none focus:border-accent resize-none placeholder-fg-3"
                        />
                        <button
                          onClick={() => handleAddNote(resume.id)}
                          disabled={saving[`add-${resume.id}`] || !(drafts[resume.id] ?? '').trim()}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent hover:brightness-110 text-accent-fg disabled:opacity-50 rounded-[var(--radius-md)] text-xs font-medium transition-colors"
                        >
                          {saving[`add-${resume.id}`]
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <Plus className="h-3.5 w-3.5" />
                          }
                          Add Note
                        </button>
                      </div>}
                    </>
                  )}
                </div>
              )}
              {expanded && (
                <CapabilityGate feature="f06">
                <div className="border-t border-line px-5 pb-5 pt-4">
                  <h2 className="mb-2 text-sm font-semibold text-fg">Resume comments</h2>
                  <CommentsPanel
                    resumeId={resume.id}
                    workspaceId={workspaceId}
                    highlightCommentId={requestedResumeId === resume.id ? requestedCommentId : undefined}
                    canComment={canReview}
                  />
                </div>
                </CapabilityGate>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
