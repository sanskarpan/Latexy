'use client'

import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { formatCatalogPrice, quotaLimitUpdate, type AdminPlanCatalogResponse, type CatalogPlan, type CatalogPlanUpdate } from '@/lib/plan-catalog'

export default function AdminPlanCatalog() {
  const [catalog, setCatalog] = useState<AdminPlanCatalogResponse | null>(null)
  const [selected, setSelected] = useState('free')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try { setCatalog(await apiClient.getAdminPlanCatalog()) }
    catch (err) { setError(err instanceof Error ? err.message : 'Could not load plan catalog.') }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { void load() }, [load])

  if (loading) return <p className="text-sm text-fg-2" role="status">Loading plan catalog…</p>
  if (!catalog) return (
    <div role="alert" className="rounded-lg border border-line p-4">
      <p>{error || 'Catalog unavailable.'}</p>
      <button type="button" onClick={() => void load()} className="mt-3 underline">Try again</button>
    </div>
  )
  const plan = catalog.plans[selected] || Object.values(catalog.plans)[0]
  return (
    <section aria-label="Plan catalog" className="space-y-5">
      <div>
        <h2 className="text-xl font-semibold text-fg">Plans and pricing</h2>
        <p className="mt-2 text-sm text-fg-2">Manage customer-facing names, descriptions, order, visibility and availability for new purchases. Hidden plans may still be purchased through a direct request; pause new purchases to retire an offer.</p>
        <p className="mt-2 rounded-lg border border-line bg-surface p-3 text-sm text-fg-2">{catalog.pricing_policy}</p>
        <p className="mt-2 text-sm text-fg-2">{catalog.quota_policy}</p>
      </div>
      <label className="block text-sm text-fg-2">
        Plan SKU
        <select value={plan?.id || ''} onChange={(event) => setSelected(event.target.value)} className="mt-1 block w-full rounded-md border border-line bg-surface px-3 py-2 text-fg">
          {Object.values(catalog.plans).map((entry) => <option key={entry.id} value={entry.id}>{entry.name} ({entry.id})</option>)}
        </select>
      </label>
      {plan && <>
        <PlanEditor key={`${plan.id}:${plan.version}`} plan={plan} onSaved={setCatalog} onReload={load} />
        <QuotaControls key={plan.id} plan={plan} onSaved={setCatalog} onReload={load} />
      </>}
    </section>
  )
}

