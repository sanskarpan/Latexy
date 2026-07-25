'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  apiClient,
  type AdminEntitlementsState,
  type AdminUser,
  type UserRole,
} from '@/lib/api-client'
import { JobQueue } from '@/components/JobQueue'

interface FlagDetail {
  key: string
  enabled: boolean
  label: string
  description: string | null
  updated_at: string | null
}

type TabId = 'flags' | 'matrix' | 'users'

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'flags', label: 'Feature Flags' },
  { id: 'matrix', label: 'Features × Plans' },
  { id: 'users', label: 'Users & Roles' },
]

// ── Shared toggle switch ──────────────────────────────────────────────────────

function Switch({
  enabled,
  onClick,
  disabled,
  busy,
  label,
}: {
  enabled: boolean
  onClick: () => void
  disabled?: boolean
  busy?: boolean
  label: string
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={enabled}
      aria-label={label}
      onClick={onClick}
      disabled={disabled || busy}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300/60 disabled:cursor-not-allowed disabled:opacity-50 ${
        enabled
          ? 'border-orange-400/40 bg-orange-400/20'
          : 'border-white/10 bg-white/[0.04]'
      }`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full transition duration-200 ${
          enabled ? 'translate-x-5 bg-orange-300' : 'translate-x-0.5 bg-zinc-600'
        }`}
      />
    </button>
  )
}

// ── Tab 1: operational feature flags (existing behaviour, preserved) ──────────

function FeatureFlagsTab() {
  const [flags, setFlags] = useState<FlagDetail[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<string | null>(null)

  useEffect(() => {
    apiClient
      .getAdminFeatureFlags()
      .then((data) => setFlags(data))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg || 'Failed to load feature flags')
      })
      .finally(() => setLoading(false))
  }, [])

  const toggle = async (key: string, currentEnabled: boolean) => {
    setUpdating(key)
    try {
      const updated = await apiClient.updateFeatureFlag(key, !currentEnabled)
      setFlags((prev) =>
        prev?.map((f) => (f.key === key ? { ...f, enabled: updated.enabled } : f)) ?? null,
      )
      toast.success(`${updated.label} ${updated.enabled ? 'enabled' : 'disabled'}`)
    } catch {
      toast.error('Failed to update flag')
    } finally {
      setUpdating(null)
    }
  }

  if (loading) return <RowsSkeleton rows={6} />
  if (error) return <InlineError message={error} />

  return (
    <div className="space-y-3">
      {flags?.map((flag) => (
        <div
          key={flag.key}
          className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-zinc-900/60 px-5 py-4"
        >
          <div className="min-w-0 flex-1 pr-6">
            <p className="text-sm font-medium text-zinc-100">{flag.label}</p>
            {flag.description && <p className="mt-0.5 text-xs text-zinc-500">{flag.description}</p>}
            {flag.updated_at && (
              <p className="mt-1 text-[10px] text-zinc-700">
                {new Date(flag.updated_at).toLocaleString()}
              </p>
            )}
          </div>
          <Switch
            enabled={flag.enabled}
            busy={updating === flag.key}
            onClick={() => toggle(flag.key, flag.enabled)}
            label={`Toggle ${flag.label}`}
          />
        </div>
      ))}
    </div>
  )
}

// ── Tab 2: features × plans matrix ────────────────────────────────────────────

const CATEGORY_ORDER = ['core', 'editor', 'career', 'advanced', 'integrations', 'analytics']

function categoryLabel(cat: string): string {
  return cat.charAt(0).toUpperCase() + cat.slice(1)
}

