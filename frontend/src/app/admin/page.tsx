'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'
import { JobQueue } from '@/components/JobQueue'

interface FlagDetail {
  key: string
  enabled: boolean
  label: string
  description: string | null
  updated_at: string | null
}

export default function AdminPage() {
  const [flags, setFlags] = useState<FlagDetail[] | null>(null)
  const [forbidden, setForbidden] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [updating, setUpdating] = useState<string | null>(null)

  useEffect(() => {
    apiClient.getAdminFeatureFlags()
      .then((data) => setFlags(data))
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        if (msg.includes('403') || msg.includes('Forbidden')) {
          setForbidden(true)
        } else {
          setError(msg || 'Failed to load feature flags')
        }
      })
      .finally(() => setLoading(false))
  }, [])

  const toggle = async (key: string, currentEnabled: boolean) => {
    setUpdating(key)
    try {
      const updated = await apiClient.updateFeatureFlag(key, !currentEnabled)
      setFlags((prev) =>
        prev?.map((f) => (f.key === key ? { ...f, enabled: updated.enabled } : f)) ?? null
      )
      toast.success(`${updated.label} ${updated.enabled ? 'enabled' : 'disabled'}`)
    } catch {
      toast.error('Failed to update flag')
    } finally {
      setUpdating(null)
    }
  }

  if (loading) {
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
        <p className="text-sm text-zinc-600">Admin access required. Set ADMIN_EMAIL in backend/.env.</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3">
        <p className="text-lg font-semibold text-zinc-300">Failed to load</p>
        <p className="text-sm text-zinc-600">{error}</p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-12">
      <div className="mb-8">
        <p className="text-[10px] uppercase tracking-[0.25em] text-zinc-600">Admin</p>
        <h1 className="mt-1 text-xl font-semibold text-white">Feature Flags</h1>
      </div>

      <div className="space-y-3">
        {flags?.map((flag) => (
          <div
            key={flag.key}
            className="flex items-center justify-between rounded-xl border border-white/[0.07] bg-zinc-900/60 px-5 py-4"
          >
            <div className="min-w-0 flex-1 pr-6">
              <p className="text-sm font-medium text-zinc-100">{flag.label}</p>
              {flag.description && (
                <p className="mt-0.5 text-xs text-zinc-500">{flag.description}</p>
              )}
              {flag.updated_at && (
                <p className="mt-1 text-[10px] text-zinc-700">
                  {new Date(flag.updated_at).toLocaleString()}
                </p>
              )}
            </div>

            <button
              onClick={() => toggle(flag.key, flag.enabled)}
              disabled={updating === flag.key}
              aria-label={`Toggle ${flag.label}`}
              className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 transition-colors duration-200 focus:outline-none disabled:opacity-50 ${
                flag.enabled
                  ? 'border-orange-400/40 bg-orange-400/20'
                  : 'border-white/10 bg-white/[0.04]'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full transition duration-200 ${
                  flag.enabled
                    ? 'translate-x-5 bg-orange-300'
                    : 'translate-x-0.5 bg-zinc-600'
                }`}
              />
            </button>
          </div>
        ))}
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
