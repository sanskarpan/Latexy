'use client'

import { Suspense, useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Bell, Mail, Calendar, Save, Loader2, CheckCircle, Monitor, Github, Unlink, ExternalLink } from 'lucide-react'
import { apiClient, type NotificationPrefs, type GitHubStatusResponse } from '@/lib/api-client'
import { getNotificationPref, setNotificationPref } from '@/hooks/usePushNotifications'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030'

function SettingsContent() {
  const searchParams = useSearchParams()

  // Notification prefs
  const [prefs, setPrefs] = useState<NotificationPrefs>({ job_completed: true, weekly_digest: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [desktopNotifs, setDesktopNotifs] = useState(true)

  // Load desktop notification preference from localStorage
  useEffect(() => {
    setDesktopNotifs(getNotificationPref())
  }, [])

  // GitHub
  const [ghStatus, setGhStatus] = useState<GitHubStatusResponse>({ connected: false, username: null })
  const [ghLoading, setGhLoading] = useState(true)
  const [ghDisconnecting, setGhDisconnecting] = useState(false)
  const [ghError, setGhError] = useState<string | null>(null)
  const [ghSuccess, setGhSuccess] = useState<string | null>(null)

  useEffect(() => {
    apiClient.getNotificationPrefs()
      .then(setPrefs)
      .catch((e) => setError(e?.message ?? 'Failed to load preferences'))
      .finally(() => setLoading(false))

    apiClient.getGitHubStatus()
      .then(setGhStatus)
      .catch(() => {/* ignore — user not logged in or GitHub not configured */})
      .finally(() => setGhLoading(false))
  }, [])

  // Show success message after OAuth redirect
  useEffect(() => {
    if (searchParams.get('github') === 'connected') {
      setGhSuccess('GitHub account connected successfully!')
      apiClient.getGitHubStatus().then(setGhStatus).catch(() => {})
      setTimeout(() => setGhSuccess(null), 5000)
    }
  }, [searchParams])

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

  async function handleDisconnectGitHub() {
    if (!confirm('Disconnect GitHub? This will disable sync on all your resumes.')) return
    setGhDisconnecting(true)
    setGhError(null)
    try {
      await apiClient.disconnectGitHub()
      setGhStatus({ connected: false, username: null })
    } catch (e: unknown) {
      setGhError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      setGhDisconnecting(false)
    }
  }

  function handleConnectGitHub() {
    // Redirect to backend OAuth flow — need auth token in header, but this is a redirect.
    // We'll open in same window; the backend will redirect back to /settings?github=connected
    window.location.href = `${API_BASE}/github/connect`
  }

  return (
    <div className="min-h-screen bg-[#080808] px-4 py-10">
      <div className="mx-auto max-w-xl space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-semibold text-zinc-100">Settings</h1>
          <p className="mt-1 text-sm text-zinc-500">Manage your account preferences</p>
        </div>

        {/* GitHub Integration card */}
        <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-zinc-800">
              <Github size={14} className="text-zinc-200" />
            </div>
            <h2 className="text-base font-semibold text-zinc-100">GitHub Integration</h2>
          </div>

          {ghSuccess && (
            <p className="rounded-lg bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-400 ring-1 ring-emerald-500/20">
              {ghSuccess}
            </p>
          )}

          {ghLoading ? (
            <div className="flex items-center gap-2 text-zinc-500 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking GitHub status…
            </div>
          ) : ghStatus.connected ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500/15">
                    <CheckCircle size={14} className="text-emerald-400" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-zinc-200">Connected as <span className="text-emerald-300">{ghStatus.username}</span></p>
                    <p className="text-[11px] text-zinc-500">
                      Resume sync enabled. Toggle per-resume in the editor.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <a
                  href={`https://github.com/${ghStatus.username}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 rounded-lg border border-white/[0.08] px-3 py-1.5 text-[11px] font-medium text-zinc-400 transition hover:text-zinc-200"
                >
                  <ExternalLink size={11} />
                  View Profile
                </a>
                <button
                  onClick={handleDisconnectGitHub}
                  disabled={ghDisconnecting}
                  className="flex items-center gap-1.5 rounded-lg border border-rose-500/20 px-3 py-1.5 text-[11px] font-medium text-rose-400 transition hover:bg-rose-500/10 disabled:opacity-40"
                >
                  {ghDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                  {ghDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-zinc-500">
                Connect your GitHub account to sync resume LaTeX source to a private repository.
                Push from the editor manually to save a version in Git.
              </p>
              <button
                onClick={handleConnectGitHub}
                className="flex items-center gap-2 rounded-lg bg-zinc-800 px-4 py-2 text-sm font-semibold text-zinc-100 ring-1 ring-white/[0.1] transition hover:bg-zinc-700"
              >
                <Github size={14} />
                Connect GitHub
              </button>
            </div>
          )}

          {ghError && (
            <p className="rounded-lg bg-rose-500/10 px-3 py-2 text-[11px] text-rose-400 ring-1 ring-rose-500/20">
              {ghError}
            </p>
          )}
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

        {/* Desktop notifications card */}
        <div className="rounded-xl border border-white/[0.07] bg-[#0d0d0d] p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-orange-500/15">
              <Monitor size={14} className="text-orange-300" />
            </div>
            <h2 className="text-base font-semibold text-zinc-100">Desktop Notifications</h2>
          </div>

          <label className="flex items-start justify-between gap-4 cursor-pointer">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-orange-500/10">
                <Bell size={13} className="text-orange-400" />
              </div>
              <div>
                <p className="text-sm font-medium text-zinc-200">Browser notifications</p>
                <p className="mt-0.5 text-[11px] text-zinc-500">
                  Get notified when compilation or optimization finishes while the tab is in the background
                </p>
              </div>
            </div>
            <button
              role="switch"
              aria-checked={desktopNotifs}
              onClick={() => {
                const next = !desktopNotifs
                setDesktopNotifs(next)
                setNotificationPref(next)
              }}
              onKeyDown={(e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                  e.preventDefault()
                  const next = !desktopNotifs
                  setDesktopNotifs(next)
                  setNotificationPref(next)
                }
              }}
              className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors ${
                desktopNotifs ? 'bg-orange-600' : 'bg-white/10'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
                  desktopNotifs ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </label>

          {typeof window !== 'undefined' && 'Notification' in window && Notification.permission === 'denied' && (
            <p className="rounded-lg bg-yellow-500/10 px-3 py-2 text-[11px] text-yellow-400 ring-1 ring-yellow-500/20">
              Notifications are blocked by your browser. Update your site permissions to enable them.
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  return (
    <Suspense fallback={null}>
      <SettingsContent />
    </Suspense>
  )
}