function MatrixTab() {
  const [state, setState] = useState<AdminEntitlementsState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  // Cells with an in-flight request. key = `${scope}:${featureKey}` where scope
  // is 'global' or a plan family. A Set lets multiple cells be in flight at once
  // without one toggle clobbering another's busy state.
  const [busyCells, setBusyCells] = useState<ReadonlySet<string>>(() => new Set())
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    apiClient
      .getAdminEntitlements()
      .then((data) => {
        if (mounted.current) setState(data)
      })
      .catch((err: unknown) => {
        if (mounted.current) setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (mounted.current) setLoading(false)
      })
  }, [])

  const markBusy = useCallback((cellId: string) => {
    setBusyCells((cur) => {
      const next = new Set(cur)
      next.add(cellId)
      return next
    })
  }, [])

  const clearBusy = useCallback((cellId: string) => {
    setBusyCells((cur) => {
      if (!cur.has(cellId)) return cur
      const next = new Set(cur)
      next.delete(cellId)
      return next
    })
  }, [])

  const grouped = useMemo(() => {
    if (!state) return []
    const byCat = new Map<string, AdminEntitlementsState['registry']>()
    for (const feat of state.registry) {
      const list = byCat.get(feat.category) ?? []
      list.push(feat)
      byCat.set(feat.category, list)
    }
    const cats = [...byCat.keys()].sort((a, b) => {
      const ai = CATEGORY_ORDER.indexOf(a)
      const bi = CATEGORY_ORDER.indexOf(b)
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi)
    })
    return cats.map((cat) => ({ category: cat, features: byCat.get(cat)! }))
  }, [state])

  // Functional patch helpers so every write builds off the *latest* state,
  // never a value captured in the handler's closure. This is what prevents
  // concurrent toggles from clobbering each other.
  const patchKillSwitch = useCallback(
    (cur: AdminEntitlementsState | null, featureKey: string, value: boolean) =>
      cur
        ? { ...cur, kill_switches: { ...cur.kill_switches, [featureKey]: value } }
        : cur,
    [],
  )

  const patchMatrixCell = useCallback(
    (
      cur: AdminEntitlementsState | null,
      family: string,
      featureKey: string,
      value: boolean,
    ) =>
      cur
        ? {
            ...cur,
            matrix: {
              ...cur.matrix,
              [family]: { ...(cur.matrix[family] ?? {}), [featureKey]: value },
            },
          }
        : cur,
    [],
  )

  const toggleGlobal = useCallback(
    async (featureKey: string, next: boolean) => {
      const cellId = `global:${featureKey}`
      // optimistic — functional so it merges with any other in-flight change
      setState((cur) => patchKillSwitch(cur, featureKey, next))
      markBusy(cellId)
      try {
        const fresh = await apiClient.updateKillSwitch(featureKey, next)
        if (!mounted.current) return
        // Apply only the authoritative value for *this* cell, keeping any other
        // in-flight optimistic edits rather than overwriting the whole grid.
        setState((cur) => patchKillSwitch(cur, featureKey, fresh.kill_switches[featureKey] ?? next))
      } catch {
        if (!mounted.current) return
        // Roll back only this cell, functionally, so a concurrent toggle's
        // optimistic change survives.
        setState((cur) => patchKillSwitch(cur, featureKey, !next))
        toast.error('Failed to update kill-switch')
      } finally {
        clearBusy(cellId)
      }
    },
    [patchKillSwitch, markBusy, clearBusy],
  )

  const toggleCell = useCallback(
    async (family: string, featureKey: string, next: boolean) => {
      const cellId = `${family}:${featureKey}`
      setState((cur) => patchMatrixCell(cur, family, featureKey, next))
      markBusy(cellId)
      try {
        const fresh = await apiClient.updateMatrixCell(family, featureKey, next)
        if (!mounted.current) return
        setState((cur) =>
          patchMatrixCell(cur, family, featureKey, fresh.matrix[family]?.[featureKey] ?? next),
        )
      } catch {
        if (!mounted.current) return
        setState((cur) => patchMatrixCell(cur, family, featureKey, !next))
        toast.error('Failed to update plan access')
      } finally {
        clearBusy(cellId)
      }
    },
    [patchMatrixCell, markBusy, clearBusy],
  )

  if (loading) return <RowsSkeleton rows={8} />
  if (error) return <InlineError message={error} />
  if (!state) return null

  const families = state.plan_families

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.07] bg-zinc-900/40">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="sticky top-0 z-20 bg-zinc-950/95 backdrop-blur">
              <th className="sticky left-0 z-30 w-[160px] min-w-[160px] bg-zinc-950/95 px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-zinc-400">
                Feature
              </th>
              <th className="min-w-[68px] px-3 py-3 text-center text-[11px] font-semibold uppercase tracking-wider text-orange-200/80">
                Global
              </th>
              {families.map((fam) => (
                <th
                  key={fam}
                  className="min-w-[68px] px-3 py-3 text-center text-[11px] font-semibold uppercase tracking-wider text-zinc-400"
                >
                  {fam}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {grouped.map(({ category, features }) => (
              <FragmentGroup
                key={category}
                category={category}
                colSpan={families.length + 2}
                features={features}
                state={state}
                families={families}
                busyCells={busyCells}
                onToggleGlobal={toggleGlobal}
                onToggleCell={toggleCell}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="border-t border-white/[0.07] px-4 py-3 text-[11px] text-zinc-600">
        Launch default is everything on. A <span className="text-orange-200/80">Global</span>{' '}
        kill-switch off disables the feature for every plan. Non-gateable core features are always on.
      </p>
    </div>
  )
}

function FragmentGroup({
  category,
  colSpan,
  features,
  state,
  families,
  busyCells,
  onToggleGlobal,
  onToggleCell,
}: {
  category: string
  colSpan: number
  features: AdminEntitlementsState['registry']
  state: AdminEntitlementsState
  families: string[]
  busyCells: ReadonlySet<string>
  onToggleGlobal: (featureKey: string, next: boolean) => void
  onToggleCell: (family: string, featureKey: string, next: boolean) => void
}) {
  return (
    <>
      <tr>
        <th
          colSpan={colSpan}
          scope="colgroup"
          className="sticky left-0 bg-zinc-900/80 px-4 py-2 text-left text-[10px] font-semibold uppercase tracking-[0.2em] text-zinc-500"
        >
          {categoryLabel(category)}
        </th>
      </tr>
      {features.map((feat, idx) => {
        const globalOn = state.kill_switches[feat.key] ?? true
        const rowDisabled = feat.gateable && !globalOn
        return (
          <tr
            key={feat.key}
            className={`group border-t border-white/[0.04] transition-colors hover:bg-white/[0.02] ${
              idx % 2 === 1 ? 'bg-white/[0.012]' : ''
            } ${rowDisabled ? 'opacity-50' : ''}`}
          >
            <td className="sticky left-0 z-10 w-[160px] min-w-[160px] bg-zinc-900/60 px-4 py-3 group-hover:bg-zinc-900/80">
              <div className="flex items-center gap-2">
                <span className="text-sm text-zinc-200">{feat.label}</span>
                {!feat.gateable && (
                  <span className="rounded bg-emerald-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-300/80">
                    always on
                  </span>
                )}
              </div>
              <span className="text-[10px] text-zinc-600">{feat.key}</span>
            </td>

            {/* Global kill-switch */}
            <td className="px-3 py-3 text-center">
              {feat.gateable ? (
                <div className="inline-flex min-h-[40px] items-center justify-center px-1">
                  <Switch
                    enabled={globalOn}
                    busy={busyCells.has(`global:${feat.key}`)}
                    onClick={() => onToggleGlobal(feat.key, !globalOn)}
                    label={`${feat.label} global kill-switch`}
                  />
                </div>
              ) : (
                <AlwaysOnDot />
              )}
            </td>

            {/* Per-plan cells */}
            {families.map((fam) => {
              const cellOn = state.matrix[fam]?.[feat.key] ?? true
              if (!feat.gateable) {
                return (
                  <td key={fam} className="px-3 py-3 text-center">
                    <AlwaysOnDot />
                  </td>
                )
              }
              return (
                <td key={fam} className="px-3 py-3 text-center">
                  <div className="inline-flex min-h-[40px] items-center justify-center px-1">
                    <Switch
                      enabled={cellOn}
                      disabled={rowDisabled}
                      busy={busyCells.has(`${fam}:${feat.key}`)}
                      onClick={() => onToggleCell(fam, feat.key, !cellOn)}
                      label={`${feat.label} for ${fam}`}
                    />
                  </div>
                </td>
              )
            })}
          </tr>
        )
      })}
    </>
  )
}

function AlwaysOnDot() {
  return (
    <span
      title="Always on"
      className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-400/70 align-middle"
      aria-label="Always on"
    />
  )
}

// ── Tab 3: users & roles ──────────────────────────────────────────────────────

const ROLES: UserRole[] = ['user', 'support', 'admin']
const PAGE_SIZE = 20

function UsersTab() {
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [users, setUsers] = useState<AdminUser[] | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<string | null>(null)

  // debounce the search box → resets pagination
  useEffect(() => {
    const t = setTimeout(() => {
      setDebounced(query.trim())
      setOffset(0)
    }, 300)
    return () => clearTimeout(t)
  }, [query])

  useEffect(() => {
    // `stale` guards against out-of-order responses: if the query/offset changes
    // (or the component unmounts) before this request resolves, its result is
    // discarded so the latest request always wins.
    let stale = false
    setLoading(true)
    setError(null)
    apiClient
      .getAdminUsers({ q: debounced || undefined, limit: PAGE_SIZE, offset })
      .then((data) => {
        if (stale) return
        setUsers(data.users)
        setTotal(data.total)
      })
      .catch((err: unknown) => {
        if (stale) return
        setError(err instanceof Error ? err.message : String(err))
      })
      .finally(() => {
        if (!stale) setLoading(false)
      })
    return () => {
      stale = true
    }
  }, [debounced, offset])

  const changeRole = async (user: AdminUser, role: UserRole) => {
    if (role === user.role) return
    setSavingId(user.id)
    try {
      const updated = await apiClient.updateUserRole(user.id, role)
      setUsers((prev) => prev?.map((u) => (u.id === user.id ? updated : u)) ?? null)
      toast.success(`${updated.email} is now ${updated.role}`)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('409') || msg.includes('last_admin')) {
        toast.error('Cannot demote the last remaining admin.')
      } else {
        toast.error('Failed to update role')
      }
    } finally {
      setSavingId(null)
    }
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div>
      <div className="mb-4">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by email or name…"
          aria-label="Search users"
          className="w-full rounded-lg border border-white/10 bg-zinc-900/60 px-4 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-orange-400/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300/40 sm:max-w-sm"
        />
      </div>

      {loading ? (
        <RowsSkeleton rows={6} />
      ) : error ? (
        <InlineError message={error} />
      ) : !users || users.length === 0 ? (
        <div className="rounded-xl border border-white/[0.07] bg-zinc-900/40 px-6 py-16 text-center">
          <p className="text-sm font-medium text-zinc-300">No users found</p>
          <p className="mt-1 text-xs text-zinc-600">
            {debounced ? `No matches for “${debounced}”.` : 'No users to display.'}
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-white/[0.07] bg-zinc-900/40">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-white/[0.07] text-[11px] uppercase tracking-wider text-zinc-500">
                  <th className="min-w-[220px] px-4 py-3 text-left font-semibold">User</th>
                  <th className="min-w-[90px] px-4 py-3 text-left font-semibold">Plan</th>
                  <th className="min-w-[130px] px-4 py-3 text-left font-semibold">Role</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u, idx) => (
                  <tr
                    key={u.id}
                    className={`border-t border-white/[0.04] ${idx % 2 === 1 ? 'bg-white/[0.012]' : ''}`}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium text-zinc-100">{u.email}</span>
                        {u.email_verified && (
                          <span
                            title="Email verified"
                            className="rounded bg-emerald-400/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-emerald-300/80"
                          >
                            verified
                          </span>
                        )}
                      </div>
                      {u.name && <p className="mt-0.5 text-xs text-zinc-600">{u.name}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded-md border border-white/[0.07] bg-white/[0.03] px-2 py-0.5 text-xs text-zinc-400">
                        {u.subscription_plan ?? 'free'}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={u.role}
                        disabled={savingId === u.id}
                        onChange={(e) => changeRole(u, e.target.value as UserRole)}
                        aria-label={`Role for ${u.email}`}
                        className="min-h-[40px] rounded-lg border border-white/10 bg-zinc-900 px-3 py-2 text-sm text-zinc-200 focus:border-orange-400/40 focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300/40 disabled:opacity-50"
                      >
                        {ROLES.map((r) => (
                          <option key={r} value={r}>
                            {r}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-between border-t border-white/[0.07] px-4 py-3">
            <p className="text-xs text-zinc-600">
              {total} user{total === 1 ? '' : 's'} · page {page} of {pageCount}
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                disabled={offset === 0}
                className="rounded-lg border border-white/10 px-3 py-1 text-xs font-medium text-zinc-300 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                Previous
              </button>
              <button
                onClick={() => setOffset((o) => o + PAGE_SIZE)}
                disabled={offset + PAGE_SIZE >= total}
                className="rounded-lg border border-white/10 px-3 py-1 text-xs font-medium text-zinc-300 transition hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Shared UI bits ────────────────────────────────────────────────────────────

function RowsSkeleton({ rows }: { rows: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div
          key={i}
          className="h-16 animate-pulse rounded-xl border border-white/[0.05] bg-zinc-900/40"
        />
      ))}
    </div>
  )
}

function InlineError({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-rose-500/20 bg-rose-500/[0.06] px-5 py-4">
      <p className="text-sm font-medium text-rose-200">Failed to load</p>
      <p className="mt-1 text-xs text-rose-300/70">{message}</p>
    </div>
  )
}

// ── Page shell ────────────────────────────────────────────────────────────────

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>('flags')
  const [forbidden, setForbidden] = useState(false)
  const [checking, setChecking] = useState(true)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  // Probe authorization once via the flags endpoint (already admin-gated).
  useEffect(() => {
    apiClient
      .getAdminFeatureFlags()
      .then(() => setForbidden(false))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('403') || msg.includes('Forbidden')) setForbidden(true)
      })
      .finally(() => setChecking(false))
  }, [])

  const onTabKeyDown = (e: React.KeyboardEvent, index: number) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    e.preventDefault()
    const dir = e.key === 'ArrowRight' ? 1 : -1
    const next = (index + dir + TABS.length) % TABS.length
    setTab(TABS[next].id)
    tabRefs.current[next]?.focus()
  }

  if (checking) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-orange-300" />
      </div>
    )
  }

  if (forbidden) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <p className="text-lg font-semibold text-zinc-300">Not authorized</p>
        <p className="text-sm text-zinc-600">
          Admin access required. Ask an administrator to grant you the admin role.
        </p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-12">
      <div className="mb-6">
        <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">Admin</p>
        <h1 className="mt-1 text-xl font-semibold text-white">Control Plane</h1>
      </div>

      {/* Tab list */}
      <div
        role="tablist"
        aria-label="Admin sections"
        className="mb-8 inline-flex gap-1 rounded-xl border border-white/[0.07] bg-zinc-900/50 p-1"
      >
        {TABS.map((t, i) => {
          const active = tab === t.id
          return (
            <button
              key={t.id}
              ref={(el) => {
                tabRefs.current[i] = el
              }}
              role="tab"
              id={`admin-tab-${t.id}`}
              aria-selected={active}
              aria-controls={`admin-panel-${t.id}`}
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(t.id)}
              onKeyDown={(e) => onTabKeyDown(e, i)}
              className={`rounded-lg px-4 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-orange-300/60 ${
                active
                  ? 'bg-orange-300/15 text-orange-100'
                  : 'text-zinc-400 hover:bg-white/[0.04] hover:text-white'
              }`}
            >
              {t.label}
            </button>
          )
        })}
      </div>

      <div
        role="tabpanel"
        id={`admin-panel-${tab}`}
        aria-labelledby={`admin-tab-${tab}`}
        tabIndex={0}
        className="focus:outline-none"
      >
        {tab === 'flags' && <FeatureFlagsTab />}
        {tab === 'matrix' && <MatrixTab />}
        {tab === 'users' && <UsersTab />}
      </div>

      <div className="mt-12">
        <div className="mb-6">
          <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">System</p>
          <h2 className="mt-1 text-xl font-semibold text-white">Job Queue</h2>
        </div>
        <div className="rounded-xl border border-white/[0.07] bg-zinc-900/60 p-5">
          <JobQueue maxJobs={50} showFilters showSearch />
        </div>
      </div>
    </div>
  )
}
