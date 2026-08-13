'use client'

import { Suspense, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { Bell, BookOpen, Mail, Calendar, Loader2, CheckCircle, Monitor, Unlink, ExternalLink, Cloud, LogIn } from 'lucide-react'
import { Github } from '@/components/icons/brand-icons'
import { apiClient, type NotificationPrefs, type GitHubStatusResponse, type ZoteroStatusResponse, type MendeleyStatusResponse, type DropboxStatusResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { getNotificationPref, setNotificationPref } from '@/hooks/usePushNotifications'

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8030'

function SettingsContent() {
  const searchParams = useSearchParams()
  const { data: sessionData, isPending: sessionLoading } = useSession()
  const settingsTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())

  // Clear all pending timers on unmount
  useEffect(() => () => {
    settingsTimersRef.current.forEach((t) => clearTimeout(t))
    settingsTimersRef.current.clear()
  }, [])

  function scheduleTimer(fn: () => void, delay: number) {
    const t = setTimeout(() => {
      settingsTimersRef.current.delete(t)
      fn()
    }, delay)
    settingsTimersRef.current.add(t)
  }

  // Notification prefs
  const [prefs, setPrefs] = useState<NotificationPrefs>({ job_completed: true, weekly_digest: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [desktopNotifs, setDesktopNotifs] = useState(true)
  const [desktopBusy, setDesktopBusy] = useState(false)

  // Track the browser's current Notification permission so we can (a) drive the
  // request flow when the toggle is turned on and (b) surface the blocked hint.
  // Starts 'default' so the first client render matches SSR (no hydration
  // mismatch); the effect syncs the real value after mount.
  const [notifPerm, setNotifPerm] = useState<NotificationPermission | 'unsupported'>('default')
  useEffect(() => {
    if (typeof window !== 'undefined' && 'Notification' in window) {
      setNotifPerm(Notification.permission)
    } else {
      setNotifPerm('unsupported')
    }
  }, [])

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

  // Zotero (Feature 42)
  const [zotStatus, setZotStatus] = useState<ZoteroStatusResponse>({ connected: false, username: null, user_id: null })
  const [zotLoading, setZotLoading] = useState(true)
  const [zotDisconnecting, setZotDisconnecting] = useState(false)
  const [zotError, setZotError] = useState<string | null>(null)
  const [zotSuccess, setZotSuccess] = useState<string | null>(null)

  // Mendeley (Feature 42)
  const [menStatus, setMenStatus] = useState<MendeleyStatusResponse>({ connected: false, name: null })
  const [menLoading, setMenLoading] = useState(true)
  const [menDisconnecting, setMenDisconnecting] = useState(false)
  const [menError, setMenError] = useState<string | null>(null)
  const [menSuccess, setMenSuccess] = useState<string | null>(null)

  // Dropbox (Feature 77)
  const [dbxStatus, setDbxStatus] = useState<DropboxStatusResponse>({ connected: false, display_name: null, account_id: null })
  const [dbxLoading, setDbxLoading] = useState(true)
  const [dbxDisconnecting, setDbxDisconnecting] = useState(false)
  const [dbxError, setDbxError] = useState<string | null>(null)
  const [dbxSuccess, setDbxSuccess] = useState<string | null>(null)

  // Everything on this page is per-user, so wait for the Better Auth session to
  // resolve before fetching — otherwise these fire before AuthSync has published
  // the Bearer token and every integration wrongly renders as "not connected".
  useEffect(() => {
    if (sessionLoading) return
    if (!sessionData) {
      setLoading(false)
      setGhLoading(false)
      setZotLoading(false)
      setMenLoading(false)
      setDbxLoading(false)
      return
    }

    apiClient.getNotificationPrefs()
      .then(setPrefs)
      .catch((e) => {
        console.error('Failed to load notification preferences', e)
        setError('Failed to load preferences')
      })
      .finally(() => setLoading(false))

    apiClient.getGitHubStatus()
      .then(setGhStatus)
      .catch((e) => {
        console.error('Failed to load GitHub status', e)
        setGhError('Failed to load GitHub status')
      })
      .finally(() => setGhLoading(false))

    apiClient.getZoteroStatus()
      .then(setZotStatus)
      .catch((e) => {
        console.error('Failed to load Zotero status', e)
        setZotError('Failed to load Zotero status')
      })
      .finally(() => setZotLoading(false))

    apiClient.getMendeleyStatus()
      .then(setMenStatus)
      .catch((e) => {
        console.error('Failed to load Mendeley status', e)
        setMenError('Failed to load Mendeley status')
      })
      .finally(() => setMenLoading(false))

    apiClient.getDropboxStatus()
      .then(setDbxStatus)
      .catch((e) => {
        console.error('Failed to load Dropbox status', e)
        setDbxError('Failed to load Dropbox status')
      })
      .finally(() => setDbxLoading(false))
  }, [sessionData, sessionLoading])

  // Show success message after OAuth redirect
  useEffect(() => {
    if (searchParams.get('github') === 'connected') {
      setGhSuccess('GitHub account connected successfully!')
      apiClient.getGitHubStatus().then(setGhStatus).catch(() => {})
      scheduleTimer(() => setGhSuccess(null), 5000)
    }
    if (searchParams.get('zotero') === 'connected') {
      setZotSuccess('Zotero connected successfully!')
      apiClient.getZoteroStatus().then(setZotStatus).catch(() => {})
      scheduleTimer(() => setZotSuccess(null), 5000)
      if (window.opener) {
        window.opener.postMessage({ type: 'zotero:connected' }, '*')
        window.close()
      }
    }
    if (searchParams.get('mendeley') === 'connected') {
      setMenSuccess('Mendeley connected successfully!')
      apiClient.getMendeleyStatus().then(setMenStatus).catch(() => {})
      scheduleTimer(() => setMenSuccess(null), 5000)
      if (window.opener) {
        window.opener.postMessage({ type: 'mendeley:connected' }, '*')
        window.close()
      }
    }
    if (searchParams.get('dropbox') === 'connected') {
      setDbxSuccess('Dropbox account connected successfully!')
      apiClient.getDropboxStatus().then(setDbxStatus).catch(() => {})
      scheduleTimer(() => setDbxSuccess(null), 5000)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams])

  // Notification prefs autosave on toggle (optimistic). The switches look like
  // instant toggles, so persist immediately and reconcile with the server. On
  // failure we revert to the previous value and surface an error.
  async function persistPrefs(next: NotificationPrefs) {
    const prev = prefs
    setPrefs(next) // optimistic
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await apiClient.updateNotificationPrefs(next)
      setPrefs(updated)
      setSaved(true)
      scheduleTimer(() => setSaved(false), 2000)
    } catch (e: unknown) {
      setPrefs(prev) // revert optimistic change
      setError(e instanceof Error ? e.message : 'Failed to save preferences')
    } finally {
      setSaving(false)
    }
  }

  // Desktop notifications toggle. Turning ON must actually obtain browser
  // permission — otherwise the switch reads "enabled" while the browser silently
  // drops every notification. Only persist the pref as ON once permission is
  // 'granted'; if the user denies, revert and let the blocked hint show.
  async function handleToggleDesktop() {
    if (desktopBusy) return
    // Turning OFF is always allowed and needs no permission.
    if (desktopNotifs) {
      setDesktopNotifs(false)
      setNotificationPref(false)
      return
    }

    // Turning ON.
    if (typeof window === 'undefined' || !('Notification' in window)) {
      // No Notification API — persist the local pref and let callers no-op.
      setDesktopNotifs(true)
      setNotificationPref(true)
      return
    }

    if (Notification.permission === 'granted') {
      setDesktopNotifs(true)
      setNotificationPref(true)
      return
    }

    if (Notification.permission === 'denied') {
      // Cannot enable while blocked — keep OFF and surface the hint.
      setNotifPerm('denied')
      return
    }

    // permission === 'default' → must ask before enabling.
    setDesktopBusy(true)
    try {
      const result = await Notification.requestPermission()
      setNotifPerm(result)
      if (result === 'granted') {
        setDesktopNotifs(true)
        setNotificationPref(true)
      } else {
        // Denied or dismissed — keep the toggle OFF and do not persist ON.
        setDesktopNotifs(false)
        setNotificationPref(false)
      }
    } finally {
      setDesktopBusy(false)
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

  function handleConnectZotero() {
    window.location.href = `${API_BASE}/zotero/connect`
  }

  async function handleDisconnectZotero() {
    if (!confirm('Disconnect Zotero? You will need to reconnect to import references.')) return
    setZotDisconnecting(true)
    setZotError(null)
    try {
      await apiClient.disconnectZotero()
      setZotStatus({ connected: false, username: null, user_id: null })
    } catch (e: unknown) {
      setZotError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      setZotDisconnecting(false)
    }
  }

  function handleConnectDropbox() {
    window.location.href = `${API_BASE}/dropbox/connect`
  }

  async function handleDisconnectDropbox() {
    if (!confirm('Disconnect Dropbox? Sync will be disabled on all your resumes. Files already in Dropbox are not deleted.')) return
    setDbxDisconnecting(true)
    setDbxError(null)
    try {
      await apiClient.disconnectDropbox()
      setDbxStatus({ connected: false, display_name: null, account_id: null })
    } catch (e: unknown) {
      setDbxError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      setDbxDisconnecting(false)
    }
  }

  function handleConnectMendeley() {
    window.location.href = `${API_BASE}/mendeley/connect`
  }

  async function handleDisconnectMendeley() {
    if (!confirm('Disconnect Mendeley? You will need to reconnect to import references.')) return
    setMenDisconnecting(true)
    setMenError(null)
    try {
      await apiClient.disconnectMendeley()
      setMenStatus({ connected: false, name: null })
    } catch (e: unknown) {
      setMenError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      setMenDisconnecting(false)
    }
  }

  // While the session resolves, avoid flashing either the cards or the sign-in
  // gate.
  if (sessionLoading) {
    return (
      <div className="min-h-screen overflow-x-hidden bg-bg px-4 py-10">
        <div className="mx-auto max-w-xl">
          <div className="flex items-center gap-2 rounded-[var(--radius-lg)] border border-line bg-surface p-6 text-sm text-fg-3">
            <Loader2 size={14} className="animate-spin" />
            Loading settings…
          </div>
        </div>
      </div>
    )
  }

  // Signed-out gate. Every card on this page is per-user (integrations need a
  // Bearer token, Save hits an authenticated endpoint), so render a sign-in
  // prompt instead of empty "not connected" cards — matching /developer and
  // /byok.
  if (!sessionData) {
    return (
      <div className="min-h-screen overflow-x-hidden bg-bg px-4 py-10">
        <div className="mx-auto max-w-xl space-y-8">
          <div>
            <h1 className="text-2xl font-semibold text-fg">Settings</h1>
            <p className="mt-1 text-sm text-fg-3">Manage your account preferences</p>
          </div>
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center space-y-4">
            <div className="mx-auto flex h-10 w-10 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <LogIn size={16} className="text-accent-strong" />
            </div>
            <div className="space-y-1">
              <h2 className="text-base font-semibold text-fg">Sign in to manage settings</h2>
              <p className="text-[12px] text-fg-3">
                Connect integrations and manage your notification preferences from one place.
              </p>
            </div>
            <a
              href="/login?next=/settings"
              className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
            >
              <LogIn size={13} />
              Sign in
            </a>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-bg px-4 py-10">
      <div className="mx-auto max-w-xl space-y-8">
        {/* Header */}
        <div>
          <h1 className="text-2xl font-semibold text-fg">Settings</h1>
          <p className="mt-1 text-sm text-fg-3">Manage your account preferences</p>
        </div>

        {/* GitHub Integration card */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-surface-2">
              <Github size={14} className="text-fg" />
            </div>
            <h2 className="text-base font-semibold text-fg">GitHub Integration</h2>
          </div>

          {ghSuccess && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-[11px] text-ok ring-1 ring-ok/20">
              {ghSuccess}
            </p>
          )}

          {ghLoading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking GitHub status…
            </div>
          ) : ghStatus.connected ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ok/15">
                    <CheckCircle size={14} className="text-ok" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg break-words">Connected as <span className="text-ok">{ghStatus.username}</span></p>
                    <p className="text-[11px] text-fg-3">
                      Resume sync enabled. Toggle per-resume in the editor.
                    </p>
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2 pt-1">
                <a
                  href={`https://github.com/${ghStatus.username}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-[11px] font-medium text-fg-2 transition hover:text-fg"
                >
                  <ExternalLink size={11} />
                  View Profile
                </a>
                <button
                  onClick={handleDisconnectGitHub}
                  disabled={ghDisconnecting}
                  className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-err/20 px-3 py-1.5 text-[11px] font-medium text-err transition hover:bg-err/10 disabled:opacity-40"
                >
                  {ghDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                  {ghDisconnecting ? 'Disconnecting…' : 'Disconnect'}
                </button>
              </div>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Connect your GitHub account to sync resume LaTeX source to a private repository.
                Push from the editor manually to save a version in Git.
              </p>
              <button
                onClick={handleConnectGitHub}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-surface-2 px-4 py-2 text-sm font-semibold text-fg ring-1 ring-line transition hover:bg-surface-2 hover:brightness-110"
              >
                <Github size={14} />
                Connect GitHub
              </button>
            </div>
          )}

          {ghError && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {ghError}
            </p>
          )}
        </div>

        {/* Zotero Integration card (Feature 42) */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <BookOpen size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Zotero Integration</h2>
          </div>

          {zotSuccess && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-[11px] text-ok ring-1 ring-ok/20">
              {zotSuccess}
            </p>
          )}

          {zotLoading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking Zotero status…
            </div>
          ) : zotStatus.connected ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ok/15">
                    <CheckCircle size={14} className="text-ok" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg break-words">
                      Connected as <span className="text-ok">@{zotStatus.username}</span>
                    </p>
                    <p className="text-[11px] text-fg-3">
                      Import your library from the References panel in the editor.
                    </p>
                  </div>
                </div>
              </div>
              <button
                onClick={handleDisconnectZotero}
                disabled={zotDisconnecting}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-err/20 px-3 py-1.5 text-[11px] font-medium text-err transition hover:bg-err/10 disabled:opacity-40"
              >
                {zotDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                {zotDisconnecting ? 'Disconnecting…' : 'Disconnect Zotero'}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Connect your Zotero account to import your reference library as BibTeX directly into any resume.
              </p>
              <button
                onClick={handleConnectZotero}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110"
              >
                <ExternalLink size={14} />
                Connect Zotero
              </button>
            </div>
          )}

          {zotError && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {zotError}
            </p>
          )}
        </div>

        {/* Mendeley Integration card (Feature 42) */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <BookOpen size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Mendeley Integration</h2>
          </div>

          {menSuccess && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-[11px] text-ok ring-1 ring-ok/20">
              {menSuccess}
            </p>
          )}

          {menLoading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking Mendeley status…
            </div>
          ) : menStatus.connected ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ok/15">
                    <CheckCircle size={14} className="text-ok" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-fg break-words">
                      Connected as <span className="text-ok">{menStatus.name ?? 'Mendeley User'}</span>
                    </p>
                    <p className="text-[11px] text-fg-3">
                      Import your library from the References panel in the editor.
                    </p>
                  </div>
                </div>
              </div>
              <button
                onClick={handleDisconnectMendeley}
                disabled={menDisconnecting}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-err/20 px-3 py-1.5 text-[11px] font-medium text-err transition hover:bg-err/10 disabled:opacity-40"
              >
                {menDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                {menDisconnecting ? 'Disconnecting…' : 'Disconnect Mendeley'}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Connect your Mendeley account to import your research library as BibTeX directly into any resume.
              </p>
              <button
                onClick={handleConnectMendeley}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110"
              >
                <ExternalLink size={14} />
                Connect Mendeley
              </button>
            </div>
          )}

          {menError && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {menError}
            </p>
          )}
        </div>

        {/* Dropbox Integration card (Feature 77) */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Cloud size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Dropbox Integration</h2>
          </div>

          {dbxSuccess && (
            <p className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-[11px] text-ok ring-1 ring-ok/20">
              {dbxSuccess}
            </p>
          )}

          {dbxLoading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking Dropbox status…
            </div>
          ) : dbxStatus.connected ? (
            <div className="space-y-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ok/15">
                  <CheckCircle size={14} className="text-ok" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-fg">Dropbox connected</p>
                  <p className="text-[11px] text-fg-3">
                    Sync is enabled. Toggle per-resume sync from the editor toolbar.
                  </p>
                </div>
              </div>
              <button
                onClick={handleDisconnectDropbox}
                disabled={dbxDisconnecting}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-err/20 px-3 py-1.5 text-[11px] font-medium text-err transition hover:bg-err/10 disabled:opacity-40"
              >
                {dbxDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                {dbxDisconnecting ? 'Disconnecting…' : 'Disconnect Dropbox'}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Connect your Dropbox account to sync resume LaTeX source to{' '}
                <span className="font-mono text-fg-2">/Latexy/</span> in your Dropbox.
                Push and pull from the editor toolbar per resume.
              </p>
              <button
                onClick={handleConnectDropbox}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110"
              >
                <Cloud size={14} />
                Connect Dropbox
              </button>
            </div>
          )}

          {dbxError && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {dbxError}
            </p>
          )}
        </div>

        {/* Notification preferences card */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Bell size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Email Notifications</h2>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Loading preferences…
            </div>
          ) : (
            <div className="space-y-4">
              {/* Job completed toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                    <Mail size={13} className="text-accent-strong" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Job completion emails</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                      Receive an email when your resume optimization or compilation finishes
                    </p>
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.job_completed}
                  disabled={saving}
                  onClick={() => persistPrefs({ ...prefs, job_completed: !prefs.job_completed })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, job_completed: !prefs.job_completed })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                    prefs.job_completed ? 'bg-accent' : 'bg-surface-2'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${
                      prefs.job_completed ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>

              <div className="border-t border-line" />

              {/* Weekly digest toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                    <Calendar size={13} className="text-accent-strong" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Weekly digest</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                      A Monday morning summary of your resume activity and ATS score trends
                    </p>
                  </div>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.weekly_digest}
                  disabled={saving}
                  onClick={() => persistPrefs({ ...prefs, weekly_digest: !prefs.weekly_digest })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, weekly_digest: !prefs.weekly_digest })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                    prefs.weekly_digest ? 'bg-accent' : 'bg-surface-2'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${
                      prefs.weekly_digest ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>
            </div>
          )}

          {error && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {error}
            </p>
          )}

          {/* Autosave status — changes persist on toggle, so there is no manual
              Save button and no unsaved state to lose. */}
          <div className="flex items-center gap-1.5 pt-1 text-[11px] text-fg-3" aria-live="polite">
            {saving ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                Saving…
              </>
            ) : saved ? (
              <>
                <CheckCircle size={12} className="text-ok" />
                <span className="text-ok">Saved</span>
              </>
            ) : (
              'Changes are saved automatically'
            )}
          </div>
        </div>

        {/* Desktop notifications card */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Monitor size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Desktop Notifications</h2>
          </div>

          <label className="flex items-start justify-between gap-4 cursor-pointer">
            <div className="flex items-start gap-3">
              <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                <Bell size={13} className="text-accent-strong" />
              </div>
              <div>
                <p className="text-sm font-medium text-fg">Browser notifications</p>
                <p className="mt-0.5 text-[11px] text-fg-3">
                  Get notified when compilation or optimization finishes while the tab is in the background
                </p>
              </div>
            </div>
            <button
              role="switch"
              aria-checked={desktopNotifs}
              disabled={desktopBusy}
              onClick={handleToggleDesktop}
              onKeyDown={(e) => {
                if (e.key === ' ' || e.key === 'Enter') {
                  e.preventDefault()
                  handleToggleDesktop()
                }
              }}
              className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                desktopNotifs ? 'bg-accent' : 'bg-surface-2'
              }`}
            >
              <span
                className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${
                  desktopNotifs ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </label>

          {notifPerm === 'denied' && (
            <p className="rounded-[var(--radius-md)] bg-warn/10 px-3 py-2 text-[11px] text-warn ring-1 ring-warn/20">
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
