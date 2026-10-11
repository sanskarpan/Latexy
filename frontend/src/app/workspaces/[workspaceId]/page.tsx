'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import {
  ArrowLeft, Building2, Users, FileText, Plus, Trash2, Loader2, Download,
  UserMinus, ChevronDown, Check, X, ExternalLink
} from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type WorkspaceDetailResponse,
  type WorkspaceMemberResponse,
  type WorkspaceResumeItem,
  type ResumeResponse,
} from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import { downloadBlob } from '@/lib/download'

type RoleOption = 'editor' | 'viewer'

export default function WorkspaceDetailPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()

  const { can } = useEntitlements()
  const canManage = can('f08')
  const canManageRef = useRef(canManage)
  canManageRef.current = canManage

  const [ws, setWs] = useState<WorkspaceDetailResponse | null>(null)
  const [resumes, setResumes] = useState<WorkspaceResumeItem[]>([])
  const [myResumes, setMyResumes] = useState<ResumeResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<RoleOption>('editor')
  const [inviting, setInviting] = useState(false)
  const [showAddResume, setShowAddResume] = useState(false)
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)
  const [reloadNonce, setReloadNonce] = useState(0)

  const userId = session?.user?.id ?? ''

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
      .then(([detail, wrs]) => {
        setWs(detail)
        setNameInput(detail.name)
        setResumes(wrs)
      })
      .catch((error) => {
        setLoadError(error instanceof Error ? error.message : 'Failed to load workspace')
        toast.error('Failed to load workspace')
      })
      .finally(() => setLoading(false))
  }, [session, workspaceId, reloadNonce])

  // Loading the picker is a new sharing flow; saved workspace data remains readable.
  useEffect(() => {
    if (!session?.user || !canManage) return
    let active = true
    apiClient.listAllResumes().then((items) => {
      if (active) setMyResumes(items)
    }).catch(() => {
      if (active) toast.error('Failed to load your resumes')
    })
    return () => { active = false }
  }, [session, canManage])

  const isOwner = ws?.owner_id === userId

  // ── Rename ──────────────────────────────────────────────────────────────────

  async function handleRename() {
    if (!canManageRef.current || !isOwner) return
    const name = nameInput.trim()
    if (!name || !ws) return
    try {
      const updated = await apiClient.updateWorkspace(workspaceId, name)
      setWs((prev) => prev ? { ...prev, name: updated.name } : prev)
      setEditingName(false)
      toast.success('Workspace renamed')
    } catch {
      toast.error('Failed to rename workspace')
    }
  }

  // ── Invite member ───────────────────────────────────────────────────────────

  async function handleInvite() {
    if (!canManageRef.current || !isOwner) return
    const email = inviteEmail.trim()
    if (!email) return
    setInviting(true)
    try {
      const member = await apiClient.inviteWorkspaceMember(workspaceId, email, inviteRole)
      setWs((prev) =>
        prev ? { ...prev, members: [...prev.members, member], member_count: prev.member_count + 1 } : prev
      )
      setInviteEmail('')
      toast.success(`${email} added to workspace`)
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? 'Failed to invite member'
      toast.error(msg)
    } finally {
      setInviting(false)
    }
  }

  // ── Remove member ───────────────────────────────────────────────────────────

  async function handleRemoveMember(member: WorkspaceMemberResponse) {
    if (!confirm(`Remove ${member.email ?? member.user_id} from this workspace?`)) return
    try {
      await apiClient.removeWorkspaceMember(workspaceId, member.user_id)
      setWs((prev) =>
        prev
          ? { ...prev, members: prev.members.filter((m) => m.user_id !== member.user_id), member_count: prev.member_count - 1 }
          : prev
      )
      toast.success('Member removed')
    } catch {
      toast.error('Failed to remove member')
    }
  }

  // ── Change role ─────────────────────────────────────────────────────────────

  async function handleRoleChange(member: WorkspaceMemberResponse, role: RoleOption) {
    // Reducing an existing member's access is still available during a downgrade.
    if (!isOwner || (role !== 'viewer' && !canManageRef.current)) return
    try {
      const updated = await apiClient.updateWorkspaceMemberRole(workspaceId, member.user_id, role)
      setWs((prev) =>
        prev
          ? {
              ...prev,
              members: prev.members.map((m) =>
                m.user_id === member.user_id ? { ...m, role: updated.role } : m
              ),
            }
          : prev
      )
    } catch {
      toast.error('Failed to update role')
    }
  }

  // ── Add resume ──────────────────────────────────────────────────────────────

  async function handleAddResume(resumeId: string) {
    if (!canManageRef.current) return
    try {
      const item = await apiClient.addResumeToWorkspace(workspaceId, resumeId)
      setResumes((prev) => [...prev, item])
      setWs((prev) => prev ? { ...prev, resume_count: prev.resume_count + 1 } : prev)
      setShowAddResume(false)
      toast.success('Resume added to workspace')
    } catch (err: unknown) {
      const msg = (err as { message?: string })?.message ?? 'Failed to add resume'
      toast.error(msg)
    }
  }

  // ── Remove resume ───────────────────────────────────────────────────────────

  async function handleRemoveResume(resumeId: string, title: string) {
    if (!confirm(`Remove "${title}" from this workspace?`)) return
    try {
      await apiClient.removeResumeFromWorkspace(workspaceId, resumeId)
      setResumes((prev) => prev.filter((r) => r.id !== resumeId))
      setWs((prev) => prev ? { ...prev, resume_count: Math.max(0, prev.resume_count - 1) } : prev)
      toast.success('Resume removed')
    } catch {
      toast.error('Failed to remove resume')
    }
  }

  async function handleDownloadResume(resumeId: string, title: string) {
    try {
      const blob = await apiClient.downloadWorkspaceResume(workspaceId, resumeId)
      downloadBlob(blob, `${title.replace(/[^a-z0-9_-]+/gi, '_') || 'resume'}.pdf`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Resume download failed')
    }
  }

  if (sessionLoading || loading) return <LoadingSpinner />
  if (sessionError && !session) return <SessionLoadError area="Team workspace" />
  if (!session?.user) return null
  if (!ws) {
    return (
      <div className="min-h-screen bg-bg p-6 text-fg">
        <div role="alert" className="mx-auto mt-20 max-w-lg rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.07] p-8 text-center">
          <h1 className="text-lg font-semibold text-err">Team workspace could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-2">{loadError ?? 'The workspace is unavailable.'}</p>
          <div className="mt-6 flex justify-center gap-3">
            <Link href="/workspaces" className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-xs font-semibold text-fg-2 hover:text-fg">
              All Workspaces
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

  const sharedResumeIds = new Set(resumes.map((r) => r.id))
  const unsharedResumes = myResumes.filter((r) => !sharedResumeIds.has(r.id))

  return (
    <div className="min-h-screen bg-bg text-fg p-6 max-w-5xl mx-auto">
      {/* Back nav */}
      <Link
        href="/workspaces"
        className="inline-flex items-center gap-1.5 text-sm text-fg-2 hover:text-fg mb-6 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" /> All Workspaces
      </Link>

      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-[var(--radius-md)] bg-accent-soft flex items-center justify-center">
            <Building2 className="h-5 w-5 text-accent-strong" />
          </div>
          {canManage && editingName && isOwner ? (
            <div className="flex items-center gap-2">
              <input
                autoFocus
                value={nameInput}
                onChange={(e) => setNameInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setEditingName(false) }}
                className="bg-surface-2 border border-line-2 rounded-[var(--radius-md)] px-3 py-1.5 text-lg font-semibold focus:outline-none focus:border-accent"
              />
              <button onClick={handleRename} className="text-ok hover:brightness-110"><Check className="h-4 w-4" /></button>
              <button onClick={() => setEditingName(false)} className="text-fg-3 hover:text-fg-2"><X className="h-4 w-4" /></button>
            </div>
          ) : canManage && isOwner ? (
            <button
              onClick={() => setEditingName(true)}
              className="text-2xl font-semibold hover:text-accent-strong cursor-pointer transition-colors"
              title="Click to rename"
            >
              {ws.name}
            </button>
          ) : <h1 className="text-2xl font-semibold">{ws.name}</h1>}
        </div>
        <div className="flex gap-4 text-sm text-fg-2">
          <span className="flex items-center gap-1"><Users className="h-3.5 w-3.5" />{ws.member_count}/{ws.max_members}</span>
          <span className="flex items-center gap-1"><FileText className="h-3.5 w-3.5" />{ws.resume_count} resumes</span>
          <span className="capitalize bg-surface-2 px-2 py-0.5 rounded text-xs">{ws.plan_id}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Members panel ──────────────────────────────────────────────────── */}
        <section className="bg-surface border border-line rounded-[var(--radius-lg)] p-5">
          <h2 className="text-sm font-semibold text-fg-2 mb-4 flex items-center gap-2">
            <Users className="h-4 w-4 text-accent-strong" /> Members
          </h2>

          <ul className="space-y-2 mb-4">
            {ws.members.map((m) => (
              <li key={m.user_id} className="flex items-center justify-between py-1.5">
                <div>
                  <p className="text-sm font-medium text-fg">{m.name ?? m.email ?? m.user_id}</p>
                  {m.name && <p className="text-xs text-fg-3">{m.email}</p>}
                </div>
                <div className="flex items-center gap-2">
                  {m.role === 'owner' ? (
                    <span className="text-xs text-accent-strong bg-accent-soft px-2 py-0.5 rounded">Owner</span>
                  ) : isOwner && (canManage || m.role === 'editor') ? (
                    <div className="relative group">
                      <button className="flex items-center gap-1 text-xs text-fg-2 bg-surface-2 hover:bg-surface px-2 py-0.5 rounded capitalize transition-colors">
                        {m.role} <ChevronDown className="h-3 w-3" />
                      </button>
                      <div className="absolute right-0 top-full mt-1 z-10 hidden group-focus-within:block bg-surface-2 border border-line rounded-[var(--radius-md)] shadow-[var(--shadow-2)] min-w-[100px]">
                        {(['editor', 'viewer'] as RoleOption[]).filter((role) => canManage || role === 'viewer').map((r) => (
                          <button
                            key={r}
                            onClick={() => handleRoleChange(m, r)}
                            className="block w-full text-left px-3 py-1.5 text-xs capitalize hover:bg-surface transition-colors"
                          >
                            {r}
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <span className="text-xs text-fg-3 capitalize">{m.role}</span>
                  )}
                  {isOwner && m.role !== 'owner' && (
                    <button
                      onClick={() => handleRemoveMember(m)}
                      className="text-fg-3 hover:text-err transition-colors"
                      title="Remove member"
                    >
                      <UserMinus className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>

          {/* Invite form (owner only) */}
          {canManage && isOwner && ws.member_count < ws.max_members && (
            <div className="border-t border-line pt-4">
              <p className="text-xs text-fg-3 mb-2">Invite by email</p>
              <div className="flex gap-2">
                <input
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleInvite()}
                  placeholder="colleague@company.com"
                  className="flex-1 bg-surface-2 border border-line rounded-[var(--radius-md)] px-3 py-1.5 text-sm focus:outline-none focus:border-accent"
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as RoleOption)}
                  className="bg-surface-2 border border-line rounded-[var(--radius-md)] px-2 py-1.5 text-sm focus:outline-none"
                >
                  <option value="editor">Editor</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button
                  onClick={handleInvite}
                  disabled={inviting || !inviteEmail.trim()}
                  className="px-3 py-1.5 bg-accent hover:brightness-110 text-accent-fg disabled:opacity-50 rounded-[var(--radius-md)] text-sm transition-colors"
                >
                  {inviting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                </button>
              </div>
            </div>
          )}

          {canManage && isOwner && ws.member_count >= ws.max_members && (
            <p className="text-xs text-warn mt-3">Member limit reached ({ws.max_members}/{ws.max_members})</p>
          )}
        </section>

        {/* ── Resumes panel ───────────────────────────────────────────────────── */}
        <section className="bg-surface border border-line rounded-[var(--radius-lg)] p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-fg-2 flex items-center gap-2">
              <FileText className="h-4 w-4 text-accent-strong" /> Shared Resumes
            </h2>
            {canManage && <button
              onClick={() => setShowAddResume((v) => !v)}
              className="flex items-center gap-1 text-xs text-accent-strong hover:brightness-110 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" /> Submit mine
            </button>}
          </div>

          {/* Resume picker */}
          {canManage && showAddResume && (
            <div className="mb-4 bg-surface-2 rounded-[var(--radius-md)] p-3 max-h-40 overflow-y-auto space-y-1">
              {unsharedResumes.length === 0 ? (
                <p className="text-xs text-fg-3">All your resumes are already shared here.</p>
              ) : (
                unsharedResumes.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => handleAddResume(r.id)}
                    className="w-full text-left text-xs px-2 py-1.5 hover:bg-surface rounded transition-colors text-fg-2"
                  >
                    {r.title}
                  </button>
                ))
              )}
            </div>
          )}

          {resumes.length === 0 ? (
            <p className="text-sm text-fg-3 py-4 text-center">No resumes shared yet.</p>
          ) : (
            <ul className="space-y-2">
              {resumes.map((r) => (
                <li key={r.id} className="flex items-center justify-between py-1.5">
                  <span className="text-sm text-fg-2 truncate flex-1 mr-2">{r.title}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    {r.owner_id === userId && (
                      <Link
                        href={`/workspace/${r.id}/edit`}
                        className="text-fg-3 hover:text-accent-strong transition-colors"
                        title="Open in editor"
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                      </Link>
                    )}
                    <button
                      onClick={() => handleDownloadResume(r.id, r.title)}
                      className="text-fg-3 hover:text-accent-strong transition-colors"
                      title="Download PDF"
                    >
                      <Download className="h-3.5 w-3.5" />
                    </button>
                    {(isOwner || r.owner_id === userId) && (
                      <button
                        onClick={() => handleRemoveResume(r.id, r.title)}
                        className="text-fg-3 hover:text-err transition-colors"
                        title="Remove from workspace"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  )
}
