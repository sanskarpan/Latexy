'use client'

import { useEffect, useRef, useState } from 'react'
import { X, UserPlus, Users, Crown, Eye, MessageSquare, Trash2, Loader2, ChevronDown } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type CollaboratorInfo, type CollabRole, type PresenceUser } from '@/lib/api-client'

// ── Constants ─────────────────────────────────────────────────────────────────

const ROLE_META: Record<CollabRole, { label: string; icon: React.ReactNode; desc: string }> = {
  editor: {
    label: 'Editor',
    icon: <MessageSquare size={11} />,
    desc: 'Can edit',
  },
  commenter: {
    label: 'Commenter',
    icon: <MessageSquare size={11} />,
    desc: 'Can comment',
  },
  viewer: {
    label: 'Viewer',
    icon: <Eye size={11} />,
    desc: 'Read-only',
  },
}

// ── Props ──────────────────────────────────────────────────────────────────────

interface CollaboratorPanelProps {
  open: boolean
  resumeId: string
  isOwner: boolean
  presenceUsers: PresenceUser[]
  onClose: () => void
}

// ── Component ─────────────────────────────────────────────────────────────────

export default function CollaboratorPanel({
  open,
  resumeId,
  isOwner,
  presenceUsers,
  onClose,
}: CollaboratorPanelProps) {
  const [collaborators, setCollaborators] = useState<CollaboratorInfo[]>([])
  const [loadingList, setLoadingList] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<CollabRole>('editor')
  const [inviting, setInviting] = useState(false)
  const [removingId, setRemovingId] = useState<string | null>(null)
  const [roleChangeId, setRoleChangeId] = useState<string | null>(null)
  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  useEffect(() => {
    if (!open || !isOwner) return
    setLoadingList(true)
    apiClient.listCollaborators(resumeId)
      .then(setCollaborators)
      .catch(() => toast.error('Could not load collaborators'))
      .finally(() => setLoadingList(false))
  }, [open, resumeId, isOwner])

  if (!open) return null

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault()
    if (!inviteEmail.trim()) return
    setInviting(true)
    try {
      const newCollab = await apiClient.inviteCollaborator(resumeId, inviteEmail.trim(), inviteRole)
      setCollaborators((prev) => [...prev, newCollab])
      setInviteEmail('')
      toast.success(`Invited ${inviteEmail}`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to invite')
    } finally {
      setInviting(false)
    }
  }

  async function handleRoleChange(collab: CollaboratorInfo, newRole: CollabRole) {
    setRoleChangeId(collab.user_id)
    try {
      const updated = await apiClient.updateCollaboratorRole(resumeId, collab.user_id, newRole)
      setCollaborators((prev) => prev.map((c) => (c.user_id === collab.user_id ? updated : c)))
    } catch {
      toast.error('Failed to update role')
    } finally {
      setRoleChangeId(null)
    }
  }

  async function handleRemove(collab: CollaboratorInfo) {
    setRemovingId(collab.user_id)
    try {
      await apiClient.removeCollaborator(resumeId, collab.user_id)
      setCollaborators((prev) => prev.filter((c) => c.user_id !== collab.user_id))
      toast.success(`Removed ${collab.user_name ?? collab.user_email}`)
    } catch {
      toast.error('Failed to remove collaborator')
    } finally {
      setRemovingId(null)
    }
  }

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose() }}
    >
      <div className="relative w-full max-w-md rounded-2xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/15">
              <Users size={14} className="text-violet-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Collaborators</h2>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-5 px-5 py-5">
          {/* Live presence */}
          {presenceUsers.length > 0 && (
            <div className="space-y-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                Currently editing
              </p>
              <div className="flex flex-wrap gap-2">
                {presenceUsers.map((u, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium"
                    style={{ backgroundColor: `${u.color}22`, color: u.color, border: `1px solid ${u.color}44` }}
                  >
                    <span
                      className="h-1.5 w-1.5 rounded-full animate-pulse"
                      style={{ backgroundColor: u.color }}
                    />
                    {u.name}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Invite form (owner only) */}
          {isOwner && (
            <form onSubmit={handleInvite} className="space-y-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                Invite by email
              </p>
              <div className="flex gap-1.5">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@example.com"
                  className="min-w-0 flex-1 rounded-lg border border-white/[0.08] bg-[#141414] px-3 py-2 text-[12px] text-zinc-200 outline-none placeholder:text-zinc-600 focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
                />
                {/* Role selector */}
                <div className="relative">
                  <select
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value as CollabRole)}
                    className="appearance-none rounded-lg border border-white/[0.08] bg-[#141414] py-2 pl-3 pr-7 text-[11px] text-zinc-300 outline-none focus:border-violet-500/40"
                  >
                    {(Object.keys(ROLE_META) as CollabRole[]).map((r) => (
                      <option key={r} value={r}>{ROLE_META[r].label}</option>
                    ))}
                  </select>
                  <ChevronDown size={10} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-zinc-500" />
                </div>
                <button
                  type="submit"
                  disabled={inviting || !inviteEmail.trim()}
                  className="flex items-center gap-1 rounded-lg bg-violet-600/80 px-3 py-2 text-[11px] font-semibold text-white ring-1 ring-violet-500/30 transition hover:bg-violet-600 disabled:opacity-40"
                >
                  {inviting ? <Loader2 size={11} className="animate-spin" /> : <UserPlus size={11} />}
                  {inviting ? 'Inviting…' : 'Invite'}
                </button>
              </div>
            </form>
          )}

          {/* Collaborator list */}
          {isOwner && (
            <div className="space-y-2">
              <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                {loadingList ? 'Loading…' : `${collaborators.length} collaborator${collaborators.length !== 1 ? 's' : ''}`}
              </p>
              {loadingList ? (
                <div className="flex justify-center py-4">
                  <Loader2 size={16} className="animate-spin text-zinc-600" />
                </div>
              ) : collaborators.length === 0 ? (
                <p className="py-3 text-center text-[11px] text-zinc-700">
                  No collaborators yet. Invite someone above.
                </p>
              ) : (
                <div className="space-y-1">
                  {collaborators.map((collab) => {
                    const isLiveUser = presenceUsers.some((p) => p.name === collab.user_name)
                    return (
                      <div
                        key={collab.id}
                        className="flex items-center gap-3 rounded-lg border border-white/[0.05] bg-white/[0.02] px-3 py-2.5"
                      >
                        {/* Avatar */}
                        <div
                          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[10px] font-bold uppercase text-white"
                          style={{ backgroundColor: isLiveUser ? '#7c3aed' : '#374151' }}
                        >
                          {(collab.user_name || collab.user_email || '?')[0]}
                        </div>

                        {/* Name + email */}
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[12px] font-medium text-zinc-200">
                            {collab.user_name || collab.user_email}
                          </p>
                          {collab.user_name && (
                            <p className="truncate text-[10px] text-zinc-600">{collab.user_email}</p>
                          )}
                        </div>

                        {/* Role selector */}
                        <div className="relative">
                          {roleChangeId === collab.user_id ? (
                            <Loader2 size={10} className="animate-spin text-zinc-500" />
                          ) : (
                            <select
                              value={collab.role}
                              onChange={(e) => handleRoleChange(collab, e.target.value as CollabRole)}
                              className="appearance-none rounded border border-white/[0.08] bg-transparent py-0.5 pl-2 pr-5 text-[10px] text-zinc-400 outline-none"
                            >
                              {(Object.keys(ROLE_META) as CollabRole[]).map((r) => (
                                <option key={r} value={r}>{ROLE_META[r].label}</option>
                              ))}
                            </select>
                          )}
                        </div>

                        {/* Remove button */}
                        <button
                          onClick={() => handleRemove(collab)}
                          disabled={removingId === collab.user_id}
                          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-zinc-600 transition hover:bg-red-500/15 hover:text-red-400 disabled:opacity-40"
                          title="Remove collaborator"
                        >
                          {removingId === collab.user_id ? (
                            <Loader2 size={10} className="animate-spin" />
                          ) : (
                            <Trash2 size={10} />
                          )}
                        </button>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* Info for non-owners */}
          {!isOwner && (
            <p className="text-center text-[11px] text-zinc-600">
              You were invited to collaborate on this resume.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
