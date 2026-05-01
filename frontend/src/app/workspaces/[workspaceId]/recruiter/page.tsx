'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, FileText, StickyNote, Plus, Pencil, Trash2,
  Loader2, ChevronDown, ChevronRight, Check, X,
} from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type WorkspaceDetailResponse,
  type WorkspaceResumeItem,
  type RecruiterNoteResponse,
} from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'

interface ResumeWithNotes {
  resume: WorkspaceResumeItem
  notes: RecruiterNoteResponse[]
  expanded: boolean
  loading: boolean
}

export default function RecruiterDashboardPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const router = useRouter()
  const { data: session, isPending: sessionLoading } = useSession()

  const [ws, setWs] = useState<WorkspaceDetailResponse | null>(null)
  const [items, setItems] = useState<ResumeWithNotes[]>([])
  const [loading, setLoading] = useState(true)

  // Per-resume note drafts
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  // Per-note edit state: noteId → draft content
  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})

  const userId = session?.user?.id ?? ''

  useEffect(() => {
    if (!session?.user) return
    Promise.all([
      apiClient.getWorkspace(workspaceId),
      apiClient.listWorkspaceResumes(workspaceId),
    ])
      .then(([detail, resumes]) => {
        if (detail.owner_id !== session.user.id) {
          router.replace(`/workspaces/${workspaceId}`)
          return
        }
        setWs(detail)
        setItems(resumes.map((r) => ({ resume: r, notes: [], expanded: false, loading: false })))
      })
      .catch(() => toast.error('Failed to load workspace'))
      .finally(() => setLoading(false))
  }, [session, workspaceId, router])

  async function toggleExpand(resumeId: string) {
    setItems((prev) =>
      prev.map((item) => {
        if (item.resume.id !== resumeId) return item
        if (item.expanded) return { ...item, expanded: false }
        // Load notes on first expand
        if (item.notes.length === 0 && !item.loading) {
          loadNotes(resumeId)
        }
        return { ...item, expanded: true }
      })
    )
  }

  async function loadNotes(resumeId: string) {
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
  }

  async function handleAddNote(resumeId: string) {
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

  if (sessionLoading || loading) return <LoadingSpinner />
  if (!ws) return null

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6 max-w-4xl mx-auto">
      {/* Back nav */}
      <Link
        href={`/workspaces/${workspaceId}`}
        className="inline-flex items-center gap-1.5 text-sm text-zinc-400 hover:text-zinc-200 mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" /> {ws.name}
      </Link>

      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <div className="h-10 w-10 rounded-xl bg-violet-500/20 flex items-center justify-center">
          <StickyNote className="h-5 w-5 text-violet-400" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold">Recruiter Dashboard</h1>
          <p className="text-sm text-zinc-400">{ws.name} · {items.length} resumes</p>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="text-center py-20 text-zinc-500">
          <FileText className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="text-lg mb-1">No resumes shared yet</p>
          <p className="text-sm">Share resumes from the workspace overview to annotate them here.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map(({ resume, notes, expanded, loading: notesLoading }) => (
            <div
              key={resume.id}
              className="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden"
            >
              {/* Resume header row */}
              <button
                onClick={() => toggleExpand(resume.id)}
                className="w-full flex items-center justify-between px-5 py-4 hover:bg-zinc-800/50 transition-colors text-left"
              >
                <div className="flex items-center gap-3">
                  <FileText className="h-4 w-4 text-zinc-400 shrink-0" />
                  <span className="font-medium text-zinc-200">{resume.title}</span>
                  {notes.length > 0 && (
                    <span className="text-xs bg-violet-500/20 text-violet-300 px-2 py-0.5 rounded-full">
                      {notes.length} {notes.length === 1 ? 'note' : 'notes'}
                    </span>
                  )}
                </div>
                {expanded
                  ? <ChevronDown className="h-4 w-4 text-zinc-500" />
                  : <ChevronRight className="h-4 w-4 text-zinc-500" />
                }
              </button>

              {/* Expanded notes section */}
              {expanded && (
                <div className="border-t border-zinc-800 px-5 pb-5 pt-4">
                  {notesLoading ? (
                    <div className="flex justify-center py-4">
                      <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
                    </div>
                  ) : (
                    <>
                      {/* Existing notes */}
                      {notes.length === 0 ? (
                        <p className="text-sm text-zinc-500 mb-4">No notes yet. Add one below.</p>
                      ) : (
                        <ul className="space-y-3 mb-4">
                          {notes.map((note) => (
                            <li
                              key={note.id}
                              className="bg-zinc-800 rounded-lg p-3"
                            >
                              {editDrafts[note.id] !== undefined ? (
                                <div className="space-y-2">
                                  <textarea
                                    value={editDrafts[note.id]}
                                    onChange={(e) =>
                                      setEditDrafts((p) => ({ ...p, [note.id]: e.target.value }))
                                    }
                                    rows={3}
                                    className="w-full bg-zinc-700 border border-zinc-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500 resize-none"
                                  />
                                  <div className="flex gap-2">
                                    <button
                                      onClick={() => handleUpdateNote(resume.id, note.id)}
                                      disabled={saving[`edit-${note.id}`]}
                                      className="flex items-center gap-1 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
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
                                      className="flex items-center gap-1 px-3 py-1.5 text-zinc-400 hover:text-zinc-200 text-xs transition-colors"
                                    >
                                      <X className="h-3 w-3" /> Cancel
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex items-start justify-between gap-2">
                                  <div className="flex-1 min-w-0">
                                    <p className="text-sm text-zinc-200 whitespace-pre-wrap">{note.content}</p>
                                    <p className="text-xs text-zinc-500 mt-1">
                                      {note.author_name ?? note.author_email ?? 'You'} ·{' '}
                                      {new Date(note.created_at).toLocaleDateString()}
                                    </p>
                                  </div>
                                  {note.author_id === userId && (
                                    <div className="flex items-center gap-1 shrink-0">
                                      <button
                                        onClick={() =>
                                          setEditDrafts((p) => ({ ...p, [note.id]: note.content }))
                                        }
                                        className="p-1 text-zinc-500 hover:text-violet-400 transition-colors"
                                        title="Edit note"
                                      >
                                        <Pencil className="h-3.5 w-3.5" />
                                      </button>
                                      <button
                                        onClick={() => handleDeleteNote(resume.id, note.id)}
                                        className="p-1 text-zinc-500 hover:text-rose-400 transition-colors"
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
                      <div className="space-y-2">
                        <textarea
                          value={drafts[resume.id] ?? ''}
                          onChange={(e) =>
                            setDrafts((p) => ({ ...p, [resume.id]: e.target.value }))
                          }
                          placeholder="Add a recruiter note…"
                          rows={3}
                          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500 resize-none placeholder-zinc-600"
                        />
                        <button
                          onClick={() => handleAddNote(resume.id)}
                          disabled={saving[`add-${resume.id}`] || !(drafts[resume.id] ?? '').trim()}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
                        >
                          {saving[`add-${resume.id}`]
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : <Plus className="h-3.5 w-3.5" />
                          }
                          Add Note
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
