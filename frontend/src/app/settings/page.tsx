'use client'

import { Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams, useRouter, usePathname } from 'next/navigation'
import { Bell, BookOpen, Mail, Calendar, Loader2, CheckCircle, Monitor, Unlink, ExternalLink, Cloud, LogIn, CircleAlert, Eye } from 'lucide-react'
import { Github } from '@/components/icons/brand-icons'
import { apiClient, type NotificationPrefs, type GitHubStatusResponse, type ZoteroStatusResponse, type MendeleyStatusResponse, type DropboxStatusResponse, type GoogleDriveStatusResponse } from '@/lib/api-client'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import { getNotificationPref, setNotificationPref } from '@/hooks/usePushNotifications'
import { useOnboarding } from '@/components/onboarding/OnboardingFlow'
import PersonalDictionarySettings from '@/components/PersonalDictionarySettings'
import SecuritySettings from '@/components/auth/SecuritySettings'
import ReferralPanel from '@/components/ReferralPanel'
import { safeOAuthAuthorizationUrl } from '@/lib/oauth-navigation'

function SettingsContent() {
  const searchParams = useSearchParams()
  const router = useRouter()
  const pathname = usePathname()
  const { session: sessionData, isPending: sessionLoading, error: sessionError } = useRequireAuth()
  const { resetOnboarding } = useOnboarding(useMemo(() => ({
    ownerId: sessionData?.user?.id ?? null,
    authToken: sessionData?.session?.token ?? '',
    confirmed: Boolean(sessionData?.user?.id && sessionData?.session?.token && !sessionLoading && !sessionError),
  }), [sessionData?.session?.token, sessionData?.user?.id, sessionError, sessionLoading]))
  const settingsTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set())
  type ProviderActionKey =
    | 'google_drive'
    | 'github_disconnect'
    | 'zotero_disconnect'
    | 'dropbox_disconnect'
    | 'mendeley_disconnect'
  type ProviderActionIdentity = { ownerId: string | null; authToken: string; generation: number }
  const providerActionIdentityRef = useRef<ProviderActionIdentity>({ ownerId: null, authToken: '', generation: 0 })
  const providerActionAuthReadyRef = useRef(false)
  const providerActionMountedRef = useRef(false)
  const providerActionLifecycleRef = useRef(0)
  const providerActionActiveRef = useRef<Record<ProviderActionKey, boolean>>({
    google_drive: false,
    github_disconnect: false,
    zotero_disconnect: false,
    dropbox_disconnect: false,
    mendeley_disconnect: false,
  })
  const providerActionRevisionRef = useRef<Record<ProviderActionKey, number>>({
    google_drive: 0,
    github_disconnect: 0,
    zotero_disconnect: 0,
    dropbox_disconnect: 0,
    mendeley_disconnect: 0,
  })
  const providerActionOwnerId = sessionData?.user?.id ?? null
  const providerActionAuthToken = sessionData?.session?.token ?? ''
  const providerActionAuthReady = Boolean(sessionData && !sessionLoading && !sessionError)
  providerActionAuthReadyRef.current = providerActionAuthReady
  const legacyAuthReadyRef = useRef(providerActionAuthReady)
  const legacyAuthReadyGenerationRef = useRef(0)
  if (legacyAuthReadyRef.current !== providerActionAuthReady) {
    legacyAuthReadyRef.current = providerActionAuthReady
    legacyAuthReadyGenerationRef.current += 1
  }
  if (
    providerActionIdentityRef.current.ownerId !== providerActionOwnerId
    || providerActionIdentityRef.current.authToken !== providerActionAuthToken
  ) {
    providerActionIdentityRef.current = {
      ownerId: providerActionOwnerId,
      authToken: providerActionAuthToken,
      generation: providerActionIdentityRef.current.generation + 1,
    }
    for (const key of Object.keys(providerActionActiveRef.current) as ProviderActionKey[]) {
      providerActionActiveRef.current[key] = false
    }
  }
  const providerActionIdentity = providerActionIdentityRef.current
  type NotificationOwnerIdentity = { ownerId: string | null; generation: number }
  const notificationOwnerIdentityRef = useRef<NotificationOwnerIdentity>({ ownerId: null, generation: 0 })
  const notificationMountedRef = useRef(false)
  const notificationLoadedIdentityRef = useRef<NotificationOwnerIdentity | null>(null)
  const notificationRequestRef = useRef(0)
  const notificationEditRevisionRef = useRef(0)
  const notificationPutInFlightRef = useRef<number | null>(null)
  const notificationOwnerId = sessionData?.user?.id ?? null
  const notificationAuthReady = Boolean(
    notificationOwnerId
    && sessionData?.session?.token
    && !sessionLoading
    && !sessionError,
  )
  const notificationAuthReadyRef = useRef(notificationAuthReady)
  notificationAuthReadyRef.current = notificationAuthReady
  if (notificationOwnerIdentityRef.current.ownerId !== notificationOwnerId) {
    notificationOwnerIdentityRef.current = {
      ownerId: notificationOwnerId,
      generation: notificationOwnerIdentityRef.current.generation + 1,
    }
  }
  const notificationOwnerIdentity = notificationOwnerIdentityRef.current
  type LegacyProvider = 'github' | 'zotero' | 'mendeley' | 'dropbox'
  type LegacyCallbackAttempt = {
    key: string
    ownerGeneration: number
    dispatched: boolean
    settled: boolean
  }
  type LegacyOwnedNotice = { ownerId: string | null; success: string | null; error: string | null }
  const legacyCallbackStartedRef = useRef<Map<LegacyProvider, LegacyCallbackAttempt>>(new Map())
  const legacyCallbackQueryRef = useRef(searchParams)
  legacyCallbackQueryRef.current = searchParams
  const legacyOperationRevisionRef = useRef<Record<LegacyProvider, number>>({ github: 0, zotero: 0, mendeley: 0, dropbox: 0 })
  const legacyStatusRevisionRef = useRef<Record<LegacyProvider, number>>({ github: 0, zotero: 0, mendeley: 0, dropbox: 0 })
  const legacyOwnedNoticeRef = useRef<Record<LegacyProvider, LegacyOwnedNotice>>({
    github: { ownerId: null, success: null, error: null },
    zotero: { ownerId: null, success: null, error: null },
    mendeley: { ownerId: null, success: null, error: null },
    dropbox: { ownerId: null, success: null, error: null },
  })
  const legacyOwnerRef = useRef<string | null>(providerActionIdentity.ownerId)
  const legacyOwnerGenerationRef = useRef(0)
  if (legacyOwnerRef.current !== providerActionIdentity.ownerId) {
    legacyOwnerRef.current = providerActionIdentity.ownerId
    legacyOwnerGenerationRef.current += 1
  }
  const legacyNoticeOwnerRef = useRef<string | null>(providerActionIdentity.ownerId)
  const legacyOwnerNoticeRevisionRef = useRef(0)
  const legacyProviderNoticeRevisionRef = useRef<Record<LegacyProvider, number>>({ github: 0, zotero: 0, mendeley: 0, dropbox: 0 })
  if (legacyNoticeOwnerRef.current !== providerActionIdentity.ownerId) {
    legacyNoticeOwnerRef.current = providerActionIdentity.ownerId
    legacyOwnerNoticeRevisionRef.current += 1
  }

  // Replay the first-run product tour: clear the completion flag (local + account)
  // then head to the workspace, which re-opens onboarding when it isn't completed.
  const handleReplayTour = () => {
    resetOnboarding()
    router.push('/workspace')
  }

  // Deferred notification results and timers belong to this Settings page
  // lifetime. Invalidate them on unmount and keep Strict Mode replay safe.
  useEffect(() => {
    notificationMountedRef.current = true
    const timers = settingsTimersRef.current
    return () => {
      notificationMountedRef.current = false
      notificationRequestRef.current += 1
      notificationEditRevisionRef.current += 1
      notificationPutInFlightRef.current = null
      timers.forEach((t) => clearTimeout(t))
      timers.clear()
    }
  }, [])

  function scheduleTimer(fn: () => void, delay: number) {
    const t = setTimeout(() => {
      settingsTimersRef.current.delete(t)
      fn()
    }, delay)
    settingsTimersRef.current.add(t)
  }

  function retireLegacyCallback(provider: LegacyProvider) {
    // A later explicit action owns the card, even if an earlier verification
    // has already reached the server and cannot be cancelled.
    legacyOperationRevisionRef.current[provider] += 1
    legacyProviderNoticeRevisionRef.current[provider] += 1
    const attempt = legacyCallbackStartedRef.current.get(provider)
    if (attempt) attempt.settled = true
    const notice = legacyOwnedNoticeRef.current[provider]
    if (notice.ownerId === providerActionIdentityRef.current.ownerId && notice.success) {
      if (provider === 'github' && ghSuccess === notice.success) setGhSuccess(null)
      if (provider === 'zotero' && zotSuccess === notice.success) setZotSuccess(null)
      if (provider === 'mendeley' && menSuccess === notice.success) setMenSuccess(null)
      if (provider === 'dropbox' && dbxSuccess === notice.success) setDbxSuccess(null)
    }
    legacyOwnedNoticeRef.current[provider] = {
      ownerId: providerActionIdentityRef.current.ownerId,
      success: null,
      error: null,
    }
    const query = new URLSearchParams(legacyCallbackQueryRef.current.toString())
    if (query.get(provider) === 'connected') {
      query.delete(provider)
      const remaining = query.toString()
      router.replace(remaining ? `${pathname}?${remaining}` : pathname, { scroll: false })
    }
  }

  function beginProviderAction(key: ProviderActionKey) {
    if (
      !providerActionMountedRef.current
      || !providerActionAuthReadyRef.current
      || !providerActionIdentity.ownerId
      || !providerActionIdentity.authToken
      || providerActionActiveRef.current[key]
    ) return null
    const capturedIdentity = providerActionIdentity
    if (
      providerActionIdentityRef.current.ownerId !== capturedIdentity.ownerId
      || providerActionIdentityRef.current.authToken !== capturedIdentity.authToken
      || providerActionIdentityRef.current.generation !== capturedIdentity.generation
    ) return null
    const lifecycle = providerActionLifecycleRef.current
    const revision = ++providerActionRevisionRef.current[key]
    providerActionActiveRef.current[key] = true
    if (key !== 'google_drive') {
      const provider = key.replace('_disconnect', '') as LegacyProvider
      retireLegacyCallback(provider)
      legacyStatusRevisionRef.current[provider] += 1
    }
    const isCurrent = () => (
      providerActionMountedRef.current
      && providerActionLifecycleRef.current === lifecycle
      && providerActionIdentityRef.current.ownerId === capturedIdentity.ownerId
      && providerActionIdentityRef.current.authToken === capturedIdentity.authToken
      && providerActionIdentityRef.current.generation === capturedIdentity.generation
      && providerActionRevisionRef.current[key] === revision
      && providerActionActiveRef.current[key]
    )
    return {
      isCurrent,
      accountContext: { authToken: capturedIdentity.authToken, isCurrent },
    }
  }

  // Notification prefs
  const [prefs, setPrefs] = useState<NotificationPrefs>({
    job_completed: true,
    job_failed: true,
    share_viewed: false,
    weekly_digest: false,
    tracker_updates: true,
    comment_mentions: true,
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notificationRetryNonce, setNotificationRetryNonce] = useState(0)
  const [desktopNotifs, setDesktopNotifs] = useState(true)
  const [desktopBusy, setDesktopBusy] = useState(false)

  const notificationDataReady = notificationMountedRef.current
    && notificationAuthReady
    && notificationLoadedIdentityRef.current?.ownerId === notificationOwnerIdentity.ownerId
    && notificationLoadedIdentityRef.current?.generation === notificationOwnerIdentity.generation

  // Do not briefly expose the previous user's preferences or save indicators
  // while the new account's authoritative GET is pending. Same-owner token
  // refreshes retain local drafts because the owner epoch has not changed.
  useEffect(() => {
    notificationLoadedIdentityRef.current = null
    notificationRequestRef.current += 1
    notificationEditRevisionRef.current += 1
    notificationPutInFlightRef.current = null
    setLoading(Boolean(sessionData))
    setSaving(false)
    setSaved(false)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notificationOwnerIdentity.generation])

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
  const [ghStatus, setGhStatus] = useState<GitHubStatusResponse>({
    connected: false,
    username: null,
    public_import: false,
    private_sync: false,
  })
  const [ghLoading, setGhLoading] = useState(true)
  const [ghConnecting, setGhConnecting] = useState(false)
  const [ghDisconnecting, setGhDisconnecting] = useState(false)
  const [ghError, setGhError] = useState<string | null>(null)
  const [ghSuccess, setGhSuccess] = useState<string | null>(null)
  const oauthCompletionStartedRef = useRef<string | null>(null)

  // Zotero (Feature 42)
  const [zotStatus, setZotStatus] = useState<ZoteroStatusResponse>({ connected: false, username: null, user_id: null })
  const [zotLoading, setZotLoading] = useState(true)
  const [zotConnecting, setZotConnecting] = useState(false)
  const [zotDisconnecting, setZotDisconnecting] = useState(false)
  const [zotError, setZotError] = useState<string | null>(null)
  const [zotSuccess, setZotSuccess] = useState<string | null>(null)

  // Mendeley (Feature 42)
  const [menStatus, setMenStatus] = useState<MendeleyStatusResponse>({ connected: false, name: null })
  const [menLoading, setMenLoading] = useState(true)
  const [menConnecting, setMenConnecting] = useState(false)
  const [menDisconnecting, setMenDisconnecting] = useState(false)
  const [menError, setMenError] = useState<string | null>(null)
  const [menSuccess, setMenSuccess] = useState<string | null>(null)

  // Dropbox (Feature 77)
  const [dbxStatus, setDbxStatus] = useState<DropboxStatusResponse>({ connected: false, display_name: null, account_id: null })
  const [dbxLoading, setDbxLoading] = useState(true)
  const [dbxConnecting, setDbxConnecting] = useState(false)
  const [dbxDisconnecting, setDbxDisconnecting] = useState(false)
  const [dbxError, setDbxError] = useState<string | null>(null)
  const [dbxSuccess, setDbxSuccess] = useState<string | null>(null)

  // Google Drive (B50a). OAuth credentials never reach the browser; this
  // state contains only the server-reported connection and least-privilege
  // scope.
  const [gdriveStatus, setGdriveStatus] = useState<GoogleDriveStatusResponse>({ connected: false, scope: null })
  const [gdriveLoading, setGdriveLoading] = useState(true)
  const [gdriveConnecting, setGdriveConnecting] = useState(false)
  const [gdriveDisconnecting, setGdriveDisconnecting] = useState(false)
  const [gdriveError, setGdriveError] = useState<string | null>(null)
  const [gdriveSuccess, setGdriveSuccess] = useState<string | null>(null)
  type GoogleDriveCompletionOwner = {
    accountKey: string
    ticket: string
    active: boolean
    statusApplied: boolean
  }
  const googleDriveCompletionOwnerRef = useRef<GoogleDriveCompletionOwner | null>(null)
  const googleDriveStatusGenerationRef = useRef(0)
  const googleDriveLifecycleRef = useRef(0)
  const integrationStatusGenerationRef = useRef(0)
  type OAuthCompletionOwner = {
    accountKey: string
    provider: string
    ticket: string
    active: boolean
  }
  const oauthCompletionOwnerRef = useRef<OAuthCompletionOwner | null>(null)
  const githubOAuthMountedRef = useRef(false)
  const githubOAuthLifecycleRef = useRef(0)

  useEffect(() => {
    githubOAuthMountedRef.current = true
    const lifecycle = ++githubOAuthLifecycleRef.current
    return () => {
      githubOAuthMountedRef.current = false
      // Strict Mode replays cleanup/setup in one turn. Preserve the one-use
      // ticket for that replay, but invalidate it after an actual unmount.
      queueMicrotask(() => {
        // eslint-disable-next-line react-hooks/exhaustive-deps
        if (githubOAuthLifecycleRef.current !== lifecycle) return
        githubOAuthMountedRef.current = false
        githubOAuthLifecycleRef.current += 1
        if (oauthCompletionOwnerRef.current?.provider === 'github') {
          oauthCompletionOwnerRef.current = null
        }
      })
    }
  }, [])

  useEffect(() => {
    providerActionMountedRef.current = true
    const lifecycle = ++providerActionLifecycleRef.current
    const revisions = providerActionRevisionRef.current
    const active = providerActionActiveRef.current
    const legacyCallbackStarted = legacyCallbackStartedRef.current
    return () => {
      if (providerActionLifecycleRef.current !== lifecycle) return
      providerActionMountedRef.current = false
      providerActionLifecycleRef.current += 1
      for (const key of Object.keys(active) as ProviderActionKey[]) {
        active[key] = false
      }
      for (const key of Object.keys(revisions) as ProviderActionKey[]) {
        revisions[key] += 1
      }
      legacyCallbackStarted.clear()
    }
  }, [])

  useEffect(() => {
    const clearPreviousOwnerNotice = (
      provider: LegacyProvider,
      currentSuccess: string | null,
      currentError: string | null,
      setSuccess: (message: string | null) => void,
      setError: (message: string | null) => void,
    ) => {
      const notice = legacyOwnedNoticeRef.current[provider]
      if (notice.ownerId === providerActionIdentity.ownerId) return
      if (notice.success && currentSuccess === notice.success) setSuccess(null)
      if (notice.error && currentError === notice.error) setError(null)
      notice.ownerId = providerActionIdentity.ownerId
      notice.success = null
      notice.error = null
    }

    clearPreviousOwnerNotice('github', ghSuccess, ghError, setGhSuccess, setGhError)
    clearPreviousOwnerNotice('zotero', zotSuccess, zotError, setZotSuccess, setZotError)
    clearPreviousOwnerNotice('mendeley', menSuccess, menError, setMenSuccess, setMenError)
    clearPreviousOwnerNotice('dropbox', dbxSuccess, dbxError, setDbxSuccess, setDbxError)
  }, [providerActionIdentity.ownerId, ghSuccess, ghError, zotSuccess, zotError, menSuccess, menError, dbxSuccess, dbxError])

  // An account/token transition invalidates in-flight provider actions. Clear
  // transient busy indicators, but keep confirmed state until the owner-scoped
  // reads below provide the replacement values.
  useEffect(() => {
    setGhDisconnecting(false)
    setZotDisconnecting(false)
    setDbxDisconnecting(false)
    setMenDisconnecting(false)
    setGdriveLoading(false)
    setGdriveDisconnecting(false)
  }, [providerActionIdentity.generation])

  useEffect(() => {
    setGhConnecting(false)
    if (!providerActionAuthReady && oauthCompletionOwnerRef.current?.provider === 'github') {
      oauthCompletionOwnerRef.current.active = false
      oauthCompletionOwnerRef.current = null
    }
  }, [providerActionIdentity.generation, providerActionAuthReady])

  // Any deferred Google Drive response must lose ownership when this page is
  // removed. The owner also gets replaced when the authenticated account
  // changes, so an old OAuth callback cannot update the new account's card.
  useEffect(() => {
    const lifecycle = ++googleDriveLifecycleRef.current
    return () => {
      // React Strict Mode replays passive effects by running cleanup and then
      // setup in the same turn. Defer invalidation so that replay can retain
      // the in-flight one-use ticket and its owner instead of deduping it away.
      queueMicrotask(() => {
        // This ref is intentionally read at cleanup time to distinguish a
        // Strict Mode replay from a real unmount.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        if (googleDriveLifecycleRef.current !== lifecycle) return
        googleDriveStatusGenerationRef.current += 1
        googleDriveCompletionOwnerRef.current = null
        integrationStatusGenerationRef.current += 1
        oauthCompletionOwnerRef.current = null
      })
    }
  }, [])

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
      setGdriveLoading(false)
      return
    }

    const accountKey = `${sessionData.user?.id ?? ''}:${sessionData.session?.token ?? ''}`
    if (oauthCompletionOwnerRef.current && oauthCompletionOwnerRef.current.accountKey !== accountKey) {
      oauthCompletionOwnerRef.current = null
    }
    const generation = ++integrationStatusGenerationRef.current
    let cancelled = false
    const current = () => !cancelled && integrationStatusGenerationRef.current === generation
    const initialStatusRevision = { ...legacyStatusRevisionRef.current }
    const currentStatus = (provider: LegacyProvider) => (
      current() && legacyStatusRevisionRef.current[provider] === initialStatusRevision[provider]
    )
    const ownerIdentity = notificationOwnerIdentity
    if (!notificationAuthReady) {
      setLoading(false)
    } else {
      if (
        notificationLoadedIdentityRef.current?.ownerId !== ownerIdentity.ownerId
        || notificationLoadedIdentityRef.current?.generation !== ownerIdentity.generation
      ) {
        setLoading(true)
      }
      const notificationRequest = ++notificationRequestRef.current
      const notificationEditAtStart = notificationEditRevisionRef.current
      const notificationPutAtStart = notificationPutInFlightRef.current
      const notificationCurrent = () => (
        current()
        && notificationMountedRef.current
        && notificationOwnerIdentityRef.current.ownerId === ownerIdentity.ownerId
        && notificationOwnerIdentityRef.current.generation === ownerIdentity.generation
        && notificationRequestRef.current === notificationRequest
      )
      const accountContext = {
        authToken: sessionData.session?.token ?? '',
        isCurrent: () => notificationAuthReadyRef.current && notificationCurrent(),
      }

      apiClient.getNotificationPrefs(accountContext)
        .then((nextPrefs) => {
          if (!notificationCurrent()) return
          notificationLoadedIdentityRef.current = ownerIdentity
          // A refresh that began before an optimistic edit must not replace
          // the draft with an older snapshot or supersede an active PUT.
          if (
            notificationEditRevisionRef.current === notificationEditAtStart
            && notificationPutInFlightRef.current === notificationPutAtStart
            && notificationPutAtStart === null
          ) {
            setPrefs(nextPrefs)
            setError(null)
          }
        })
        .catch(() => {
          if (!notificationCurrent()) return
          if (notificationEditRevisionRef.current !== notificationEditAtStart || notificationPutAtStart !== null) return
          console.error('Failed to load notification preferences')
          setError('Failed to load preferences')
        })
        .finally(() => { if (notificationCurrent()) setLoading(false) })
    }

    apiClient.getGitHubStatus()
      .then((status) => { if (currentStatus('github')) setGhStatus(status) })
      .catch(() => {
        if (!currentStatus('github')) return
        console.error('Failed to load GitHub status')
        setGhError('Failed to load GitHub status')
      })
      .finally(() => { if (currentStatus('github')) setGhLoading(false) })

    apiClient.getZoteroStatus()
      .then((status) => { if (currentStatus('zotero')) setZotStatus(status) })
      .catch(() => {
        if (!currentStatus('zotero')) return
        console.error('Failed to load Zotero status')
        setZotError('Failed to load Zotero status')
      })
      .finally(() => { if (currentStatus('zotero')) setZotLoading(false) })

    apiClient.getMendeleyStatus()
      .then((status) => { if (currentStatus('mendeley')) setMenStatus(status) })
      .catch(() => {
        if (!currentStatus('mendeley')) return
        console.error('Failed to load Mendeley status')
        setMenError('Failed to load Mendeley status')
      })
      .finally(() => { if (currentStatus('mendeley')) setMenLoading(false) })

    apiClient.getDropboxStatus()
      .then((status) => { if (currentStatus('dropbox')) setDbxStatus(status) })
      .catch(() => {
        if (!currentStatus('dropbox')) return
        console.error('Failed to load Dropbox status')
        setDbxError('Failed to load Dropbox status')
      })
      .finally(() => { if (currentStatus('dropbox')) setDbxLoading(false) })

    return () => {
      cancelled = true
      if (integrationStatusGenerationRef.current === generation) integrationStatusGenerationRef.current += 1
    }

  }, [sessionData, sessionLoading, sessionError, notificationOwnerIdentity, notificationRetryNonce, notificationAuthReady])

  // Do not race an OAuth ticket exchange with the normal status read. A slow
  // pre-redirect `connected: false` response must not overwrite the connected
  // state returned after `/complete`.
  useEffect(() => {
    if (sessionLoading || !sessionData) return
    const accountKey = `${sessionData.user?.id ?? ''}:${sessionData.session?.token ?? ''}`
    const hasDriveTicket = searchParams.get('google_drive') === 'complete' && Boolean(searchParams.get('ticket'))
    const completionOwner = googleDriveCompletionOwnerRef.current
    if (completionOwner && completionOwner.accountKey !== accountKey) {
      googleDriveStatusGenerationRef.current += 1
      googleDriveCompletionOwnerRef.current = null
    }
    if (hasDriveTicket) return
    if (completionOwner?.accountKey === accountKey) {
      if (completionOwner.active) return
      if (completionOwner.statusApplied) {
        // The completion status is authoritative for the first render after
        // router.replace removes the ticket. Consume this one suppression so a
        // later settings/search-param change can perform a fresh read.
        completionOwner.statusApplied = false
        return
      }
    }

    const generation = ++googleDriveStatusGenerationRef.current
    let cancelled = false
    setGdriveLoading(true)
    apiClient.getGoogleDriveStatus()
      .then((status) => {
        if (!cancelled && googleDriveStatusGenerationRef.current === generation) setGdriveStatus(status)
      })
      .catch(() => {
        if (cancelled || googleDriveStatusGenerationRef.current !== generation) return
        console.error('Failed to load Google Drive status')
        setGdriveError('Failed to load Google Drive status. Please retry.')
      })
      .finally(() => {
        if (!cancelled && googleDriveStatusGenerationRef.current === generation) setGdriveLoading(false)
      })
    return () => {
      cancelled = true
      if (googleDriveStatusGenerationRef.current === generation) googleDriveStatusGenerationRef.current += 1
    }
  }, [searchParams, sessionData, sessionLoading])

  // Provider callbacks only return short-lived tickets. Exchange them through
  // the authenticated client so the backend can prove this browser is signed
  // in as the same Latexy user who initiated each OAuth flow.
  useEffect(() => {
    const providers = ['github', 'zotero', 'mendeley', 'dropbox', 'google_drive'] as const
    type Provider = typeof providers[number]
    const provider = providers.find((name) => {
      const result = searchParams.get(name)
      return result === 'complete' || result === 'error'
    })
    if (!provider) return

    const providerName = provider === 'github'
      ? 'GitHub'
      : provider === 'google_drive'
        ? 'Google Drive'
      : `${provider[0].toUpperCase()}${provider.slice(1)}`
    const setProviderError = (message: string | null) => {
      if (provider === 'github') setGhError(message)
      if (provider === 'zotero') setZotError(message)
      if (provider === 'mendeley') setMenError(message)
      if (provider === 'dropbox') setDbxError(message)
      if (provider === 'google_drive') setGdriveError(message)
    }
    const setProviderConnecting = (value: boolean) => {
      if (provider === 'github') setGhConnecting(value)
      if (provider === 'zotero') setZotConnecting(value)
      if (provider === 'mendeley') setMenConnecting(value)
      if (provider === 'dropbox') setDbxConnecting(value)
      if (provider === 'google_drive') setGdriveConnecting(value)
    }

    if (searchParams.get(provider) === 'error') {
      const reason = searchParams.get('reason')
      const message = reason === 'access_denied'
        ? `${providerName} authorization was cancelled.`
        : reason === 'invalid_state'
          ? `The ${providerName} connection request expired. Please try again.`
          : `${providerName} could not be connected. Please try again.`
      setProviderError(message)
      router.replace(pathname, { scroll: false })
      return
    }

    if (sessionLoading || (provider === 'github' && sessionError)) return

    const ticket = searchParams.get('ticket')
    if (!ticket) {
      setProviderError(`The ${providerName} connection request is incomplete. Please try again.`)
      router.replace(pathname, { scroll: false })
      return
    }
    if (!sessionData) {
      setProviderError(`Sign in as the account that started this ${providerName} connection, then try again.`)
      router.replace(pathname, { scroll: false })
      return
    }
    const accountKey = `${sessionData.user?.id ?? ''}:${sessionData.session?.token ?? ''}`
    // A callback ticket is one intent, not a new intent after account/token
    // rotation. Never replay a started GitHub ticket as the replacement user.
    const completionKey = provider === 'github'
      ? `${provider}:${ticket}`
      : `${accountKey}:${provider}:${ticket}`
    if (oauthCompletionStartedRef.current === completionKey) return

    if (provider !== 'google_drive') retireLegacyCallback(provider)
    oauthCompletionStartedRef.current = completionKey
    const googleDriveOwner = provider === 'google_drive'
      ? { accountKey, ticket, active: true, statusApplied: false }
      : null
    const providerOwner = provider === 'google_drive'
      ? null
      : { accountKey, provider, ticket, active: true }
    const githubAction = provider === 'github'
      ? (() => {
        const capturedIdentity = providerActionIdentity
        const isCurrent = () => (
          githubOAuthMountedRef.current
          && providerActionAuthReadyRef.current
          && providerActionIdentityRef.current.ownerId === capturedIdentity.ownerId
          && providerActionIdentityRef.current.authToken === capturedIdentity.authToken
          && providerActionIdentityRef.current.generation === capturedIdentity.generation
          && oauthCompletionOwnerRef.current === providerOwner
          && Boolean(providerOwner?.active)
        )
        return { isCurrent, accountContext: { authToken: capturedIdentity.authToken, isCurrent } }
      })()
      : null
    if (googleDriveOwner) {
      googleDriveStatusGenerationRef.current += 1
      googleDriveCompletionOwnerRef.current = googleDriveOwner
    }
    if (providerOwner) oauthCompletionOwnerRef.current = providerOwner
    router.replace(pathname, { scroll: false })
    setProviderConnecting(true)
    setProviderError(null)

    const complete = async (name: Provider) => {
      if (name === 'github') {
        if (!githubAction) return
        await apiClient.completeGitHubOAuth(ticket, githubAction.accountContext)
        if (!githubAction.isCurrent()) return
        const status = await apiClient.getGitHubStatus(githubAction.accountContext)
        if (!githubAction.isCurrent()) return
        setGhStatus(status)
        setGhSuccess('GitHub account connected successfully!')
        scheduleTimer(() => {
          if (providerOwner === oauthCompletionOwnerRef.current) setGhSuccess(null)
        }, 5000)
        const returnTo = searchParams.get('return_to')
        if (returnTo?.startsWith('/') && !returnTo.startsWith('//') && !returnTo.includes('\\')) {
          router.replace(returnTo)
        }
      } else if (name === 'zotero') {
        await apiClient.completeZoteroOAuth(ticket)
        if (providerOwner !== oauthCompletionOwnerRef.current) return
        const status = await apiClient.getZoteroStatus()
        if (providerOwner !== oauthCompletionOwnerRef.current) return
        setZotStatus(status)
        setZotSuccess('Zotero connected successfully!')
        scheduleTimer(() => {
          if (providerOwner === oauthCompletionOwnerRef.current) setZotSuccess(null)
        }, 5000)
      } else if (name === 'mendeley') {
        await apiClient.completeMendeleyOAuth(ticket)
        if (providerOwner !== oauthCompletionOwnerRef.current) return
        const status = await apiClient.getMendeleyStatus()
        if (providerOwner !== oauthCompletionOwnerRef.current) return
        setMenStatus(status)
        setMenSuccess('Mendeley connected successfully!')
        scheduleTimer(() => {
          if (providerOwner === oauthCompletionOwnerRef.current) setMenSuccess(null)
        }, 5000)
      } else {
        if (name === 'dropbox') {
          await apiClient.completeDropboxOAuth(ticket)
          if (providerOwner !== oauthCompletionOwnerRef.current) return
          const status = await apiClient.getDropboxStatus()
          if (providerOwner !== oauthCompletionOwnerRef.current) return
          setDbxStatus(status)
          setDbxSuccess('Dropbox connected successfully!')
          scheduleTimer(() => {
            if (providerOwner === oauthCompletionOwnerRef.current) setDbxSuccess(null)
          }, 5000)
        } else {
          const owner = googleDriveOwner
          if (!owner) return
          await apiClient.completeGoogleDriveOAuth(ticket)
          if (owner !== googleDriveCompletionOwnerRef.current) return
          const status = await apiClient.getGoogleDriveStatus()
          if (owner !== googleDriveCompletionOwnerRef.current || !owner.active) return
          owner.statusApplied = true
          owner.active = false
          setGdriveStatus(status)
          setGdriveSuccess('Google Drive connected successfully!')
          scheduleTimer(() => {
            if (owner === googleDriveCompletionOwnerRef.current) setGdriveSuccess(null)
          }, 5000)
        }
      }
    }

    complete(provider)
      .catch((e: unknown) => {
        if (githubAction && !githubAction.isCurrent()) return
        if (googleDriveOwner && googleDriveOwner !== googleDriveCompletionOwnerRef.current) return
        if (providerOwner && providerOwner !== oauthCompletionOwnerRef.current) return
        setProviderError(e instanceof Error ? e.message : `Failed to complete ${providerName} connection`)
      })
      .finally(() => {
        if (githubAction && !githubAction.isCurrent()) return
        if (googleDriveOwner && googleDriveOwner !== googleDriveCompletionOwnerRef.current) return
        if (providerOwner && providerOwner !== oauthCompletionOwnerRef.current) return
        setProviderConnecting(false)
        if (googleDriveOwner) {
          googleDriveOwner.active = false
          setGdriveLoading(false)
        }
        if (providerOwner) providerOwner.active = false
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, router, searchParams, sessionData, sessionLoading, sessionError])

  // Show success message after OAuth redirect
  useEffect(() => {
    const connectedProviders = ['github', 'zotero', 'mendeley', 'dropbox'] as const
    const activeProviders = connectedProviders.filter((provider) => searchParams.get(provider) === 'connected')

    for (const provider of connectedProviders) {
      if (!activeProviders.includes(provider) && legacyCallbackStartedRef.current.has(provider)) {
        legacyOperationRevisionRef.current[provider] += 1
        legacyCallbackStartedRef.current.delete(provider)
      }
    }
    if (!activeProviders.length) return
    if (!providerActionAuthReady || !providerActionIdentity.ownerId || !providerActionIdentity.authToken) {
      for (const provider of activeProviders) {
        const attempt = legacyCallbackStartedRef.current.get(provider)
        if (
          attempt?.ownerGeneration === legacyOwnerGenerationRef.current
          && !attempt.dispatched
          && legacyCallbackStartedRef.current.get(provider) === attempt
        ) {
          legacyOperationRevisionRef.current[provider] += 1
          legacyCallbackStartedRef.current.delete(provider)
        }
      }
      return
    }

    const requestKey = `${providerActionIdentity.generation}:${searchParams.toString()}`
    const ownerGeneration = legacyOwnerGenerationRef.current
    const clearQueryAfterVerification = () => {
      // Navigation can add a provider or unrelated parameters while a read is
      // held. Only consume the current, fully settled callback markers.
      const query = new URLSearchParams(legacyCallbackQueryRef.current.toString())
      const currentProviders = connectedProviders.filter((provider) => query.get(provider) === 'connected')
      if (currentProviders.length && currentProviders.every((provider) => {
        const attempt = legacyCallbackStartedRef.current.get(provider)
        return attempt?.ownerGeneration === ownerGeneration && attempt.settled
      })) {
        for (const provider of currentProviders) query.delete(provider)
        const remaining = query.toString()
        router.replace(remaining ? `${pathname}?${remaining}` : pathname, { scroll: false })
      }
    }
    const verifyLegacyConnection = async <T extends { connected: boolean }>(
      provider: LegacyProvider,
      providerName: string,
      loadStatus: (context: { authToken: string; isCurrent: () => boolean }) => Promise<T>,
      setStatus: (status: T) => void,
      setProviderLoading: (loading: boolean) => void,
      setSuccess: (message: string | null) => void,
      setProviderError: (message: string | null) => void,
      onVerified?: (isCurrent: () => boolean) => void,
    ): Promise<void> => {
      const previousAttempt = legacyCallbackStartedRef.current.get(provider)
      if (previousAttempt?.ownerGeneration === ownerGeneration && (
        previousAttempt.key === requestKey
        || previousAttempt.settled
        || (previousAttempt.dispatched && !previousAttempt.settled)
      )) return

      const operationRevision = legacyOperationRevisionRef.current[provider] + 1
      legacyOperationRevisionRef.current[provider] = operationRevision
      const providerActionLifecycle = providerActionLifecycleRef.current
      const capturedIdentity = providerActionIdentity
      const capturedAuthReadyGeneration = legacyAuthReadyGenerationRef.current
      const ownerNoticeRevision = legacyOwnerNoticeRevisionRef.current
      let noticeRevision = legacyProviderNoticeRevisionRef.current[provider]
      const attempt: LegacyCallbackAttempt = {
        key: requestKey,
        ownerGeneration,
        dispatched: false,
        settled: false,
      }
      legacyCallbackStartedRef.current.set(provider, attempt)
      const isCurrentResult = () => (
        providerActionMountedRef.current
        && providerActionLifecycleRef.current === providerActionLifecycle
        && providerActionIdentityRef.current.ownerId === capturedIdentity.ownerId
        && legacyOwnerGenerationRef.current === ownerGeneration
        && legacyOperationRevisionRef.current[provider] === operationRevision
        && legacyCallbackStartedRef.current.get(provider) === attempt
        && legacyCallbackQueryRef.current.get(provider) === 'connected'
      )
      const isCurrentDispatch = () => {
        const current = (
          isCurrentResult()
          && providerActionAuthReadyRef.current
          && legacyAuthReadyGenerationRef.current === capturedAuthReadyGeneration
          && providerActionIdentityRef.current.authToken === capturedIdentity.authToken
          && providerActionIdentityRef.current.generation === capturedIdentity.generation
        )
        if (current) attempt.dispatched = true
        return current
      }
      const isCurrentNotice = () => (
        providerActionMountedRef.current
        && providerActionLifecycleRef.current === providerActionLifecycle
        && providerActionIdentityRef.current.ownerId === capturedIdentity.ownerId
        && legacyOwnerGenerationRef.current === ownerGeneration
        && legacyOwnerNoticeRevisionRef.current === ownerNoticeRevision
        && legacyProviderNoticeRevisionRef.current[provider] === noticeRevision
      )
      const accountContext = { authToken: capturedIdentity.authToken, isCurrent: isCurrentDispatch }
      const verificationFailure = `${providerName} authorization completed, but the connection could not be verified. Refresh or try connecting again.`
      if (!isCurrentResult()) return
      setProviderError(null)
      if (legacyOwnedNoticeRef.current[provider].ownerId === capturedIdentity.ownerId) {
        legacyOwnedNoticeRef.current[provider].error = null
      }
      try {
        const status = await loadStatus(accountContext)
        if (!isCurrentResult()) return
        attempt.settled = true
        // An ordinary initial status read may finish while this callback is
        // pending. Keep that known status visible, but once this later read is
        // verified, don't let an older initial response overwrite it.
        legacyStatusRevisionRef.current[provider] += 1
        noticeRevision = legacyProviderNoticeRevisionRef.current[provider] + 1
        legacyProviderNoticeRevisionRef.current[provider] = noticeRevision
        setStatus(status)
        setProviderLoading(false)
        if (!status.connected) {
          setSuccess(null)
          setProviderError(verificationFailure)
          legacyOwnedNoticeRef.current[provider] = {
            ownerId: capturedIdentity.ownerId,
            success: null,
            error: verificationFailure,
          }
          clearQueryAfterVerification()
          return
        }
        const successMessage = `${providerName} connected successfully!`
        setSuccess(successMessage)
        legacyOwnedNoticeRef.current[provider] = {
          ownerId: capturedIdentity.ownerId,
          success: successMessage,
          error: null,
        }
        scheduleTimer(() => {
          if (!isCurrentNotice()) return
          setSuccess(null)
          const notice = legacyOwnedNoticeRef.current[provider]
          if (notice.ownerId === capturedIdentity.ownerId && notice.success === successMessage) {
            notice.success = null
          }
        }, 5000)
        if (onVerified && isCurrentResult()) onVerified(isCurrentResult)
        clearQueryAfterVerification()
      } catch {
        if (!isCurrentResult()) return
        if (!attempt.dispatched) {
          if (legacyCallbackStartedRef.current.get(provider) === attempt) {
            legacyCallbackStartedRef.current.delete(provider)
          }
          return
        }
        attempt.settled = true
        console.error(`Failed to verify ${providerName} connection`)
        setSuccess(null)
        setProviderLoading(false)
        setProviderError(verificationFailure)
        legacyOwnedNoticeRef.current[provider] = {
          ownerId: capturedIdentity.ownerId,
          success: null,
          error: verificationFailure,
        }
        clearQueryAfterVerification()
      }
    }

    if (activeProviders.includes('github')) {
      void verifyLegacyConnection<GitHubStatusResponse>('github', 'GitHub account', (context) => apiClient.getGitHubStatus(context), setGhStatus, setGhLoading, setGhSuccess, setGhError)
    }
    if (activeProviders.includes('zotero')) {
      void verifyLegacyConnection<ZoteroStatusResponse>('zotero', 'Zotero', (context) => apiClient.getZoteroStatus(context), setZotStatus, setZotLoading, setZotSuccess, setZotError, (isCurrent) => {
          if (isCurrent() && window.opener) {
            window.opener.postMessage({ type: 'zotero:connected' }, window.location.origin)
            window.close()
          }
        })
    }
    if (activeProviders.includes('mendeley')) {
      void verifyLegacyConnection<MendeleyStatusResponse>('mendeley', 'Mendeley', (context) => apiClient.getMendeleyStatus(context), setMenStatus, setMenLoading, setMenSuccess, setMenError, (isCurrent) => {
          if (isCurrent() && window.opener) {
            window.opener.postMessage({ type: 'mendeley:connected' }, window.location.origin)
            window.close()
          }
        })
    }
    if (activeProviders.includes('dropbox')) {
      void verifyLegacyConnection<DropboxStatusResponse>('dropbox', 'Dropbox account', (context) => apiClient.getDropboxStatus(context), setDbxStatus, setDbxLoading, setDbxSuccess, setDbxError)
    }
    // Removing a pending provider may leave only already-settled callbacks.
    // They are deduplicated above, but their remaining URL markers still need
    // consuming so a later reload does not replay a finished verification.
    clearQueryAfterVerification()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, router, searchParams, providerActionIdentity.generation, providerActionAuthReady])

  // Notification prefs autosave on toggle (optimistic). The switches look like
  // instant toggles, so persist immediately and reconcile with the server. On
  // failure we revert to the previous value and surface an error.
  async function persistPrefs(next: NotificationPrefs) {
    if (
      !notificationDataReady
      || !notificationAuthReadyRef.current
      || !notificationOwnerIdentity.ownerId
      || !notificationMountedRef.current
      || notificationPutInFlightRef.current !== null
      || notificationOwnerIdentityRef.current.ownerId !== notificationOwnerIdentity.ownerId
      || notificationOwnerIdentityRef.current.generation !== notificationOwnerIdentity.generation
    ) return
    const ownerIdentity = notificationOwnerIdentity
    const revision = ++notificationEditRevisionRef.current
    notificationPutInFlightRef.current = revision
    const current = () => (
      notificationMountedRef.current
      && notificationOwnerIdentityRef.current.ownerId === ownerIdentity.ownerId
      && notificationOwnerIdentityRef.current.generation === ownerIdentity.generation
      && notificationEditRevisionRef.current === revision
    )
    const accountContext = {
      authToken: sessionData?.session?.token ?? '',
      isCurrent: () => notificationAuthReadyRef.current && current(),
    }
    const prev = prefs
    setPrefs(next) // optimistic
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      const updated = await apiClient.updateNotificationPrefs(next, accountContext)
      if (!current()) return
      setPrefs(updated)
      setSaved(true)
      scheduleTimer(() => {
        if (current()) setSaved(false)
      }, 2000)
    } catch (e: unknown) {
      if (!current()) return
      setPrefs(prev) // revert optimistic change
      setError(e instanceof Error ? e.message : 'Failed to save preferences')
    } finally {
      if (!current()) return
      notificationPutInFlightRef.current = null
      setSaving(false)
    }
  }

  function retryNotificationPrefs() {
    if (
      !notificationOwnerIdentity.ownerId
      || !notificationAuthReadyRef.current
      || !notificationMountedRef.current
    ) return
    setError(null)
    setLoading(true)
    setNotificationRetryNonce((nonce) => nonce + 1)
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
    if (!confirm('Disconnect GitHub? Latexy will revoke its GitHub authorization and disable sync on all your resumes. Imported resume text will remain.')) return
    const action = beginProviderAction('github_disconnect')
    if (!action) return
    setGhDisconnecting(true)
    setGhError(null)
    setGhSuccess(null)
    try {
      await apiClient.disconnectGitHub(action.accountContext)
      if (!action.isCurrent()) return
      setGhStatus({ connected: false, username: null, public_import: false, private_sync: false })
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setGhError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.github_disconnect = false
        setGhDisconnecting(false)
      }
    }
  }

  async function handleConnectGitHub() {
    setGhConnecting(true)
    setGhError(null)
    try {
      const { authorization_url: rawAuthorizationUrl } = await apiClient.startGitHubOAuth('sync')
      const authorizationUrl = safeOAuthAuthorizationUrl(rawAuthorizationUrl, {
        hostname: 'github.com',
        pathname: '/login/oauth/authorize',
      })
      if (!authorizationUrl) throw new Error('GitHub returned an invalid authorization URL. Please retry.')
      window.location.assign(authorizationUrl)
    } catch (e: unknown) {
      setGhError(e instanceof Error ? e.message : 'Failed to start GitHub connection')
      setGhConnecting(false)
    }
  }

  async function handleConnectZotero() {
    setZotConnecting(true)
    setZotError(null)
    try {
      const { authorization_url: rawAuthorizationUrl } = await apiClient.startZoteroOAuth()
      const authorizationUrl = safeOAuthAuthorizationUrl(rawAuthorizationUrl, {
        hostname: 'www.zotero.org',
        pathname: '/oauth/authorize',
      })
      if (!authorizationUrl) throw new Error('Zotero returned an invalid authorization URL. Please retry.')
      window.location.assign(authorizationUrl)
    } catch (e: unknown) {
      setZotError(e instanceof Error ? e.message : 'Failed to start Zotero connection')
      setZotConnecting(false)
    }
  }

  async function handleDisconnectZotero() {
    if (!confirm('Disconnect Zotero? You will need to reconnect to import references.')) return
    const action = beginProviderAction('zotero_disconnect')
    if (!action) return
    setZotDisconnecting(true)
    setZotError(null)
    setZotSuccess(null)
    try {
      await apiClient.disconnectZotero(action.accountContext)
      if (!action.isCurrent()) return
      setZotStatus({ connected: false, username: null, user_id: null })
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setZotError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.zotero_disconnect = false
        setZotDisconnecting(false)
      }
    }
  }

  async function handleConnectDropbox() {
    setDbxConnecting(true)
    setDbxError(null)
    try {
      const { authorization_url: rawAuthorizationUrl } = await apiClient.startDropboxOAuth()
      const authorizationUrl = safeOAuthAuthorizationUrl(rawAuthorizationUrl, {
        hostname: 'www.dropbox.com',
        pathname: '/oauth2/authorize',
      })
      if (!authorizationUrl) throw new Error('Dropbox returned an invalid authorization URL. Please retry.')
      window.location.assign(authorizationUrl)
    } catch (e: unknown) {
      setDbxError(e instanceof Error ? e.message : 'Failed to start Dropbox connection')
      setDbxConnecting(false)
    }
  }

  async function handleDisconnectDropbox() {
    if (!confirm('Disconnect Dropbox? Sync will be disabled on all your resumes. Files already in Dropbox are not deleted.')) return
    const action = beginProviderAction('dropbox_disconnect')
    if (!action) return
    setDbxDisconnecting(true)
    setDbxError(null)
    setDbxSuccess(null)
    try {
      await apiClient.disconnectDropbox(action.accountContext)
      if (!action.isCurrent()) return
      setDbxStatus({ connected: false, display_name: null, account_id: null })
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setDbxError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.dropbox_disconnect = false
        setDbxDisconnecting(false)
      }
    }
  }

  async function handleConnectGoogleDrive() {
    if (gdriveConnecting || gdriveDisconnecting) return
    setGdriveConnecting(true)
    setGdriveError(null)
    try {
      const { authorization_url: rawAuthorizationUrl } = await apiClient.startGoogleDriveOAuth()
      const authorizationUrl = safeOAuthAuthorizationUrl(rawAuthorizationUrl, {
        hostname: 'accounts.google.com',
        pathname: '/o/oauth2/v2/auth',
      })
      if (!authorizationUrl) {
        throw new Error('Google Drive returned an invalid authorization URL. Please retry.')
      }
      window.location.assign(authorizationUrl)
    } catch (e: unknown) {
      setGdriveError(e instanceof Error ? e.message : 'Failed to start Google Drive connection')
      setGdriveConnecting(false)
    }
  }

  async function retryGoogleDriveStatus() {
    if (gdriveLoading || gdriveConnecting || gdriveDisconnecting) return
    const action = beginProviderAction('google_drive')
    if (!action) return
    setGdriveLoading(true)
    setGdriveError(null)
    try {
      const status = await apiClient.getGoogleDriveStatus(action.accountContext)
      if (!action.isCurrent()) return
      setGdriveStatus(status)
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setGdriveError(e instanceof Error ? e.message : 'Failed to load Google Drive status. Please retry.')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.google_drive = false
        setGdriveLoading(false)
      }
    }
  }

  async function handleDisconnectGoogleDrive() {
    if (gdriveLoading || gdriveConnecting || gdriveDisconnecting) return
    if (!confirm('Disconnect Google Drive? Files already exported there will not be deleted.')) return
    const action = beginProviderAction('google_drive')
    if (!action) return
    setGdriveDisconnecting(true)
    setGdriveError(null)
    try {
      await apiClient.disconnectGoogleDrive(action.accountContext)
      if (!action.isCurrent()) return
      setGdriveStatus({ connected: false, scope: null })
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setGdriveError(e instanceof Error ? e.message : 'Failed to disconnect Google Drive')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.google_drive = false
        setGdriveDisconnecting(false)
      }
    }
  }

  async function handleConnectMendeley() {
    setMenConnecting(true)
    setMenError(null)
    try {
      const { authorization_url: rawAuthorizationUrl } = await apiClient.startMendeleyOAuth()
      const authorizationUrl = safeOAuthAuthorizationUrl(rawAuthorizationUrl, {
        hostname: 'api.mendeley.com',
        pathname: '/oauth/authorize',
      })
      if (!authorizationUrl) throw new Error('Mendeley returned an invalid authorization URL. Please retry.')
      window.location.assign(authorizationUrl)
    } catch (e: unknown) {
      setMenError(e instanceof Error ? e.message : 'Failed to start Mendeley connection')
      setMenConnecting(false)
    }
  }

  async function handleDisconnectMendeley() {
    if (!confirm('Disconnect Mendeley? You will need to reconnect to import references.')) return
    const action = beginProviderAction('mendeley_disconnect')
    if (!action) return
    setMenDisconnecting(true)
    setMenError(null)
    setMenSuccess(null)
    try {
      await apiClient.disconnectMendeley(action.accountContext)
      if (!action.isCurrent()) return
      setMenStatus({ connected: false, name: null })
    } catch (e: unknown) {
      if (!action.isCurrent()) return
      setMenError(e instanceof Error ? e.message : 'Failed to disconnect')
    } finally {
      if (action.isCurrent()) {
        providerActionActiveRef.current.mendeley_disconnect = false
        setMenDisconnecting(false)
      }
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

  if (sessionError && !sessionData) {
    return (
      <div className="min-h-screen overflow-x-hidden bg-bg px-4 py-10">
        <div role="alert" className="mx-auto max-w-xl rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-8 text-center">
          <CircleAlert className="mx-auto text-err" size={24} />
          <h1 className="mt-3 text-lg font-semibold text-fg">Settings could not verify your session</h1>
          <p className="mt-2 text-sm text-fg-2">Check your connection and retry.</p>
          <button type="button" onClick={() => window.location.reload()} className="mt-5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg">Retry</button>
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

        {/* Account-synced spelling dictionary */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <BookOpen size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Personal Dictionary</h2>
          </div>
          <PersonalDictionarySettings />
        </div>

        <SecuritySettings />

        <ReferralPanel />

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
                      {ghStatus.private_sync
                        ? 'Private resume sync is authorized. Toggle it per resume in the editor.'
                        : 'Connected for public-project import only. Private repositories are not accessible.'}
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
                {!ghStatus.private_sync && (
                  <button
                    onClick={handleConnectGitHub}
                    disabled={ghConnecting}
                    className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-surface-2 px-3 py-1.5 text-[11px] font-medium text-fg ring-1 ring-line transition hover:brightness-110 disabled:opacity-40"
                  >
                    {ghConnecting ? <Loader2 size={11} className="animate-spin" /> : <Github size={11} />}
                    {ghConnecting ? 'Authorizing…' : 'Enable private sync'}
                  </button>
                )}
              </div>
              <p className="text-[10px] leading-relaxed text-fg-3">
                Disconnect revokes Latexy&apos;s authorization at GitHub and removes the stored token.
                Resume text you already imported or synced is not deleted.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Connect your GitHub account to sync resume LaTeX source to a private repository.
                This requests read/write access to your repositories because GitHub OAuth cannot
                make private source-code access read-only. Push from the editor manually to save a version in Git.
              </p>
              <button
                onClick={handleConnectGitHub}
                disabled={ghConnecting}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-surface-2 px-4 py-2 text-sm font-semibold text-fg ring-1 ring-line transition hover:bg-surface-2 hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {ghConnecting ? <Loader2 size={14} className="animate-spin" /> : <Github size={14} />}
                {ghConnecting ? 'Connecting…' : 'Connect GitHub'}
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
                disabled={zotConnecting}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {zotConnecting ? <Loader2 size={14} className="animate-spin" /> : <ExternalLink size={14} />}
                {zotConnecting ? 'Connecting…' : 'Connect Zotero'}
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
                disabled={menConnecting}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {menConnecting ? <Loader2 size={14} className="animate-spin" /> : <ExternalLink size={14} />}
                {menConnecting ? 'Connecting…' : 'Connect Mendeley'}
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
                disabled={dbxConnecting}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {dbxConnecting ? <Loader2 size={14} className="animate-spin" /> : <Cloud size={14} />}
                {dbxConnecting ? 'Connecting…' : 'Connect Dropbox'}
              </button>
            </div>
          )}

          {dbxError && (
            <p className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              {dbxError}
            </p>
          )}
        </div>

        {/* Google Drive export (B50a) */}
        <div data-testid="google-drive-card" className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Cloud size={14} className="text-accent-strong" />
            </div>
            <h2 className="text-base font-semibold text-fg">Google Drive export</h2>
          </div>

          {gdriveSuccess && (
            <p role="status" className="rounded-[var(--radius-md)] bg-ok/10 px-3 py-2 text-[11px] text-ok ring-1 ring-ok/20">
              {gdriveSuccess}
            </p>
          )}

          {gdriveLoading ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Checking Google Drive status…
            </div>
          ) : gdriveStatus.connected ? (
            <div className="space-y-4">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ok/15">
                  <CheckCircle size={14} className="text-ok" />
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-fg">Google Drive connected</p>
                  <p className="text-[11px] text-fg-3">Exports go to a Latexy-created PDF in your Drive.</p>
                </div>
              </div>
              <button
                type="button"
                onClick={handleDisconnectGoogleDrive}
                disabled={gdriveDisconnecting || gdriveConnecting}
                className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-err/20 px-3 py-1.5 text-[11px] font-medium text-err transition hover:bg-err/10 disabled:opacity-40"
              >
                {gdriveDisconnecting ? <Loader2 size={11} className="animate-spin" /> : <Unlink size={11} />}
                {gdriveDisconnecting ? 'Disconnecting…' : 'Disconnect Google Drive'}
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-[12px] text-fg-3">
                Export your latest compiled resume PDF to Google Drive. This uses Google&apos;s{' '}
                <span className="font-mono text-fg-2">drive.file</span> scope: Latexy can access files it creates for you,
                not your whole Drive. Latexy does not read unrelated Drive files.
              </p>
              <button
                type="button"
                onClick={handleConnectGoogleDrive}
                disabled={gdriveConnecting || gdriveDisconnecting}
                className="flex items-center gap-2 rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {gdriveConnecting ? <Loader2 size={14} className="animate-spin" /> : <Cloud size={14} />}
                {gdriveConnecting ? 'Connecting…' : 'Connect Google Drive'}
              </button>
            </div>
          )}

          {gdriveError && (
            <div role="alert" className="flex flex-wrap items-center gap-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              <span>{gdriveError}</span>
              {!gdriveConnecting && !gdriveDisconnecting && (
                <button type="button" onClick={() => void retryGoogleDriveStatus()} className="font-semibold underline">Retry</button>
              )}
            </div>
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

          {!notificationDataReady && (loading || sessionLoading) ? (
            <div className="flex items-center gap-2 text-fg-3 text-sm">
              <Loader2 size={14} className="animate-spin" />
              Loading preferences…
            </div>
          ) : !notificationDataReady ? (
            <div role="alert" className="space-y-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              <p>Failed to load preferences.</p>
              <button type="button" onClick={retryNotificationPrefs} disabled={!notificationAuthReady} className="font-semibold underline disabled:opacity-60">
                Retry notification preferences
              </button>
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
                  type="button"
                  role="switch"
                  aria-label="Job completion emails"
                  aria-checked={prefs.job_completed}
                  disabled={saving || !notificationDataReady}
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

              {/* Job failed toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-err/10">
                    <CircleAlert size={13} className="text-err" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Job failure emails</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                      Receive an email when a resume job cannot finish after retries
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Job failure emails"
                  aria-checked={prefs.job_failed}
                  disabled={saving || !notificationDataReady}
                  onClick={() => persistPrefs({ ...prefs, job_failed: !prefs.job_failed })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, job_failed: !prefs.job_failed })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                    prefs.job_failed ? 'bg-accent' : 'bg-surface-2'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${
                      prefs.job_failed ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>

              <div className="border-t border-line" />

              {/* Share viewed toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                    <Eye size={13} className="text-accent-strong" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Shared resume view emails</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                      Receive an email for each new debounced visitor to a shared resume
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Shared resume view emails"
                  aria-checked={prefs.share_viewed}
                  disabled={saving || !notificationDataReady}
                  onClick={() => persistPrefs({ ...prefs, share_viewed: !prefs.share_viewed })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, share_viewed: !prefs.share_viewed })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                    prefs.share_viewed ? 'bg-accent' : 'bg-surface-2'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${
                      prefs.share_viewed ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </label>

              <div className="border-t border-line" />

              {/* Tracker updates toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                    <Bell size={13} className="text-accent-strong" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Application tracker updates</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">
                      Receive emails for application reminders and saved-search review nudges
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Application tracker updates"
                  aria-checked={prefs.tracker_updates}
                  disabled={saving || !notificationDataReady}
                  onClick={() => persistPrefs({ ...prefs, tracker_updates: !prefs.tracker_updates })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, tracker_updates: !prefs.tracker_updates })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${
                    prefs.tracker_updates ? 'bg-accent' : 'bg-surface-2'
                  }`}
                >
                  <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${prefs.tracker_updates ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </label>

              <div className="border-t border-line" />

              {/* Comment mention toggle */}
              <label className="flex items-start justify-between gap-4 cursor-pointer">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
                    <Bell size={13} className="text-accent-strong" />
                  </div>
                  <div>
                    <p className="text-sm font-medium text-fg">Comment mention emails</p>
                    <p className="mt-0.5 text-[11px] text-fg-3">Receive an email when a collaborator mentions you on a resume</p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Comment mention emails"
                  aria-checked={prefs.comment_mentions}
                  disabled={saving || !notificationDataReady}
                  onClick={() => persistPrefs({ ...prefs, comment_mentions: !prefs.comment_mentions })}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      persistPrefs({ ...prefs, comment_mentions: !prefs.comment_mentions })
                    }
                  }}
                  className={`relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors disabled:opacity-60 ${prefs.comment_mentions ? 'bg-accent' : 'bg-surface-2'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-fg shadow transition-transform ${prefs.comment_mentions ? 'translate-x-4' : 'translate-x-0'}`} />
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
                  type="button"
                  role="switch"
                  aria-label="Weekly digest emails"
                  aria-checked={prefs.weekly_digest}
                  disabled={saving || !notificationDataReady}
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

          {notificationDataReady && error && (
            <div role="alert" className="space-y-2 rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">
              <p>{error}</p>
              {error === 'Failed to load preferences' && (
                <button type="button" onClick={retryNotificationPrefs} disabled={!notificationAuthReady || saving || loading} className="font-semibold underline disabled:opacity-60">
                  Retry notification preferences
                </button>
              )}
            </div>
          )}

          {/* Autosave status — changes persist on toggle, so there is no manual
              Save button and no unsaved state to lose. */}
          <div className="flex items-center gap-1.5 pt-1 text-[11px] text-fg-3" aria-live="polite">
            {notificationDataReady && saving ? (
              <>
                <Loader2 size={12} className="animate-spin" />
                Saving…
              </>
            ) : notificationDataReady && saved ? (
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

        {/* Getting started — replay the first-run product tour on demand. */}
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6">
          <div className="flex items-center gap-2">
            <BookOpen size={16} className="text-accent-strong" />
            <h2 className="text-base font-semibold text-fg">Getting Started</h2>
          </div>
          <p className="mt-2 text-sm text-fg-2">Want a refresher? Replay the product tour that runs the first time you sign in.</p>
          <button
            type="button"
            onClick={handleReplayTour}
            className="mt-4 rounded-[var(--radius-md)] border border-line-2 px-4 py-2 text-sm font-medium text-fg transition hover:bg-surface-2"
          >
            Replay product tour
          </button>
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
