'use client'

/**
 * Tenant Admin Dashboard — Feature 85E.
 *
 * Lets agency/career-center owners manage their white-label tenant:
 *  - Branding (name, logo URL, primary color)
 *  - Member management (invite by email, list, remove)
 *  - Custom domain + DNS TXT verification
 *  - Aggregate stats (members, resumes, compilations)
 */

import { useEffect, useState, useCallback } from 'react'
import { toast } from 'sonner'
import { apiClient, TenantResponse, MemberResponse, TenantStats, DomainVerifyResponse } from '@/lib/api-client'
import { applyTenantTheme } from '@/lib/tenant-theme'

// ── Minimal icon components ───────────────────────────────────────────────────

function Spinner() {
  return (
    <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-orange-300" />
  )
}

function Badge({ label, color = 'zinc' }: { label: string; color?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider
        ${color === 'orange' ? 'bg-orange-400/15 text-orange-300' : 'bg-zinc-800 text-zinc-400'}`}
    >
      {label}
    </span>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TenantAdminPage() {
  const [tenants, setTenants] = useState<TenantResponse[] | null>(null)
  const [selected, setSelected] = useState<TenantResponse | null>(null)
  const [members, setMembers] = useState<MemberResponse[]>([])
  const [stats, setStats] = useState<TenantStats | null>(null)
  const [dnsInfo, setDnsInfo] = useState<DomainVerifyResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')
  const [inviting, setInviting] = useState(false)

  // Branding form state
  const [name, setName] = useState('')
  const [logoUrl, setLogoUrl] = useState('')
  const [primaryColor, setPrimaryColor] = useState('#6d28d9')
  const [customDomain, setCustomDomain] = useState('')

  // Create-tenant form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [creating, setCreating] = useState(false)

  const loadTenants = useCallback(async () => {
    try {
      const data = await apiClient.listMyTenants()
      setTenants(data)
      if (data.length > 0 && !selected) {
        selectTenant(data[0])
      }
    } catch {
      toast.error('Failed to load tenants')
    } finally {
      setLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadTenants()
  }, [loadTenants])

  const selectTenant = useCallback(async (tenant: TenantResponse) => {
    setSelected(tenant)
    setName(tenant.name)
    setLogoUrl(tenant.logo_url ?? '')
    setPrimaryColor(tenant.primary_color ?? '#6d28d9')
    setCustomDomain(tenant.custom_domain ?? '')
    setDnsInfo(null)

    try {
      const [m, s] = await Promise.all([
        apiClient.listTenantMembers(tenant.id),
        apiClient.getTenantStats(tenant.id),
      ])
      setMembers(m)
      setStats(s)
    } catch {
      toast.error('Failed to load tenant data')
    }
  }, [])

  const saveBranding = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = await apiClient.updateTenant(selected.id, {
        name: name || undefined,
        logo_url: logoUrl || null,
        primary_color: primaryColor || null,
        custom_domain: customDomain || null,
      })
      setSelected(updated)
      setTenants((prev) => prev?.map((t) => (t.id === updated.id ? updated : t)) ?? null)
      applyTenantTheme({
        ...updated,
        logo_url: updated.logo_url ?? null,
        primary_color: updated.primary_color ?? null,
        custom_domain: updated.custom_domain ?? null,
      })
      toast.success('Branding saved')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to save branding')
    } finally {
      setSaving(false)
    }
  }

  const invite = async () => {
    if (!selected || !inviteEmail.trim()) return
    setInviting(true)
    try {
      const member = await apiClient.inviteTenantMember(selected.id, inviteEmail.trim(), inviteRole)
      setMembers((prev) => [...prev, member])
      setInviteEmail('')
      toast.success(`${member.email} added as ${member.role}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to invite member')
    } finally {
      setInviting(false)
    }
  }

  const removeMember = async (userId: string) => {
    if (!selected) return
    try {
      await apiClient.removeTenantMember(selected.id, userId)
      setMembers((prev) => prev.filter((m) => m.user_id !== userId))
      toast.success('Member removed')
    } catch {
      toast.error('Failed to remove member')
    }
  }

  const verifyDomain = async () => {
    if (!selected) return
    try {
      const info = await apiClient.verifyTenantDomain(selected.id)
      setDnsInfo(info)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to fetch DNS instructions')
    }
  }

  const createTenant = async () => {
    if (!newName.trim() || !newSlug.trim()) return
    setCreating(true)
    try {
      const tenant = await apiClient.createTenant({ name: newName, slug: newSlug })
      setTenants((prev) => [...(prev ?? []), tenant])
      setShowCreate(false)
      setNewName('')
      setNewSlug('')
      await selectTenant(tenant)
      toast.success(`Tenant "${tenant.name}" created`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to create tenant')
    } finally {
      setCreating(false)
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner />
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 space-y-10">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">Admin</p>
          <h1 className="mt-1 text-xl font-semibold text-white">Tenant Management</h1>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-orange-500/20 px-4 py-2 text-sm font-medium text-orange-300 transition hover:bg-orange-500/30"
        >
          + New Tenant
        </button>
      </div>

      {/* Create tenant modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm rounded-2xl border border-white/10 bg-zinc-950 p-6 shadow-2xl">
            <h2 className="mb-5 text-base font-semibold text-white">Create New Tenant</h2>
            <div className="space-y-3">
              <input
                type="text"
                placeholder="Tenant name (e.g. Acme Recruiting)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
              />
              <input
                type="text"
                placeholder="Slug (e.g. acme-recruiting)"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                className="w-full rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
              />
              <p className="text-[11px] text-zinc-600">
                Access URL: <span className="text-zinc-400">{newSlug || 'your-slug'}.latexy.io</span>
              </p>
            </div>
            <div className="mt-5 flex gap-3">
              <button
                onClick={() => setShowCreate(false)}
                className="flex-1 rounded-lg border border-white/10 py-2 text-sm text-zinc-400 transition hover:text-white"
              >
                Cancel
              </button>
              <button
                onClick={createTenant}
                disabled={creating || !newName.trim() || !newSlug.trim()}
                className="flex-1 rounded-lg bg-orange-500/20 py-2 text-sm font-medium text-orange-300 transition hover:bg-orange-500/30 disabled:opacity-40"
              >
                {creating ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tenant selector */}
      {tenants && tenants.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tenants.map((t) => (
            <button
              key={t.id}
              onClick={() => selectTenant(t)}
              className={`rounded-full border px-4 py-1.5 text-sm transition ${
                selected?.id === t.id
                  ? 'border-orange-400/40 bg-orange-400/10 text-orange-200'
                  : 'border-white/10 bg-zinc-900 text-zinc-400 hover:text-white'
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="rounded-xl border border-white/[0.07] bg-zinc-900/60 px-6 py-12 text-center text-zinc-500">
          No tenants yet. Create one to get started.
        </div>
      )}

      {selected && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left column — stats */}
          <div className="space-y-4 lg:col-span-1">
            {/* Stats cards */}
            <div className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-zinc-600">Stats</p>
              {stats ? (
                <div className="space-y-3">
                  {[
                    { label: 'Members', value: stats.member_count },
                    { label: 'Resumes', value: stats.total_resumes },
                    { label: 'Compilations', value: stats.total_compilations },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-sm text-zinc-500">{label}</span>
                      <span className="text-sm font-semibold text-white">{value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex justify-center py-4"><Spinner /></div>
              )}
            </div>

            {/* Tenant meta */}
            <div className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5 space-y-2">
              <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">Info</p>
              <div className="text-sm text-zinc-400">
                <span className="text-zinc-600">Slug: </span>{selected.slug}
              </div>
              <div className="text-sm text-zinc-400">
                <span className="text-zinc-600">Plan: </span>
                <Badge label={selected.plan_id} color="orange" />
              </div>
              <div className="text-sm text-zinc-400">
                <span className="text-zinc-600">Max members: </span>{selected.max_members}
              </div>
            </div>
          </div>

          {/* Right column — branding + members + domain */}
          <div className="space-y-6 lg:col-span-2">
            {/* Branding */}
            <section className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-zinc-600">Branding</p>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Tenant name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Logo URL</label>
                  <input
                    type="url"
                    value={logoUrl}
                    onChange={(e) => setLogoUrl(e.target.value)}
                    placeholder="https://example.com/logo.png"
                    className="w-full rounded-lg border border-white/10 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
                  />
                  {logoUrl && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={logoUrl} alt="Logo preview" className="mt-2 h-10 rounded object-contain" />
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs text-zinc-500">Primary color</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="color"
                      value={primaryColor}
                      onChange={(e) => setPrimaryColor(e.target.value)}
                      className="h-9 w-14 cursor-pointer rounded border border-white/10 bg-transparent"
                    />
                    <span className="font-mono text-sm text-zinc-400">{primaryColor}</span>
                    <span
                      className="h-6 w-6 rounded-full border border-white/10"
                      style={{ background: primaryColor }}
                    />
                  </div>
                </div>
                <button
                  onClick={saveBranding}
                  disabled={saving}
                  className="w-full rounded-lg bg-orange-500/20 py-2 text-sm font-medium text-orange-300 transition hover:bg-orange-500/30 disabled:opacity-40"
                >
                  {saving ? 'Saving…' : 'Save Branding'}
                </button>
              </div>
            </section>

            {/* Custom domain */}
            <section className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-zinc-600">Custom Domain</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="resumes.acme.com"
                  className="flex-1 rounded-lg border border-white/10 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
                />
                <button
                  onClick={verifyDomain}
                  disabled={!selected.custom_domain && !customDomain}
                  className="rounded-lg border border-white/10 px-4 py-2 text-sm text-zinc-400 transition hover:text-white disabled:opacity-30"
                >
                  DNS Setup
                </button>
              </div>

              {dnsInfo && (
                <div className="mt-4 rounded-lg border border-white/[0.07] bg-zinc-950/60 p-4 space-y-2 text-xs text-zinc-400">
                  <p className="font-medium text-zinc-200">Add this DNS TXT record:</p>
                  <div>
                    <span className="text-zinc-600">Name: </span>
                    <code className="text-orange-300">{dnsInfo.txt_record_name}</code>
                  </div>
                  <div>
                    <span className="text-zinc-600">Value: </span>
                    <code className="text-orange-300">{dnsInfo.txt_record_value}</code>
                  </div>
                  <p className="text-zinc-600 leading-relaxed">{dnsInfo.instructions}</p>
                </div>
              )}
            </section>

            {/* Member management */}
            <section className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-zinc-600">
                Members ({members.length} / {selected.max_members})
              </p>

              {/* Invite */}
              <div className="mb-4 flex gap-2">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@example.com"
                  onKeyDown={(e) => e.key === 'Enter' && invite()}
                  className="flex-1 rounded-lg border border-white/10 bg-zinc-800 px-3 py-2 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-orange-400/40"
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
                  className="rounded-lg border border-white/10 bg-zinc-800 px-2 py-2 text-sm text-zinc-300 focus:outline-none"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  onClick={invite}
                  disabled={inviting || !inviteEmail.trim()}
                  className="rounded-lg bg-orange-500/20 px-4 py-2 text-sm font-medium text-orange-300 transition hover:bg-orange-500/30 disabled:opacity-40"
                >
                  {inviting ? '…' : 'Invite'}
                </button>
              </div>

              {/* Member list */}
              <div className="space-y-2">
                {members.length === 0 && (
                  <p className="text-sm text-zinc-600">No members yet.</p>
                )}
                {members.map((m) => (
                  <div
                    key={m.user_id}
                    className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-zinc-800/40 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-zinc-200">{m.name || m.email}</p>
                      {m.name && (
                        <p className="truncate text-xs text-zinc-500">{m.email}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge label={m.role} color={m.role === 'admin' ? 'orange' : 'zinc'} />
                      <button
                        onClick={() => removeMember(m.user_id)}
                        className="text-xs text-zinc-600 transition hover:text-red-400"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
