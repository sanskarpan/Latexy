'use client'

import { useEffect, useState } from 'react'
import { Bell, Mail, Calendar, Save, Loader2, CheckCircle } from 'lucide-react'
import { apiClient, type NotificationPrefs } from '@/lib/api-client'

export default function SettingsPage() {
  const [prefs, setPrefs] = useState<NotificationPrefs>({ job_completed: true, weekly_digest: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiClient.getNotificationPrefs()
      .then(setPrefs)
      .catch((e) => setError(e?.message ?? 'Failed to load preferences'))
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await apiClient.updateNotificationPrefs(prefs)
      setPrefs(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to save preferences')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#080808] px-4 py-10">
      <div className="mx-auto max-w-xl space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100">Settings</h1>
          <p className="mt-1 text-sm text-zinc-500">Manage your account preferences</p>
        </div>

        {/* Notification preferences card */}
        <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/15">
              <Bell size={14} className="text-violet-300" />
            </div>
            <h2 className="text-base font-semibold text-zinc-100">Email Notifications</h2>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-zinc-500 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Loading preferences…
            </div>
          ) : (
            <div className="space-y-4">
              {/* Job completed toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10">
                    <Mail size={13} className="text-emerald-400" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Job completion emails</p>
                    <p className="mt-0.5 text-[11px] text-zinc-500">
                      Receive an email when your resume optimization or compilation finishes
                    </p>
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.job_completed}
                  onClick={() => setPrefs((p) => ({ ...p, job_completed: !p.job_completed }))}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      setPrefs((p) => ({ ...p, job_completed: !p.job_completed }))
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
                    prefs.job_completed ? 'bg-violet-600' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      prefs.job_completed ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>

              <div className="border-t border-white/[0.05]" />

              {/* Weekly digest toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-500/10">
                    <Calendar size={13} className="text-blue-400" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Weekly digest</p>
                    <p className="mt-0.5 text-[11px] text-zinc-500">
                      A Monday morning summary of your resume activity and ATS score trends
                    </p>
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.weekly_digest}
                  onClick={() => setPrefs((p) => ({ ...p, weekly_digest: !p.weekly_digest }))}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      setPrefs((p) => ({ ...p, weekly_digest: !p.weekly_digest }))
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
                    prefs.weekly_digest ? 'bg-violet-600' : 'bg-white/10'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      prefs.weekly_digest ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>
            </div>
          )}

          {error && (
            <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-[11px] text-rose-400 ring-1 ring-rose-500/20">
              {error}
            </p>
          )}

          <div className="flex items-center gap-3 pt-1">
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="flex items-center gap-2 rounded-lg bg-violet-600/80 px-4 py-2 text-sm font-semibold text-white ring-1 ring-violet-500/30 transition hover:bg-violet-600 disabled:opacity-40"
            >
              {saving ? (
                <Loader2 size={13} className="animate-spin" />
              ) : saved ? (
                <CheckCircle size={13} className="text-emerald-300" />
              ) : (
                <Save size={13} />
              )}
              {saving ? 'Saving…' : saved ? 'Saved!' : 'Save preferences'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