function PlanEditor({ plan, onSaved, onReload }: {
  plan: CatalogPlan
  onSaved: (response: AdminPlanCatalogResponse) => void
  onReload: () => Promise<void>
}) {
  const [name, setName] = useState(plan.name)
  const [description, setDescription] = useState(plan.description || '')
  const [order, setOrder] = useState(plan.display_order ?? 0)
  const [visible, setVisible] = useState(plan.visible !== false)
  const [purchaseEnabled, setPurchaseEnabled] = useState(plan.purchase_enabled !== false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const isFree = plan.id === 'free'

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setError(null)
    setSaved(false)
    const update: CatalogPlanUpdate = {
      version: plan.version ?? 1,
      name: name.trim(), description: description.trim(), display_order: order,
      visible, purchase_enabled: purchaseEnabled,
    }
    try {
      const response = await apiClient.updateAdminPlanCatalog(plan.id, update)
      setSaved(true)
      toast.success('Plan catalog saved')
      onSaved(response)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save this plan.') }
    finally { setSaving(false) }
  }

  return (
    <form onSubmit={save} className="space-y-5 rounded-lg border border-line bg-surface p-5">
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <div><span className="text-fg-3">Stable SKU</span><p>{plan.id} · version {plan.version}</p></div>
        <div><span className="text-fg-3">Capability family</span><p>{plan.plan_family}</p></div>
        <div><span className="text-fg-3">Configured price (read-only)</span><p>{formatCatalogPrice(plan.price, plan.currency)} / {plan.interval}</p></div>
        <div><span className="text-fg-3">Provider plan ID (read-only)</span><p className="break-all">{plan.provider_plan_id || (isFree ? 'No payment required' : plan.purchase_type === 'one_time' ? 'One-time Orders checkout' : 'Uses existing provider setup')}</p></div>
      </div>
      {!plan.configured && <p className="text-sm text-warn">This SKU is not configured for purchase. Enabling sales here cannot create or configure a provider price.</p>}
      <label className="block text-sm text-fg-2">Display name
        <input required maxLength={100} value={name} disabled={saving} onChange={(e) => setName(e.target.value)} className="mt-1 block w-full rounded-md border border-line bg-bg px-3 py-2 text-fg" />
      </label>
      <label className="block text-sm text-fg-2">Description
        <textarea maxLength={300} value={description} disabled={saving} onChange={(e) => setDescription(e.target.value)} className="mt-1 block w-full rounded-md border border-line bg-bg px-3 py-2 text-fg" />
      </label>
      <label className="block text-sm text-fg-2">Display order
        <input type="number" required min={0} max={1000} step={1} value={order} disabled={saving} onChange={(e) => setOrder(Number(e.target.value))} className="mt-1 block w-32 rounded-md border border-line bg-bg px-3 py-2 text-fg" />
      </label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={visible} disabled={saving || isFree} onChange={(e) => setVisible(e.target.checked)} />Visible on pricing and billing</label>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={purchaseEnabled} disabled={saving || isFree} onChange={(e) => setPurchaseEnabled(e.target.checked)} />Available for new purchases</label>
      <p className="text-xs text-fg-3">Existing subscribers keep their subscription identity. Renewal, cancellation, payment verification and refund processing do not use these sale switches. Changes to feature access use the family matrix.</p>
      {plan.quotas && <div className="text-sm text-fg-2"><p className="font-medium">Current allowances</p><ul className="mt-1 space-y-1">{Object.entries(plan.quotas).map(([dimension, quota]) => <li key={dimension}>{dimension.replace(/_/g, ' ')}: {quota.limit === null ? 'Unlimited' : `${quota.limit} / ${quota.window}`}</li>)}</ul></div>}
      {error && <div role="alert" className="text-sm text-danger"><p>{error}</p><button type="button" onClick={() => void onReload()} className="mt-2 underline">Reload catalog</button></div>}
      {saved && <p role="status" className="text-sm text-ok">Catalog saved.</p>}
      <button type="submit" disabled={saving || !name.trim()} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50">{saving ? 'Saving…' : 'Save plan'}</button>
    </form>
  )
}


function QuotaControls({ plan, onSaved, onReload }: {
  plan: CatalogPlan
  onSaved: (response: AdminPlanCatalogResponse) => void
  onReload: () => Promise<void>
}) {
  const [dimension, setDimension] = useState('compilations')
  const quota = plan.quotas?.[dimension]
  if (!quota) return null
  return (
    <section aria-label="Quota limits" className="space-y-4 rounded-lg border border-line bg-surface p-5">
      <h3 className="font-semibold text-fg">Usage limits for {plan.id}</h3>
      <p className="text-sm text-fg-2">Changes apply to the next request for everyone on this exact SKU, including existing subscribers. Lowering a limit can block new requests immediately. Current usage, reset windows and refund receipts stay unchanged. Unlimited usage may increase provider costs.</p>
      <label className="block text-sm text-fg-2">Quota dimension
        <select value={dimension} onChange={(event) => setDimension(event.target.value)} className="mt-1 block w-full rounded-md border border-line bg-bg px-3 py-2 text-fg">
          {Object.keys(plan.quotas || {}).map((key) => <option key={key} value={key}>{key.replace(/_/g, ' ')}</option>)}
        </select>
      </label>
      <QuotaLimitEditor key={`${plan.id}:${dimension}:${quota.version}`} plan={plan} dimension={dimension} quota={quota} onSaved={onSaved} onReload={onReload} />
      <p className="text-xs text-fg-3">Developer API daily request limits are separate operator-configured safeguards and remain read-only.</p>
    </section>
  )
}

function QuotaLimitEditor({ plan, dimension, quota, onSaved, onReload }: {
  plan: CatalogPlan
  dimension: string
  quota: NonNullable<CatalogPlan['quotas']>[string]
  onSaved: (response: AdminPlanCatalogResponse) => void
  onReload: () => Promise<void>
}) {
  const [limit, setLimit] = useState(String(quota.limit ?? 0))
  const [unlimited, setUnlimited] = useState(quota.limit === null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const update = quotaLimitUpdate(quota.version ?? 1, limit, unlimited)
  const valid = update !== null

  async function save(event: React.FormEvent) {
    event.preventDefault()
    if (saving || !update) return
    setSaving(true)
    setError(null)
    try {
      const result = await apiClient.updateAdminPlanQuota(plan.id, dimension, update)
      toast.success('Quota limit saved. Existing usage is unchanged.')
      onSaved(result)
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not save quota limit.') }
    finally { setSaving(false) }
  }

  return (
    <form onSubmit={save} className="space-y-3">
      <p className="text-sm text-fg-2">Fixed reset window: {quota.window}. Version {quota.version ?? 1}. {quota.source === 'admin_override' ? 'Admin override' : 'Configured default'}.</p>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={unlimited} disabled={saving} onChange={(event) => setUnlimited(event.target.checked)} />Unlimited allowance</label>
      <label className="block text-sm text-fg-2">Request limit per {quota.window}
        <input type="number" min={0} max={1_000_000_000} step={1} required={!unlimited} value={limit} disabled={saving || unlimited} onChange={(event) => setLimit(event.target.value)} className="mt-1 block w-48 rounded-md border border-line bg-bg px-3 py-2 text-fg" />
      </label>
      {error && <div role="alert" className="text-sm text-err"><p>{error}</p><button type="button" onClick={() => void onReload()} className="mt-2 underline">Reload catalog</button></div>}
      <button type="submit" disabled={saving || !valid} className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-fg disabled:opacity-50">{saving ? 'Saving quota…' : 'Save quota limit'}</button>
    </form>
  )
}
