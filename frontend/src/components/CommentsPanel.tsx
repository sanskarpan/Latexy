'use client'

import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Check, Loader2, MessageSquare, Pencil, Send, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type CommentMentionParticipant, type CommentResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { containsMentionToken } from '@/lib/comment-mentions'

interface CommentsPanelProps {
  resumeId: string
  workspaceId?: string
  /** If set, the panel will auto-scroll to this comment on open */
  highlightCommentId?: string
  onClose?: () => void
  canComment?: boolean
}

const MENTION_ESCAPE_RE = /[.*+?^${}()|[\]\\]/g

export default function CommentsPanel({
  resumeId,
  workspaceId,
  highlightCommentId,
  onClose,
  canComment = true,
}: CommentsPanelProps) {
  const { data: session } = useSession()
  const userId = session?.user?.id ?? ''

  const [comments, setComments] = useState<CommentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [participants, setParticipants] = useState<CommentMentionParticipant[]>([])
  const [participantsError, setParticipantsError] = useState<string | null>(null)
  const [mentionQuery, setMentionQuery] = useState<string | null>(null)
  const [selectedMentionIds, setSelectedMentionIds] = useState<string[]>([])
  const draftRef = useRef<HTMLTextAreaElement | null>(null)

  // Per-comment edit state: commentId → draft content
  const [editDrafts, setEditDrafts] = useState<Record<string, string>>({})
  const [editSaving, setEditSaving] = useState<Record<string, boolean>>({})

  const highlightRef = useRef<HTMLLIElement | null>(null)

  const loadComments = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      setComments(await apiClient.listComments(resumeId, workspaceId))
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : 'Failed to load comments')
    } finally {
      setLoading(false)
    }
  }, [resumeId, workspaceId])

  const loadParticipants = useCallback(async () => {
    setParticipantsError(null)
    try {
      setParticipants(await apiClient.listCommentParticipants(resumeId, workspaceId))
    } catch (error) {
      setParticipantsError(error instanceof Error ? error.message : 'Mention picker is unavailable')
    }
  }, [resumeId, workspaceId])

  useEffect(() => {
    void loadComments()
    if (canComment) void loadParticipants()
  }, [canComment, loadComments, loadParticipants])

  function updateMentionQuery(value: string, cursor: number) {
    const token = value.slice(0, cursor).match(/(?:^|\s)@([^\s@]*)$/)
    setMentionQuery(token ? token[1] : null)
  }

  function renderCommentContent(comment: CommentResponse) {
    const mentions = (comment.mentions ?? []).filter((mention) => mention.display_name)
    if (!mentions.length) return comment.content
    const escaped = mentions
      .map((mention) => mention.display_name.replace(MENTION_ESCAPE_RE, '\\$&'))
      .sort((a, b) => b.length - a.length)
    const matcher = new RegExp(`(^|[^\\p{L}\\p{N}_])(@(?:${escaped.join('|')}))(?![\\p{L}\\p{N}_])`, 'gu')
    const rendered: ReactNode[] = []
    let lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = matcher.exec(comment.content)) !== null) {
      const start = match.index
      const prefix = match[1]
      const token = match[2]
      const mention = mentions.find((item) => `@${item.display_name}` === token)
      rendered.push(comment.content.slice(lastIndex, start), prefix)
      if (mention) {
        rendered.push(
          <span key={`${comment.id}-${start}`} className="rounded bg-accent-soft px-0.5 text-accent-strong" aria-label={`Mentioned ${mention.display_name}`}>
            {token}
          </span>,
        )
      } else {
        rendered.push(token)
      }
      lastIndex = start + match[0].length
    }
    rendered.push(comment.content.slice(lastIndex))
    return rendered
  }

  // Scroll to highlighted comment after comments load
  useEffect(() => {
    if (highlightRef.current) {
      highlightRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }
  }, [comments, highlightCommentId])

  async function handleSubmit() {
    const content = draft.trim()
    if (!content) return
    const mentionIds = selectedMentionIds.filter((id) => {
      const participant = participants.find((item) => item.user_id === id)
      return participant ? containsMentionToken(content, participant.display_name) : false
    })
    setSubmitting(true)
    setSubmitError(null)
    try {
      const comment = await apiClient.addComment(resumeId, content, { workspaceId, mentionedUserIds: mentionIds })
      setComments((prev) => [...prev, comment])
      setDraft('')
      setSelectedMentionIds([])
      setMentionQuery(null)
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : 'Failed to add comment. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleUpdate(commentId: string) {
    const content = (editDrafts[commentId] ?? '').trim()
    if (!content) return
    setEditSaving((p) => ({ ...p, [commentId]: true }))
    try {
      const original = comments.find((comment) => comment.id === commentId)
      const mentionedUserIds = (original?.mentions ?? [])
        .filter((mention) => containsMentionToken(content, mention.display_name))
        .map((mention) => mention.user_id)
      const updated = await apiClient.updateComment(resumeId, commentId, content, mentionedUserIds)
      setComments((prev) => prev.map((c) => (c.id === commentId ? updated : c)))
      setEditDrafts((p) => { const next = { ...p }; delete next[commentId]; return next })
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to update comment')
    } finally {
      setEditSaving((p) => ({ ...p, [commentId]: false }))
    }
  }

  function selectMention(participant: CommentMentionParticipant) {
    const textarea = draftRef.current
    const cursor = textarea?.selectionStart ?? draft.length
    const query = mentionQuery ?? ''
    const tokenStart = Math.max(0, cursor - query.length - 1)
    const replacement = `@${participant.display_name} `
    const next = `${draft.slice(0, tokenStart)}${replacement}${draft.slice(cursor)}`
    setDraft(next)
    setSelectedMentionIds((ids) => ids.includes(participant.user_id) ? ids : [...ids, participant.user_id])
    setMentionQuery(null)
    requestAnimationFrame(() => {
      textarea?.focus()
      const nextCursor = tokenStart + replacement.length
      textarea?.setSelectionRange(nextCursor, nextCursor)
    })
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
    <div className="flex h-full w-full flex-col bg-surface">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
        <div className="flex items-center gap-2 text-sm font-semibold text-fg">
          <MessageSquare className="h-4 w-4 text-accent-strong" />
          Comments
          {comments.length > 0 && (
            <span className="text-xs bg-surface-2 text-fg-2 rounded-full px-2 py-0.5">
              {comments.length}
            </span>
          )}
        </div>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close comments"
            className="text-fg-3 hover:text-fg-2 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Comment list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-fg-3" />
          </div>
        ) : loadError ? (
          <div role="alert" className="px-2 py-8 text-center">
            <p className="text-xs text-err">Comments could not be loaded.</p>
            <button
              type="button"
              onClick={() => void loadComments()}
              className="mt-3 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs text-fg-2 transition hover:bg-surface-2 hover:text-fg"
            >
              Retry
            </button>
          </div>
        ) : comments.length === 0 ? (
          <p className="text-center text-xs text-fg-3 py-8">No comments yet.</p>
        ) : (
          <ul className="space-y-2">
            {comments.map((comment) => {
              const isHighlighted = comment.id === highlightCommentId
              const isAuthor = comment.author_id === userId

              return (
                <li
                  key={comment.id}
                  ref={isHighlighted ? highlightRef : null}
                  className={`rounded-[var(--radius-md)] p-3 transition-colors ${
                    comment.resolved
                      ? 'bg-surface-2/50 opacity-60'
                      : isHighlighted
                      ? 'bg-accent-soft border border-accent'
                      : 'bg-surface-2'
                  }`}
                >
                  {/* Line / section badge */}
                  {(comment.line_number != null || comment.section_tag) && (
                    <div className="flex gap-1.5 mb-1.5">
                      {comment.line_number != null && (
                        <span className="text-xs bg-surface-2 text-fg-2 px-1.5 py-0.5 rounded-[var(--radius-md)] font-mono">
                          L{comment.line_number}
                        </span>
                      )}
                      {comment.section_tag && (
                        <span className="text-xs bg-surface-2 text-fg-2 px-1.5 py-0.5 rounded-[var(--radius-md)]">
                          {comment.section_tag}
                        </span>
                      )}
                    </div>
                  )}

                  {/* Content or edit form */}
                  {canComment && editDrafts[comment.id] !== undefined ? (
                    <div className="space-y-1.5">
                      <textarea
                        value={editDrafts[comment.id]}
                        onChange={(e) =>
                          setEditDrafts((p) => ({ ...p, [comment.id]: e.target.value }))
                        }
                        rows={3}
                        className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-2 py-1.5 text-xs focus:outline-none focus:border-accent resize-none"
                      />
                      <div className="flex gap-1.5">
                        <button
                          onClick={() => handleUpdate(comment.id)}
                          disabled={editSaving[comment.id]}
                          className="flex items-center gap-1 px-2 py-1 bg-accent text-accent-fg hover:brightness-110 disabled:opacity-50 rounded-[var(--radius-md)] text-xs transition-colors"
                        >
                          {editSaving[comment.id]
                            ? <Loader2 className="h-3 w-3 animate-spin" />
                            : <Check className="h-3 w-3" />}
                          Save
                        </button>
                        <button
                          onClick={() => setEditDrafts((p) => { const next = { ...p }; delete next[comment.id]; return next })}
                          className="px-2 py-1 text-fg-2 hover:text-fg text-xs transition-colors"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <p className="text-xs text-fg whitespace-pre-wrap">{renderCommentContent(comment)}</p>
                  )}

                  {/* Footer */}
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-fg-3">
                      {comment.author_name ?? comment.author_email ?? 'User'} ·{' '}
                      {new Date(comment.created_at).toLocaleDateString()}
                    </span>
                    <div className="flex items-center gap-1">
                      {/* Resolve toggle */}
                      {canComment && <button
                        onClick={() => handleResolve(comment.id)}
                        title={comment.resolved ? 'Unresolve' : 'Resolve'}
                        className={`p-0.5 transition-colors ${
                          comment.resolved
                            ? 'text-ok hover:text-fg-2'
                            : 'text-fg-3 hover:text-ok'
                        }`}
                      >
                        <Check className="h-3.5 w-3.5" />
                      </button>}
                      {canComment && isAuthor && editDrafts[comment.id] === undefined && (
                        <>
                          <button
                            onClick={() => setEditDrafts((p) => ({ ...p, [comment.id]: comment.content }))}
                            className="p-0.5 text-fg-3 hover:text-accent-strong transition-colors"
                            title="Edit"
                          >
                            <Pencil className="h-3 w-3" />
                          </button>
                          <button
                            onClick={() => handleDelete(comment.id)}
                            className="p-0.5 text-fg-3 hover:text-err transition-colors"
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
      {canComment ? (
      <div className="shrink-0 border-t border-line px-3 py-3">
        {participantsError && (
          <div role="alert" className="mb-2 rounded-[var(--radius-md)] border border-err/40 bg-err/10 px-2 py-1.5 text-xs text-err">
            Mention picker unavailable. <button type="button" className="underline" onClick={() => void loadParticipants()}>Retry</button>
          </div>
        )}
        <textarea
          ref={draftRef}
          value={draft}
          aria-label="Comment"
          onChange={(e) => {
            setDraft(e.target.value)
            updateMentionQuery(e.target.value, e.target.selectionStart)
          }}
          onClick={(e) => updateMentionQuery(e.currentTarget.value, e.currentTarget.selectionStart)}
          onKeyUp={(e) => updateMentionQuery(e.currentTarget.value, e.currentTarget.selectionStart)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit()
          }}
          placeholder="Add a comment… (⌘↵ to send)"
          rows={3}
          className="w-full bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-2 text-xs focus:outline-none focus:border-accent resize-none placeholder-fg-3 mb-2"
        />
        {mentionQuery !== null && participants.length > 0 && (
          <div role="listbox" aria-label="Mention collaborators" className="mb-2 max-h-32 overflow-y-auto rounded-[var(--radius-md)] border border-line bg-surface-2 p-1">
            {(() => {
              const matches = participants
                .filter((participant) => participant.user_id !== userId)
                .filter((participant) => participant.display_name.toLowerCase().includes(mentionQuery.toLowerCase()))
              return matches.length ? matches.map((participant) => (
                <button
                  key={participant.user_id}
                  type="button"
                  role="option"
                  aria-selected={false}
                  aria-label={`Mention ${participant.display_name}`}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => selectMention(participant)}
                  className="block w-full rounded px-2 py-1 text-left text-xs text-fg-2 hover:bg-accent-soft hover:text-fg"
                >
                  @{participant.display_name}{participant.email && participant.email !== participant.display_name ? ` (${participant.email})` : ''}
                </button>
              )) : <p role="status" className="px-2 py-1 text-xs text-fg-3">No collaborators match.</p>
            })()}
          </div>
        )}
        {selectedMentionIds.length > 0 && (
          <div aria-label="Selected mentions" className="mb-2 flex flex-wrap gap-1">
            {selectedMentionIds.map((id) => {
              const participant = participants.find((item) => item.user_id === id)
              if (!participant || participant.user_id === userId) return null
              return (
                <button
                  key={id}
                  type="button"
                  aria-label={`Remove mention ${participant.display_name}`}
                  onClick={() => setSelectedMentionIds((ids) => ids.filter((item) => item !== id))}
                  className="rounded bg-accent-soft px-1.5 py-0.5 text-[11px] text-accent-strong"
                >
                  @{participant.display_name}{participant.email && participant.email !== participant.display_name ? ` (${participant.email})` : ''} ×
                </button>
              )
            })}
          </div>
        )}
        {submitError && <p role="alert" className="mb-2 text-xs text-err">{submitError}</p>}
        <button
          onClick={handleSubmit}
          disabled={submitting || !draft.trim()}
          className="flex items-center gap-1.5 px-3 py-1.5 bg-accent text-accent-fg hover:brightness-110 disabled:opacity-50 rounded-[var(--radius-md)] text-xs font-medium transition-colors"
        >
          {submitting
            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
            : <Send className="h-3.5 w-3.5" />}
          Send
        </button>
      </div>
      ) : (
        <p className="shrink-0 border-t border-line px-3 py-3 text-xs text-fg-3">
          Viewer access is read-only. You can read comments but cannot add one.
        </p>
      )}
    </div>
  )
}
