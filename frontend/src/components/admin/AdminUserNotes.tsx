'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminUserNote,
  type AdminUserNoteVisibility,
  type AdminUserSupportTimeline,
  type AdminUserSupportTimelineKind,
  type AdminUserTag,
} from '@/lib/api-client'
import { formatDateTime, shortId } from './admin-format'

const NOTE_PAGE_SIZE = 10
const TIMELINE_PAGE_SIZE = 10

const TIMELINE_LABELS: Record<AdminUserSupportTimelineKind, string> = {
  note: 'Internal note',
  role_change: 'Role change',
  entitlement_change: 'Entitlement change',
  trial_change: 'Trial change',
  quota_change: 'Quota change',
  credential_revocation: 'Credential revoked',
  support_action: 'Support action',
  pii_reveal: 'PII reveal',
  plan_change: 'Plan change',
  refund: 'Refund',
  refund_request: 'Refund request',
  subscription: 'Subscription',
  payment: 'Payment',
  approval: 'Two-person approval',
}

const ADMIN_ONLY_TIMELINE_KINDS: AdminUserSupportTimelineKind[] = ['approval', 'pii_reveal']

function Panel({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description ? <p className="mt-1 text-xs leading-relaxed text-fg-3">{description}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Pill({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'warn' | 'ok' }) {
  const classes =
    tone === 'warn'
      ? 'border-warn/30 bg-warn/10 text-warn'
      : tone === 'ok'
        ? 'border-ok/30 bg-ok/10 text-ok'
        : 'border-line bg-surface-2 text-fg-3'
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${classes}`}
    >
      {label}
    </span>
  )
}

function tagsFromInput(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim().toLowerCase())
    .filter(Boolean)
}

function tagsToInput(tags: string[]): string {
  return tags.join(', ')
}

export default function AdminUserNotes({
  userId,
  canAdmin,
}: {
  userId: string
  canAdmin: boolean
}) {
  const [notes, setNotes] = useState<AdminUserNote[]>([])
  const [availableTags, setAvailableTags] = useState<string[]>([])
  const [tags, setTags] = useState<AdminUserTag[]>([])
  const [timeline, setTimeline] = useState<AdminUserSupportTimeline | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [body, setBody] = useState('')
  const [noteTags, setNoteTags] = useState('')
  const [visibility, setVisibility] = useState<AdminUserNoteVisibility>('internal')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editBody, setEditBody] = useState('')
  const [editTags, setEditTags] = useState('')
  const [tagInput, setTagInput] = useState('')
  const [noteFilterTag, setNoteFilterTag] = useState('')
  const [timelineKind, setTimelineKind] = useState<'' | AdminUserSupportTimelineKind>('')
  const [noteOffset, setNoteOffset] = useState(0)
  const [timelineOffset, setTimelineOffset] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [nextNotes, nextTags, nextTimeline] = await Promise.all([
        apiClient.getAdminUserNotes(userId, {
          tag: noteFilterTag || undefined,
          limit: NOTE_PAGE_SIZE,
          offset: noteOffset,
        }),
        apiClient.getAdminUserTags(userId),
        apiClient.getAdminUserSupportTimeline(userId, {
          kind: timelineKind ? [timelineKind] : undefined,
          limit: TIMELINE_PAGE_SIZE,
          offset: timelineOffset,
        }),
      ])
      setNotes(nextNotes.items)
      setAvailableTags(nextNotes.available_tags)
      setTags(nextTags.items)
      setTimeline(nextTimeline)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load internal notes')
    } finally {
      setLoading(false)
    }
  }, [userId, noteFilterTag, noteOffset, timelineKind, timelineOffset])

  useEffect(() => {
    void load()
  }, [load])

  const cleanedReason = reason.trim()

  const requireReason = (): string | null => {
    if (cleanedReason.length < 3) {
      toast.error('Enter a reason of at least 3 characters for this audited action')
      return null
    }
    return cleanedReason
  }

  const run = async (
    action: string,
    call: () => Promise<unknown>,
    successMessage: string,
    after?: () => void,
  ) => {
    setBusy(action)
    try {
      await call()
      toast.success(successMessage)
      after?.()
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Internal note action failed')
    } finally {
      setBusy(null)
    }
  }

  const createNote = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (body.trim().length < 3) {
      toast.error('Write at least 3 characters of operational context')
      return
    }
    await run(
      'note-create',
      () =>
        apiClient.createAdminUserNote(userId, {
          body: body.trim(),
          tags: tagsFromInput(noteTags),
          visibility,
          reason: cleaned,
        }),
      'Internal note added and audited',
      () => {
        setBody('')
        setNoteTags('')
        setVisibility('internal')
      },
    )
  }

  const startEdit = (note: AdminUserNote) => {
    setEditingId(note.id)
    setEditBody(note.body)
    setEditTags(tagsToInput(note.tags))
  }

  const saveEdit = async (note: AdminUserNote) => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!window.confirm('Save this note edit? The previous text is not copied into the audit log.')) {
      return
    }
    await run(
      `note-edit-${note.id}`,
      () =>
        apiClient.updateAdminUserNote(userId, note.id, {
          expected_version: note.version,
          body: editBody.trim(),
          tags: tagsFromInput(editTags),
          reason: cleaned,
          confirm: true,
        }),
      'Note updated and audited',
      () => setEditingId(null),
    )
  }

  const deleteNote = async (note: AdminUserNote) => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!window.confirm('Soft-delete this internal note? The body is retained for review and the audit log records no note text.')) {
      return
    }
    await run(
      `note-delete-${note.id}`,
      () => apiClient.deleteAdminUserNote(userId, note.id, {
        expected_version: note.version,
        reason: cleaned,
        confirm: true,
      }),
      'Note soft-deleted and audited',
      () => {
        if (editingId === note.id) setEditingId(null)
      },
    )
  }

  const addTag = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!tagInput.trim()) {
      toast.error('Enter a tag first')
      return
    }
    await run(
      'tag-create',
      () => apiClient.createAdminUserTag(userId, { tag: tagInput.trim(), reason: cleaned }),
      'Tag applied and audited',
      () => setTagInput(''),
    )
  }

  const removeTag = async (tag: AdminUserTag) => {
    const cleaned = requireReason()
    if (!cleaned) return
    if (!window.confirm(`Remove the tag "${tag.tag}" from this user?`)) return
    await run(
      `tag-remove-${tag.id}`,
      () => apiClient.removeAdminUserTag(userId, tag.id, { reason: cleaned, confirm: true }),
      'Tag removed and audited',
    )
  }

  const visibleTimelineKinds = useMemo(
    () =>
      (Object.keys(TIMELINE_LABELS) as AdminUserSupportTimelineKind[]).filter(
        (kind) => canAdmin || !ADMIN_ONLY_TIMELINE_KINDS.includes(kind),
      ),
    [canAdmin],
  )

  const notePage = Math.floor(noteOffset / NOTE_PAGE_SIZE) + 1
  const timelinePageSize = Math.max(1, timeline?.limit ?? TIMELINE_PAGE_SIZE)
  const timelinePage = timeline ? Math.floor(timeline.offset / timelinePageSize) + 1 : 1
  const timelinePages = timeline ? Math.max(1, Math.ceil(timeline.total / timelinePageSize)) : 1

  return (
    <Panel
      title="Internal notes, tags and support timeline"
      description="Operator-only. Notes and tags never appear on customer APIs. Every write requires a reason and is audited; note text is excluded from audit snapshots. Support can edit only its own internal notes; admin-only notes and approvals are hidden from support."
    >
      {error ? (
        <div role="alert" className="mb-3 rounded-md border border-err/20 bg-err/[0.06] px-3 py-2 text-xs text-err">
          {error}{' '}
          <button type="button" onClick={() => void load()} className="ml-2 underline">
            Retry
          </button>
        </div>
      ) : null}

      <label className="block text-[11px] font-medium text-fg-2">
        Reason for this note/tag session
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={1000}
          placeholder="e.g. Ticket #1234 billing escalation"
          className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
        />
      </label>

      <div className="mt-3 rounded-md border border-line bg-surface-2/40 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold text-fg">Tags</p>
          <span className="text-[10px] text-fg-3">{tags.length} active</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag.id}
              className="inline-flex items-center gap-1 rounded-full border border-line bg-bg px-2 py-0.5 text-[10px] text-fg-2"
            >
              {tag.tag}
              {tag.can_remove ? (
                <button
                  type="button"
                  aria-label={`Remove tag ${tag.tag}`}
                  onClick={() => void removeTag(tag)}
                  disabled={Boolean(busy)}
                  className="text-fg-3 hover:text-err disabled:opacity-40"
                >
                  ×
                </button>
              ) : null}
            </span>
          ))}
          {tags.length === 0 ? <span className="text-[11px] text-fg-3">No tags yet.</span> : null}
        </div>
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            value={tagInput}
            onChange={(event) => setTagInput(event.target.value)}
            maxLength={32}
            placeholder="e.g. billing-review"
            className="min-w-0 flex-1 rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
          />
          <button
            type="button"
            onClick={() => void addTag()}
            disabled={Boolean(busy)}
            className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
          >
            Add tag
          </button>
        </div>
      </div>

      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-md border border-line bg-surface-2/40 p-3">
          <p className="text-xs font-semibold text-fg">Add internal note</p>
          <textarea
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={4}
            maxLength={4000}
            placeholder="Operational context. Do not paste emails, phone numbers, secrets or document content."
            className="mt-2 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
          />
          <input
            value={noteTags}
            onChange={(event) => setNoteTags(event.target.value)}
            maxLength={260}
            placeholder="Tags, comma-separated"
            className="mt-2 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg"
          />
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <select
              aria-label="Note visibility"
              value={visibility}
              onChange={(event) => setVisibility(event.target.value as AdminUserNoteVisibility)}
              disabled={!canAdmin}
              className="rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg disabled:opacity-50"
            >
              <option value="internal">All internal roles</option>
              {canAdmin ? <option value="admin_only">Admins only</option> : null}
            </select>
            <button
              type="button"
              onClick={() => void createNote()}
              disabled={Boolean(busy)}
              className="rounded border border-line px-3 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
            >
              Add note
            </button>
          </div>
        </div>

        <div className="rounded-md border border-line bg-surface-2/40 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold text-fg">Notes</p>
            <div className="flex items-center gap-2">
              <select
                aria-label="Filter notes by tag"
                value={noteFilterTag}
                onChange={(event) => {
                  setNoteFilterTag(event.target.value)
                  setNoteOffset(0)
                }}
                className="rounded border border-line bg-bg px-2 py-1 text-[10px] text-fg-2"
              >
                <option value="">All tags</option>
                {availableTags.map((tag) => (
                  <option key={tag} value={tag}>
                    {tag}
                  </option>
                ))}
              </select>
              {canAdmin ? (
                <button
                  type="button"
                  onClick={() => {
                    setNoteFilterTag('')
                    setNoteOffset(0)
                  }}
                  className="rounded border border-line px-2 py-1 text-[10px] text-fg-2"
                >
                  Clear filter
                </button>
              ) : null}
            </div>
          </div>

          <ul className="mt-2 max-h-[28rem] space-y-2 overflow-auto">
            {notes.map((note) => (
              <li key={note.id} className="rounded border border-line bg-bg px-3 py-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill label={note.author_role} />
                  <Pill label={note.visibility === 'admin_only' ? 'admins only' : 'internal'} tone={note.visibility === 'admin_only' ? 'warn' : 'neutral'} />
                  <span className="text-[10px] text-fg-3">{formatDateTime(note.created_at)}</span>
                  {note.edited_at ? <span className="text-[10px] text-fg-3">edited {formatDateTime(note.edited_at)}</span> : null}
                  <span className="font-mono text-[10px] text-fg-3">{shortId(note.author_user_id, 8)}</span>
                </div>
                {editingId === note.id ? (
                  <div className="mt-2">
                    <textarea
                      value={editBody}
                      onChange={(event) => setEditBody(event.target.value)}
                      rows={4}
                      maxLength={4000}
                      className="w-full rounded border border-line bg-surface px-2 py-1.5 text-xs text-fg"
                    />
                    <input
                      value={editTags}
                      onChange={(event) => setEditTags(event.target.value)}
                      maxLength={260}
                      placeholder="Tags, comma-separated"
                      className="mt-2 w-full rounded border border-line bg-surface px-2 py-1.5 text-xs text-fg"
                    />
                    <div className="mt-2 flex gap-2">
                      <button
                        type="button"
                        onClick={() => void saveEdit(note)}
                        disabled={Boolean(busy)}
                        className="rounded border border-line px-2 py-1 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40"
                      >
                        Save with reason
                      </button>
                      <button
                        type="button"
                        onClick={() => setEditingId(null)}
                        className="rounded border border-line px-2 py-1 text-[10px] text-fg-3"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <>
                    <p className="mt-1 whitespace-pre-wrap break-words text-xs text-fg-2">{note.body}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1">
                      {note.tags.map((tag) => (
                        <span key={tag} className="rounded bg-surface-2 px-1.5 py-0.5 text-[9px] text-fg-3">
                          {tag}
                        </span>
                      ))}
                      {note.can_edit ? (
                        <button
                          type="button"
                          onClick={() => startEdit(note)}
                          disabled={Boolean(busy)}
                          className="rounded border border-line px-2 py-0.5 text-[9px] text-fg-3 hover:bg-surface-2 disabled:opacity-40"
                        >
                          Edit
                        </button>
                      ) : null}
                      {note.can_delete ? (
                        <button
                          type="button"
                          onClick={() => void deleteNote(note)}
                          disabled={Boolean(busy)}
                          className="rounded border border-err/30 px-2 py-0.5 text-[9px] text-err hover:bg-err/5 disabled:opacity-40"
                        >
                          Delete
                        </button>
                      ) : null}
                    </div>
                  </>
                )}
              </li>
            ))}
            {notes.length === 0 && !loading ? (
              <li className="py-3 text-center text-[11px] text-fg-3">No internal notes.</li>
            ) : null}
          </ul>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span className="text-[10px] text-fg-3">Page {notePage}</span>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setNoteOffset(Math.max(0, noteOffset - NOTE_PAGE_SIZE))}
                disabled={loading || noteOffset <= 0}
                className="rounded border border-line px-2 py-1 text-[10px] text-fg-2 disabled:opacity-40"
              >
                Newer
              </button>
              <button
                type="button"
                onClick={() => setNoteOffset(noteOffset + NOTE_PAGE_SIZE)}
                disabled={loading || notes.length < NOTE_PAGE_SIZE}
                className="rounded border border-line px-2 py-1 text-[10px] text-fg-2 disabled:opacity-40"
              >
                Older
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="mt-4 rounded-md border border-line bg-surface-2/40 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <p className="text-xs font-semibold text-fg">Merged support timeline</p>
            <p className="mt-0.5 text-[10px] text-fg-3">
              Notes, role/entitlement/trial/quota actions, credential revocations, refunds, payments and approvals.
              {timeline?.restricted_kinds.length ? ` Restricted for support: ${timeline.restricted_kinds.join(', ')}.` : ''}
            </p>
          </div>
          <select
            aria-label="Filter support timeline"
            value={timelineKind}
            onChange={(event) => {
              setTimelineKind(event.target.value as '' | AdminUserSupportTimelineKind)
              setTimelineOffset(0)
            }}
            className="rounded border border-line bg-bg px-2 py-1 text-[10px] text-fg-2"
          >
            <option value="">All events</option>
            {visibleTimelineKinds.map((kind) => (
              <option key={kind} value={kind}>
                {TIMELINE_LABELS[kind]}
              </option>
            ))}
          </select>
        </div>
        <ol className="mt-2 divide-y divide-line overflow-hidden rounded border border-line bg-bg">
          {(timeline?.items ?? []).map((item) => (
            <li key={item.id} className="flex flex-wrap items-start justify-between gap-2 px-3 py-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Pill label={TIMELINE_LABELS[item.kind] ?? item.kind} />
                  <span className="text-[10px] text-fg-3">{formatDateTime(item.occurred_at)}</span>
                  {item.actor_user_id ? (
                    <span className="font-mono text-[10px] text-fg-3">{shortId(item.actor_user_id, 8)}</span>
                  ) : null}
                  {item.admin_only ? <Pill label="admin only" tone="warn" /> : null}
                </div>
                <p className="mt-1 text-xs text-fg-2">{item.summary || item.event_type || 'Support event'}</p>
                {item.status ? <p className="text-[10px] text-fg-3">status {item.status}</p> : null}
              </div>
              {item.amount_minor != null ? (
                <span className="shrink-0 font-mono text-[11px] text-fg">
                  {(item.amount_minor / 100).toFixed(2)} {item.currency || ''}
                </span>
              ) : null}
            </li>
          ))}
          {timeline && timeline.items.length === 0 ? (
            <li className="px-3 py-3 text-center text-[11px] text-fg-3">No support events.</li>
          ) : null}
          {!timeline && loading ? (
            <li className="px-3 py-3 text-center text-[11px] text-fg-3">Loading timeline…</li>
          ) : null}
        </ol>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-[10px] text-fg-3" aria-live="polite">
            Page {timelinePage} of {timelinePages}
            {timeline ? ` · ${timeline.total} events` : ''}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setTimelineOffset(Math.max(0, timelineOffset - timelinePageSize))}
              disabled={loading || !timeline || timeline.offset <= 0}
              className="rounded border border-line px-2 py-1 text-[10px] text-fg-2 disabled:opacity-40"
            >
              Newer
            </button>
            <button
              type="button"
              onClick={() => setTimelineOffset(timeline?.next_offset ?? timelineOffset + timelinePageSize)}
              disabled={loading || !timeline?.has_more}
              className="rounded border border-line px-2 py-1 text-[10px] text-fg-2 disabled:opacity-40"
            >
              Older
            </button>
          </div>
        </div>
        <p className="mt-2 text-[10px] leading-relaxed text-fg-3">
          Note bodies never enter the audit log or this timeline. Soft-deleted notes are retained for review under the
          support-notes retention policy; no worker deletes them automatically.
        </p>
      </div>
    </Panel>
  )
}
