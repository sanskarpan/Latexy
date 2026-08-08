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
    <div className="h-5 w-5 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
  )
}

function Badge({ label, color = 'zinc' }: { label: string; color?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider
        ${color === 'orange' ? 'bg-accent-soft text-accent-strong' : 'bg-surface-2 text-fg-2'}`}
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
          <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Admin</p>
          <h1 className="mt-1 text-xl font-semibold text-fg">Tenant Management</h1>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong transition hover:brightness-110"
        >
          + New Tenant
        </button>
      </div>

      {/* Create tenant modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]">
          <div className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-bg p-6 shadow-[var(--shadow-2)]">
            <h2 className="mb-5 text-base font-semibold text-fg">Create New Tenant</h2>
            <div className="space-y-3">
              <input
                type="text"
                placeholder="Tenant name (e.g. Acme Recruiting)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <input
                type="text"
                placeholder="Slug (e.g. acme-recruiting)"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <p className="text-[11px] text-fg-3">
                Access URL: <span className="text-fg-2">{newSlug || 'your-slug'}.latexy.io</span>
              </p>
            </div>
            <div className="mt-5 flex gap-3">
              <button
                onClick={() => setShowCreate(false)}
                className="flex-1 rounded-[var(--radius-md)] border border-line py-2 text-sm text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                onClick={createTenant}
                disabled={creating || !newName.trim() || !newSlug.trim()}
                className="flex-1 rounded-[var(--radius-md)] bg-accent-soft py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
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
                  ? 'border-accent bg-accent-soft text-accent-strong'
                  : 'border-line bg-surface text-fg-2 hover:text-fg'
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface px-6 py-12 text-center text-fg-3">
          No tenants yet. Create one to get started.
        </div>
      )}

      {selected && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left column — stats */}
          <div className="space-y-4 lg:col-span-1">
            {/* Stats cards */}
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Stats</p>
              {stats ? (
                <div className="space-y-3">
                  {[
                    { label: 'Members', value: stats.member_count },
                    { label: 'Resumes', value: stats.total_resumes },
                    { label: 'Compilations', value: stats.total_compilations },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-sm text-fg-3">{label}</span>
                      <span className="text-sm font-semibold text-fg">{value}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="flex justify-center py-4"><Spinner /></div>
              )}
            </div>

            {/* Tenant meta */}
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 space-y-2">
              <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Info</p>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Slug: </span>{selected.slug}
              </div>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Plan: </span>
                <Badge label={selected.plan_id} color="orange" />
              </div>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Max members: </span>{selected.max_members}
              </div>
            </div>
          </div>

          {/* Right column — branding + members + domain */}
          <div className="space-y-6 lg:col-span-2">
            {/* Branding */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Branding</p>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Tenant name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Logo URL</label>
                  <input
                    type="url"
                    value={logoUrl}
                    onChange={(e) => setLogoUrl(e.target.value)}
                    placeholder="https://example.com/logo.png"
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  {logoUrl && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={logoUrl} alt="Logo preview" className="mt-2 h-10 rounded object-contain" />
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Primary color</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="color"
                      value={primaryColor}
                      onChange={(e) => setPrimaryColor(e.target.value)}
                      className="h-9 w-14 cursor-pointer rounded border border-line bg-transparent"
                    />
                    <span className="font-mono text-sm text-fg-2">{primaryColor}</span>
                    <span
                      className="h-6 w-6 rounded-full border border-line"
                      style={{ background: primaryColor }}
                    />
                  </div>
                </div>
                <button
                  onClick={saveBranding}
                  disabled={saving}
                  className="w-full rounded-[var(--radius-md)] bg-accent-soft py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
                >
                  {saving ? 'Saving…' : 'Save Branding'}
                </button>
              </div>
            </section>

            {/* Custom domain */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Custom Domain</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="resumes.acme.com"
                  className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <button
                  onClick={verifyDomain}
                  disabled={!selected.custom_domain && !customDomain}
                  className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2 transition hover:text-fg disabled:opacity-30"
                >
                  DNS Setup
                </button>
              </div>

              {dnsInfo && (
                <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-bg p-4 space-y-2 text-xs text-fg-2">
                  <p className="font-medium text-fg">Add this DNS TXT record:</p>
                  <div>
                    <span className="text-fg-3">Name: </span>
                    <code className="text-accent-strong">{dnsInfo.txt_record_name}</code>
                  </div>
                  <div>
                    <span className="text-fg-3">Value: </span>
                    <code className="text-accent-strong">{dnsInfo.txt_record_value}</code>
                  </div>
                  <p className="text-fg-3 leading-relaxed">{dnsInfo.instructions}</p>
                </div>
              )}
            </section>

            {/* Member management */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">
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
                  className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
                  className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-2 text-sm text-fg-2 focus:outline-none"
                >
                  <option value="member">Member</option>
                  <option value="admin">Admin</option>
                </select>
                <button
                  onClick={invite}
                  disabled={inviting || !inviteEmail.trim()}
                  className="rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
                >
                  {inviting ? 'Inviting…' : 'Invite'}
                </button>
              </div>

              {/* Member list */}
              <div className="space-y-2">
                {members.length === 0 && (
                  <p className="text-sm text-fg-3">No members yet.</p>
                )}
                {members.map((m) => (
                  <div
                    key={m.user_id}
                    className="flex items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-fg">{m.name || m.email}</p>
                      {m.name && (
                        <p className="truncate text-xs text-fg-3">{m.email}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge label={m.role} color={m.role === 'admin' ? 'orange' : 'zinc'} />
                      <button
                        onClick={() => removeMember(m.user_id)}
                        className="text-xs text-fg-3 transition hover:text-err"
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
