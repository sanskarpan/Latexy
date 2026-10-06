'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Loader2, MessageSquare, Send } from 'lucide-react'
import {
  apiClient,
  type ReviewCommentCreateRequest,
  type ReviewCommentResponse,
} from '@/lib/api-client'
import ReviewablePdfSurface, { type ReviewDocumentAnchor } from '@/components/ReviewablePdfSurface'
import { reviewRequestIsCurrent } from '@/lib/review-async-guard'

interface ReviewCommentsPanelProps {
  /** Public mode uses the live share capability and a pseudonymous cookie. */
  shareToken?: string
  /** Authenticated mode loads the owner's/collaborator's review thread. */
  resumeId?: string
  enabled?: boolean
  canResolve?: boolean
  title?: string
  /** Optional rendered PDF surface. It is only supplied for review-capable documents. */
  pdfUrl?: string | null
}

function errorMessage(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : fallback
  if (/429|too many/i.test(message)) return 'Review limit reached. Please try again later.'
  if (/503|temporarily unavailable|network/i.test(message)) {
    return 'Review comments are temporarily unavailable. Please retry.'
  }
  if (/404|revoked|not found/i.test(message)) return 'This review link has been revoked.'
  if (/403|access/i.test(message)) return 'You do not have permission to access review comments.'
  return message
}

