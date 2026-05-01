'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { Users, Plus, Loader2, Building2, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type WorkspaceResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function WorkspacesPage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const [workspaces, setWorkspaces] = useState<WorkspaceResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  useEffect(() => {
    if (!session?.user) return
    apiClient
      .listWorkspaces()
      .then(setWorkspaces)
      .catch(() => toast.error('Failed to load workspaces'))
      .finally(() => setLoading(false))
  }, [session])

  async function handleCreate() {
    const name = newName.trim()
    if (!name) return
    setCreating(true)
    try {
      const ws = await apiClient.createWorkspace(name)
      setWorkspaces((prev) => [ws, ...prev])
      setNewName('')
      setShowCreate(false)
      toast.success(`Workspace "${ws.name}" created`)
    } catch {
      toast.error('Failed to create workspace')
    } finally {
      setCreating(false)
    }
  }

  async function handleDelete(ws: WorkspaceResponse) {
    if (!confirm(`Delete workspace "${ws.name}"? This cannot be undone.`)) return
    try {
      await apiClient.deleteWorkspace(ws.id)
      setWorkspaces((prev) => prev.filter((w) => w.id !== ws.id))
      toast.success('Workspace deleted')
    } catch {
      toast.error('Failed to delete workspace')
    }
  }

  if (sessionLoading || loading) return <LoadingSpinner />
  if (!session?.user) return null

  const userId = session.user.id

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div className="flex items-center gap-3">
          <Building2 className="h-6 w-6 text-violet-400" />
          <h1 className="text-2xl font-semibold">Team Workspaces</h1>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-500 rounded-lg text-sm font-medium transition-colors"
        >
          <Plus className="h-4 w-4" />
          New Workspace
        </button>
      </div>

      {/* Create form */}
      {showCreate && (
        <div className="mb-6 p-4 bg-zinc-900 border border-zinc-700 rounded-xl">
          <p className="text-sm font-medium text-zinc-300 mb-3">Workspace name</p>
          <div className="flex gap-3">
            <input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleCreate()}
              placeholder="e.g. Engineering Team"
              className="flex-1 bg-zinc-800 border border-zinc-600 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-violet-500"
            />
            <button
              onClick={handleCreate}
              disabled={creating || !newName.trim()}
              className="px-4 py-2 bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg text-sm font-medium transition-colors"
            >
              {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Create'}
            </button>
            <button
              onClick={() => { setShowCreate(false); setNewName('') }}
              className="px-3 py-2 text-zinc-400 hover:text-zinc-200 text-sm transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Workspace grid */}
      {workspaces.length === 0 ? (
        <div className="text-center py-20 text-zinc-500">
          <Building2 className="h-12 w-12 mx-auto mb-4 opacity-30" />
          <p className="text-lg mb-1">No workspaces yet</p>
          <p className="text-sm">Create a workspace to collaborate with your team.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {workspaces.map((ws) => (
            <div
              key={ws.id}
              className="group relative bg-zinc-900 border border-zinc-800 hover:border-zinc-600 rounded-xl p-5 transition-colors"
            >
              <Link href={`/workspaces/${ws.id}`} className="block">
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="h-9 w-9 rounded-lg bg-violet-500/20 flex items-center justify-center">
                      <Building2 className="h-4 w-4 text-violet-400" />
                    </div>
                    <div>
                      <p className="font-medium text-zinc-100">{ws.name}</p>
                      <p className="text-xs text-zinc-500 capitalize">{ws.plan_id} plan</p>
                    </div>
                  </div>
                </div>

                <div className="flex gap-4 text-sm text-zinc-400">
                  <span className="flex items-center gap-1">
                    <Users className="h-3.5 w-3.5" />
                    {ws.member_count}/{ws.max_members} members
                  </span>
                  <span>{ws.resume_count} resumes</span>
                </div>
              </Link>

              {/* Delete button — only for owner */}
              {ws.owner_id === userId && (
                <button
                  onClick={(e) => { e.preventDefault(); handleDelete(ws) }}
                  className="absolute top-3 right-3 p-1.5 opacity-0 group-hover:opacity-100 text-zinc-500 hover:text-rose-400 transition-all"
                  title="Delete workspace"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
