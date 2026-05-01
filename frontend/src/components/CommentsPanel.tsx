'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Loader2, MessageSquare, Pencil, Send, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type CommentResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'

interface CommentsPanelProps {
  resumeId: string
  workspaceId?: string
  /** If set, the panel will auto-scroll to this comment on open */
  highlightCommentId?: string
  onClose?: () => void
}

export default function CommentsPanel({
  resumeId,
  workspaceId,
  highlightCommentId,
  onClose,
}: CommentsPanelProps) {
  const { data: session } = useSession()
  const userId = session?.user?.id ?? ''

  const [comments, setComments] = useState<CommentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // Per-comment edit state: commentId → draft content
  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({})
  const [editSaving, setEditSaving] = useState<Record<string, boolean>>({})

  const highlightRef = useRef<HTMLLIElement | null>(null)

  useEffect(() => {
    apiClient
      .listComments(resumeId, workspaceId)
      .then(setComments)
      .catch(() => toast.error('Failed to load comments'))
      .finally(() => setLoading(false))
  }, [resumeId, workspaceId])

  // Scroll to highlighted comment after comments load
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [comments, highlightCommentId])

  async function handleSubmit() {
    const content = draft.trim()
    if (!content) return
    setSubmitting(true)
    try {
      const comment = await apiClient.addComment(resumeId, content, { workspaceId })
      setComments((prev) => [...prev, comment])
      setDraft('')
    } catch {
      toast.error('Failed to add comment')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleUpdate(commentId: string) {
    const content = (editDrafts[commentId] ?? '').trim()
    if (!content) return
    setEditSaving((p) => ({ ...p, [commentId]: true }))
    try {
      const updated = await apiClient.updateComment(resumeId, commentId, content)
      setComments((prev) => prev.map((c) => (c.id === commentId ? updated : c)))
      setEditDrafts((p) => { const next = { ...p }; delete next[commentId]; return next })
    } catch {
      toast.error('Failed to update comment')
    } finally {
      setEditSaving((p) => ({ ...p, [commentId]: false }))
    }
  }

  async function handleDelete(commentId: string) {
    if (!confirm('Delete this comment?')) return
    try {
      await apiClient.deleteComment(resumeId, commentId)
      setComments((prev) => prev.filter((c) => c.id !== commentId))
    } catch {
      toast.error('Failed to delete comment')
    }
  }

  async function handleResolve(commentId: string) {
    try {
      const updated = await apiClient.resolveComment(resumeId, commentId)
      setComments((prev) => prev.map((c) => (c.id === commentId ? updated : c)))
    } catch {
      toast.error('Failed to update comment')
    }
  }

  return (
    <div className="flex flex-col h-full bg-zinc-900 border-l border-zinc-800 w-72">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-zinc-200">
          <MessageSquare className="h-4 w-4 text-violet-400" />
          Comments
          {comments.length > 0 && (
            <span className="text-xs bg-zinc-700 text-zinc-400 rounded-full px-2 py-0.5">
              {comments.length}
            </span>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Comment list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />
          </div>
        ) : comments.length === 0 ? (
          <p className="text-center text-xs text-zinc-500 py-8">No comments yet.</p>
        ) : (
          <ul className="space-y-2">
            {comments.map((comment) => {
              const isHighlighted = comment.id === highlightCommentId
              const isAuthor = comment.author_id === userId

              return (
                <li
                  key={comment.id}
                  ref={isHighlighted ? highlightRef : null}
                  className={`rounded-lg p-3 transition-colors ${
                    comment.resolved
                      ? 'bg-zinc-800/50 opacity-60'
                      : isHighlighted
                      ? 'bg-violet-500/10 border border-violet-500/30'
                      : 'bg-zinc-800'
                  }`}
                >
                  {/* Line / section badge */}
                  {(comment.line_number != null || comment.section_tag) && (
                    <div className="flex gap-1.5 mb-1.5">
                      {comment.line_number != null && (
                        <span className="text-xs bg-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded font-mono">
                          L{comment.line_number}
                        </span>
                      )}
                      {comment.section_tag && (
                        <span className="text-xs bg-zinc-700 text-zinc-400 px-1.5 py-0.5 rounded">
                          {comment.section_tag}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Content or edit form */}
                  {editDrafts[comment.id] !== undefined ? (
                    <div className="space-y-1.5">
                      <textarea
                        value={editDrafts[comment.id]}
                        onChange={(e) =>
                          setEditDrafts((p) => ({ ...p, [comment.id]: e.target.value }))
                        }
                        rows={3}
                        className="w-full bg-zinc-700 border border-zinc-600 rounded px-2 py-1.5 text-xs focus:outline-none focus:border-violet-500 resize-none"
                      />
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => handleUpdate(comment.id)}
                          disabled={editSaving[comment.id]}
                          className="flex items-center gap-1 px-2 py-1 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded text-xs transition-colors"
                        >
                          {editSaving[comment.id]
                            ? <Loader2 className="h-3 w-3 animate-spin" />
                            : <Check className="h-3 w-3" />}
                          Save
                        </button>
                        <button
                          onClick={() => setEditDrafts((p) => { const next = { ...p }; delete next[comment.id]; return next })}
                          className="px-2 py-1 text-zinc-400 hover:text-zinc-200 text-xs transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-zinc-200 whitespace-pre-wrap">{comment.content}</p>
                  )}

                  {/* Footer */}
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-zinc-500">
                      {comment.author_name ?? comment.author_email ?? 'User'} ·{' '}
                      {new Date(comment.created_at).toLocaleDateString()}
                    </span>
                    <div className="flex items-center gap-1">
                      {/* Resolve toggle */}
                      <button
                        onClick={() => handleResolve(comment.id)}
                        title={comment.resolved ? 'Unresolve' : 'Resolve'}
                        className={`p-0.5 transition-colors ${
                          comment.resolved
                            ? 'text-emerald-400 hover:text-zinc-400'
                            : 'text-zinc-600 hover:text-emerald-400'
                        }`}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>
                      {isAuthor && editDrafts[comment.id] === undefined && (
                        <>
                          <button
                            onClick={() => setEditDrafts((p) => ({ ...p, [comment.id]: comment.content }))}
                            className="p-0.5 text-zinc-600 hover:text-violet-400 transition-colors"
                            title="Edit"
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => handleDelete(comment.id)}
                            className="p-0.5 text-zinc-600 hover:text-rose-400 transition-colors"
                            title="Delete"
                          >
                            <Trash2 className="h-3 w-3" />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      {/* Add comment form */}
      <div className="shrink-0 border-t border-zinc-800 px-3 py-3">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
          }}
          placeholder="Add a comment… (⌘↵ to send)"
          rows={3}
          className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-violet-500 resize-none placeholder-zinc-600 mb-2"
        />
        <button
          onClick={handleSubmit}
          disabled={submitting || !draft.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg text-xs font-medium transition-colors"
        >
          {submitting
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Send className="h-3.5 w-3.5" />}
          Send
        </button>
      </div>
    </div>
  )
}