export default function ReviewCommentsPanel({
  shareToken,
  resumeId,
  enabled = true,
  canResolve = false,
  title = 'Review comments',
  pdfUrl = null,
}: ReviewCommentsPanelProps) {
  const isPublic = Boolean(shareToken)
  const [comments, setComments] = useState<ReviewCommentResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [capabilityInvalid, setCapabilityInvalid] = useState(false)
  const [historyTruncated, setHistoryTruncated] = useState(false)
  const [content, setContent] = useState('')
  const [lineNumber, setLineNumber] = useState('')
  const [sectionTag, setSectionTag] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [resolving, setResolving] = useState<Record<string, boolean>>({})
  const [selectedAnchor, setSelectedAnchor] = useState<ReviewDocumentAnchor | null>(null)
  const [selectedCommentId, setSelectedCommentId] = useState<string | null>(null)
  const identityGeneration = useRef(0)

  // A panel can be reused while navigating between resumes/share tokens. Do
  // not let the previous capability's comments remain visible during the
  // transition or leak into the next request.
  useEffect(() => {
    identityGeneration.current += 1
    setComments([])
    setSelectedAnchor(null)
    setSelectedCommentId(null)
    setResolving({})
    setContent('')
    setLineNumber('')
    setSectionTag('')
    setSubmitting(false)
    setCapabilityInvalid(false)
    setHistoryTruncated(false)
    setLoadError(null)
    setSubmitError(null)
  }, [enabled, resumeId, shareToken])

  const load = useCallback(async () => {
    if (!enabled || (!shareToken && !resumeId)) {
      setLoading(false)
      return
    }
    const generation = identityGeneration.current
    setLoading(true)
    setLoadError(null)
    setCapabilityInvalid(false)
    try {
      const result = shareToken
        ? { comments: await apiClient.listPublicReviewComments(shareToken), truncated: false }
        : await apiClient.listReviewComments(resumeId as string)
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      setComments(result.comments)
      setHistoryTruncated(result.truncated)
    } catch (error) {
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      if (/404|revoked|not found/i.test(error instanceof Error ? error.message : '')) {
        // Do not leave a previously fetched PDF and write form active after
        // the owner revokes/rotates the share capability.
        setCapabilityInvalid(true)
        setComments([])
        setSelectedAnchor(null)
        setSelectedCommentId(null)
        setHistoryTruncated(false)
      }
      setLoadError(errorMessage(error, 'Failed to load review comments'))
    } finally {
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      setLoading(false)
    }
  }, [enabled, resumeId, shareToken])

  useEffect(() => {
    void load()
  }, [load])

  async function submit() {
    const trimmed = content.trim()
    if (!trimmed || submitting) return
    if (isPublic && pdfUrl && !selectedAnchor) {
      setSubmitError('Select a point on the document before posting feedback.')
      return
    }
    const parsedLine = lineNumber.trim() ? Number(lineNumber) : undefined
    if (parsedLine !== undefined && (!Number.isInteger(parsedLine) || parsedLine < 1)) {
      setSubmitError('Source line must be a positive whole number.')
      return
    }
    const request: ReviewCommentCreateRequest = {
      content: trimmed,
      ...(selectedAnchor ?? {}),
      ...(parsedLine === undefined ? {} : { line_number: parsedLine }),
      ...(sectionTag.trim() ? { section_tag: sectionTag.trim() } : {}),
    }
    setSubmitting(true)
    setSubmitError(null)
    const generation = identityGeneration.current
    try {
      if (!shareToken) {
        setSubmitError('Public review comments require a live review link.')
        return
      }
      const created = await apiClient.addPublicReviewComment(shareToken, request)
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      setComments((current) => [...current, created])
      setContent('')
      setSelectedAnchor(null)
      setLineNumber('')
      setSectionTag('')
    } catch (error) {
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      if (/404|revoked|not found/i.test(error instanceof Error ? error.message : '')) {
        setCapabilityInvalid(true)
        setComments([])
        setSelectedAnchor(null)
        setSelectedCommentId(null)
      }
      setSubmitError(errorMessage(error, 'Failed to add review comment'))
    } finally {
      if (reviewRequestIsCurrent(generation, identityGeneration.current)) setSubmitting(false)
    }
  }

  async function setResolved(comment: ReviewCommentResponse, resolved: boolean) {
    if (!resumeId || resolving[comment.id]) return
    setResolving((current) => ({ ...current, [comment.id]: true }))
    const generation = identityGeneration.current
    try {
      const updated = await apiClient.resolveReviewComment(resumeId, comment.id, resolved)
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      setComments((current) => current.map((item) => item.id === updated.id ? updated : item))
    } catch (error) {
      if (!reviewRequestIsCurrent(generation, identityGeneration.current)) return
      setLoadError(errorMessage(error, 'Failed to update review comment'))
    } finally {
      if (reviewRequestIsCurrent(generation, identityGeneration.current)) {
        setResolving((current) => ({ ...current, [comment.id]: false }))
      }
    }
  }

  if (!enabled) return null

  return (
    <section aria-labelledby="review-comments-heading" className="flex min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-line px-3 py-3">
        <MessageSquare size={14} className="text-accent-strong" aria-hidden="true" />
        <h2 id="review-comments-heading" className="text-sm font-semibold text-fg">{title}</h2>
      </div>

      {loadError && (
        <div role="alert" className="m-3 rounded border border-err/30 bg-err/10 p-2 text-xs text-err">
          <p>{loadError}</p>
          <button type="button" onClick={() => void load()} className="mt-1 underline">Retry</button>
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {capabilityInvalid && (
          <p role="status" className="rounded border border-line bg-surface-2 p-3 text-xs text-fg-3">
            Review access is no longer available for this document.
          </p>
        )}
        {!capabilityInvalid && pdfUrl && (
          <ReviewablePdfSurface
            pdfUrl={pdfUrl}
            comments={comments}
            selectedAnchor={selectedAnchor}
            selectedCommentId={selectedCommentId}
            onAnchorSelect={(anchor) => {
              setSelectedAnchor(anchor)
              setSelectedCommentId(null)
            }}
            onCommentSelect={(comment) => {
              setSelectedCommentId(comment.id)
              setSelectedAnchor({ page_number: comment.page_number!, x: comment.x!, y: comment.y! })
            }}
          />
        )}
        {capabilityInvalid ? null : loading ? (
          <div role="status" className="flex items-center justify-center gap-2 py-8 text-xs text-fg-3">
            <Loader2 size={14} className="animate-spin" /> Loading comments…
          </div>
        ) : comments.length === 0 ? (
          <p className="py-6 text-center text-xs text-fg-3">No review comments yet.</p>
        ) : comments.map((comment) => (
          <article key={comment.id} data-testid="review-comment" className={`rounded border p-3 ${comment.resolved ? 'border-line bg-surface-2 opacity-70' : 'border-accent/30 bg-accent-soft/30'}`}>
            <div className="flex items-start justify-between gap-2">
              <p className="text-[11px] font-semibold text-fg-2">{comment.reviewer_label}</p>
              {comment.resolved && <Check size={13} className="text-ok" aria-label="Resolved" />}
            </div>
            {(comment.line_number || comment.section_tag) && (
              <p className="mt-1 text-[10px] text-fg-3">
                {comment.section_tag ? `Legacy section reference: ${comment.section_tag}` : 'Legacy source reference'}
                {comment.line_number ? ` · source line ${comment.line_number}` : ''}
              </p>
            )}
            {comment.page_number !== null && comment.x !== null && comment.y !== null && (
              <p className="mt-1 text-[10px] text-fg-3">Pinned to page {comment.page_number}</p>
            )}
            <p className="mt-2 whitespace-pre-wrap break-words text-xs leading-relaxed text-fg-2">{comment.content}</p>
            {canResolve && resumeId && (
              <button
                type="button"
                onClick={() => void setResolved(comment, !comment.resolved)}
                disabled={resolving[comment.id]}
                className="mt-2 text-[10px] font-medium text-accent-strong underline disabled:opacity-50"
              >
                {resolving[comment.id] ? 'Saving…' : comment.resolved ? 'Mark unresolved' : 'Mark resolved'}
              </button>
            )}
          </article>
        ))}
        {!capabilityInvalid && historyTruncated && (
          <p role="status" className="border-t border-line pt-2 text-[11px] text-fg-3">
            Showing the newest 1,000 comments. Older review history is not loaded in this view.
          </p>
        )}
      </div>

      {isPublic && !capabilityInvalid && (
        <div className="border-t border-line p-3">
          <label htmlFor="public-review-comment" className="text-[11px] font-medium text-fg-2">Leave feedback</label>
          <textarea
            id="public-review-comment"
            value={content}
            onChange={(event) => setContent(event.target.value)}
            maxLength={4000}
            rows={4}
            placeholder="Suggest a change or ask a question…"
            className="mt-1 w-full resize-y rounded border border-line bg-surface px-2 py-2 text-xs text-fg outline-none focus:border-accent"
          />
          {pdfUrl && !selectedAnchor && (
            <p role="status" className="mt-2 text-[11px] text-fg-3">
              Select a point on the rendered document to pin this feedback.
            </p>
          )}
          {selectedAnchor && (
            <p role="status" className="mt-2 rounded bg-warn/10 px-2 py-1.5 text-[11px] text-fg-2">
              Anchor selected: page {selectedAnchor.page_number}. Your feedback will be pinned to this spot.
            </p>
          )}
          <div className="mt-2 grid grid-cols-2 gap-2">
            <input
              inputMode="numeric"
              value={lineNumber}
              onChange={(event) => setLineNumber(event.target.value)}
              placeholder="Legacy source line (optional)"
              aria-label="Legacy source line (optional; not linked to the document)"
              className="rounded border border-line bg-surface px-2 py-1.5 text-[11px] text-fg outline-none focus:border-accent"
            />
            <input
              value={sectionTag}
              onChange={(event) => setSectionTag(event.target.value)}
              maxLength={100}
              placeholder="Legacy section (optional)"
              aria-label="Legacy section (optional; not linked to the document)"
              className="rounded border border-line bg-surface px-2 py-1.5 text-[11px] text-fg outline-none focus:border-accent"
            />
          </div>
          {submitError && <p role="alert" className="mt-2 text-[11px] text-err">{submitError}</p>}
          <button
            type="button"
            onClick={() => void submit()}
            disabled={submitting || !content.trim() || Boolean(pdfUrl && !selectedAnchor)}
            className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded border border-accent bg-accent-soft px-3 py-2 text-xs font-semibold text-accent-strong disabled:opacity-50"
          >
            {submitting ? <Loader2 size={12} className="animate-spin" /> : <Send size={12} />}
            Post review comment
          </button>
          <p className="mt-2 text-[10px] text-fg-3">Your label is pseudonymous to the resume owner.</p>
        </div>
      )}
    </section>
  )
}
