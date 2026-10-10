'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle, Copy, KeyRound, Loader2, ShieldCheck, Trash2 } from 'lucide-react'
import QRCode from 'qrcode'
import { authClient, useSession } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'
import { downloadBlob } from '@/lib/download'
import { supportsPasskeys } from '@/lib/passkey-security'

type SecurityError = { message?: string; code?: string } | null

function errorMessage(error: SecurityError, fallback: string): string {
  const code = error?.code?.toUpperCase() || ''
  if (code.includes('INVALID_PASSWORD')) return 'That password was not accepted.'
  if (code.includes('SESSION_NOT_FRESH') || code.includes('SESSION_EXPIRED')) {
    return 'Your session is too old for this change. Sign in again and retry.'
  }
  if (code.includes('CANCEL')) return 'The security-key prompt was cancelled.'
  if (code.includes('PREVIOUSLY_REGISTERED')) return 'That passkey is already registered to an account.'
  if (code.includes('UNSUPPORTED') || code.includes('NOT_SUPPORTED')) return 'This browser does not support passkeys.'
  return error?.message || fallback
}

function downloadBackupCodes(codes: string[]) {
  // Keep the codes in memory only. The download is user-initiated and the
  // temporary object URL is revoked shortly after the browser consumes it.
  downloadBlob(new Blob([`Latexy backup codes\n\n${codes.join('\n')}\n`], { type: 'text/plain' }), 'latexy-backup-codes.txt')
}

type SecuritySettingsFormProps = {
  twoFactorEnabled: boolean
  isCurrentOwner: () => boolean
}

function SecuritySettingsForm({ twoFactorEnabled: initialTwoFactorEnabled, isCurrentOwner }: SecuritySettingsFormProps) {
  const mountedRef = useRef(false)
  const listRequestRef = useRef(0)
  const actionRequestRef = useRef(0)
  const copyRequestRef = useRef(0)
  const timersRef = useRef<Set<number>>(new Set())
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(initialTwoFactorEnabled)
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [totpUri, setTotpUri] = useState<string | null>(null)
  const [totpQrDataUrl, setTotpQrDataUrl] = useState<string | null>(null)
  const [backupCodes, setBackupCodes] = useState<string[] | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [passkeyName, setPasskeyName] = useState('')
  const [passkeys, setPasskeys] = useState<ReadonlyArray<{ id: string; name?: string; createdAt?: Date | string }>>([])
  const [loading, setLoading] = useState(false)
  const [passkeysLoading, setPasskeysLoading] = useState(true)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState<'uri' | 'codes' | null>(null)

  useEffect(() => {
    mountedRef.current = true
    const timers = timersRef.current
    return () => {
      mountedRef.current = false
      listRequestRef.current += 1
      actionRequestRef.current += 1
      copyRequestRef.current += 1
      timers.forEach((timer) => window.clearTimeout(timer))
      timers.clear()
    }
  }, [])

  const isMounted = useCallback(() => mountedRef.current && isCurrentOwner(), [isCurrentOwner])

  useEffect(() => {
    if (isMounted()) setTwoFactorEnabled(initialTwoFactorEnabled)
  }, [initialTwoFactorEnabled, isMounted])

  const hasWebAuthn = useMemo(supportsPasskeys, [])

  const loadPasskeys = useCallback(async () => {
    if (!isMounted()) return
    const requestId = ++listRequestRef.current
    if (!isMounted()) return
    setPasskeysLoading(true)
    try {
      if (!isMounted()) return
      const result = await authClient.passkey.listUserPasskeys()
      if (result.error) throw result.error
      if (!isMounted() || requestId !== listRequestRef.current) return
      setPasskeys(result.data || [])
    } catch (e) {
      if (!isMounted() || requestId !== listRequestRef.current) return
      setError(errorMessage(e as SecurityError, 'Could not load passkeys.'))
    } finally {
      if (isMounted() && requestId === listRequestRef.current) setPasskeysLoading(false)
    }
  }, [isMounted])

  useEffect(() => { void loadPasskeys() }, [loadPasskeys])

  const copy = async (value: string, kind: 'uri' | 'codes') => {
    if (!isMounted()) return
    const requestId = ++copyRequestRef.current
    try {
      if (!isMounted()) return
      await navigator.clipboard.writeText(value)
      if (!isMounted() || requestId !== copyRequestRef.current) return
      setCopied(kind)
      const timer = window.setTimeout(() => {
        timersRef.current.delete(timer)
        if (isMounted() && requestId === copyRequestRef.current) {
          setCopied((current) => current === kind ? null : current)
        }
      }, 1500)
      timersRef.current.add(timer)
    } catch {
      if (isMounted() && requestId === copyRequestRef.current) setError('Copy failed. Use the download action or copy the text manually.')
    }
  }

  const enableTwoFactor = async () => {
    if (!isMounted()) return
    const requestId = ++actionRequestRef.current
    setLoading(true); setError('')
    try {
      // Password is optional for OAuth/passkey-only accounts. Better Auth
      // still enforces it server-side when the account has a credential.
      if (!isMounted()) return
      const result = await authClient.twoFactor.enable({ ...(password ? { password } : {}), issuer: 'Latexy', method: 'totp' })
      if (result.error || !result.data || result.data.method !== 'totp') throw result.error || new Error('Two-factor setup failed')
      if (!isMounted() || requestId !== actionRequestRef.current) return
      if ('method' in result.data && result.data.method !== 'totp') {
        throw new Error('Authenticator setup is unavailable for this account. Contact support for help.')
      }
      if (!('totpURI' in result.data) || !('backupCodes' in result.data)) {
        throw new Error('Authenticator setup is unavailable for this account. Contact support for help.')
      }
      const { totpURI, backupCodes: newBackupCodes } = result.data
      setTotpUri(totpURI)
      try {
        const qrDataUrl = await QRCode.toDataURL(totpURI, {
          errorCorrectionLevel: 'M',
          margin: 1,
          width: 220,
        })
        if (!isMounted() || requestId !== actionRequestRef.current) return
        setTotpQrDataUrl(qrDataUrl)
      } catch {
        // Keep manual URI setup available if a browser cannot render a PNG.
        if (!isMounted() || requestId !== actionRequestRef.current) return
        setTotpQrDataUrl(null)
      }
      if (!isMounted() || requestId !== actionRequestRef.current) return
      setBackupCodes(newBackupCodes)
      setAcknowledged(false)
      setPassword('')
    } catch (e) {
      if (isMounted() && requestId === actionRequestRef.current) setError(errorMessage(e as SecurityError, 'Could not start two-factor setup.'))
    } finally {
      if (isMounted() && requestId === actionRequestRef.current) setLoading(false)
    }
  }

  const verifyTwoFactor = async () => {
    if (!totpUri || !code.trim()) { setError('Enter the six-digit code from your authenticator.'); return }
    if (!isMounted()) return
    const requestId = ++actionRequestRef.current
    setLoading(true); setError('')
    try {
      if (!isMounted()) return
      const result = await authClient.twoFactor.verifyTotp({ code: code.trim() })
      if (result.error) throw result.error
      if (!isMounted() || requestId !== actionRequestRef.current) return
      setTwoFactorEnabled(true); setTotpUri(null); setTotpQrDataUrl(null); setCode(''); setPassword('')
    } catch (e) {
      if (isMounted() && requestId === actionRequestRef.current) setError(errorMessage(e as SecurityError, 'That verification code was not accepted.'))
    } finally {
      if (isMounted() && requestId === actionRequestRef.current) setLoading(false)
    }
  }

  const disableTwoFactor = async () => {
    if (!isMounted()) return
    if (!window.confirm('Disable two-factor authentication for this account?')) return
    if (!isMounted()) return
    const requestId = ++actionRequestRef.current
    setLoading(true); setError('')
    try {
      if (!isMounted()) return
      const result = await authClient.twoFactor.disable({ ...(password ? { password } : {}) })
      if (result.error) throw result.error
      if (!isMounted() || requestId !== actionRequestRef.current) return
      setTwoFactorEnabled(false); setTotpQrDataUrl(null); setBackupCodes(null); setPassword('')
    } catch (e) {
      if (isMounted() && requestId === actionRequestRef.current) setError(errorMessage(e as SecurityError, 'Could not disable two-factor authentication.'))
    } finally {
      if (isMounted() && requestId === actionRequestRef.current) setLoading(false)
    }
  }

  const addPasskey = async () => {
    if (!hasWebAuthn) { setError('This browser does not support passkeys. Use a current browser or a security key.'); return }
    if (!isMounted()) return
    const requestId = ++actionRequestRef.current
    setLoading(true); setError('')
    try {
      if (!isMounted()) return
      const result = await authClient.passkey.addPasskey({ name: passkeyName.trim() || undefined })
      if (result.error) throw result.error
      if (!isMounted() || requestId !== actionRequestRef.current) return
      setPasskeyName('')
      await loadPasskeys()
    } catch (e) {
      if (isMounted() && requestId === actionRequestRef.current) setError(errorMessage(e as SecurityError, 'Could not add that passkey.'))
    } finally {
      if (isMounted() && requestId === actionRequestRef.current) setLoading(false)
    }
  }

  const removePasskey = async (id: string) => {
    if (!isMounted()) return
    if (!window.confirm('Remove this passkey? You will not be able to use it to sign in again.')) return
    if (!isMounted()) return
    const requestId = ++actionRequestRef.current
    setLoading(true); setError('')
    try {
      if (!isMounted()) return
      const result = await authClient.passkey.deletePasskey({ id })
      if (result.error) throw result.error
      if (!isMounted() || requestId !== actionRequestRef.current) return
      setPasskeys((current) => current.filter((passkey) => passkey.id !== id))
    } catch (e) {
      if (isMounted() && requestId === actionRequestRef.current) setError(errorMessage(e as SecurityError, 'Could not remove that passkey.'))
    } finally {
      if (isMounted() && requestId === actionRequestRef.current) setLoading(false)
    }
  }

  return (
    <section aria-labelledby="security-heading" className="space-y-6 rounded-[var(--radius-lg)] border border-line bg-surface p-6">
      <div className="flex items-center gap-2.5">
        <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft"><ShieldCheck size={14} className="text-accent-strong" /></div>
        <div><h2 id="security-heading" className="text-base font-semibold text-fg">Account security</h2><p className="text-[11px] text-fg-3">Protect sign-in with an authenticator app or passkey.</p></div>
      </div>

      {error && <p role="alert" className="rounded-[var(--radius-md)] bg-err/10 px-3 py-2 text-[11px] text-err ring-1 ring-err/20">{error}</p>}

      <div className="space-y-4 border-b border-line pb-6">
        <div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-medium text-fg">Authenticator app</h3><p className="mt-1 text-[11px] text-fg-3">Use a time-based one-time password (TOTP) after your password.</p></div><span className="text-[11px] font-medium text-fg-3">{twoFactorEnabled ? 'Enabled' : 'Not enabled'}</span></div>
        {!twoFactorEnabled && !totpUri && <div className="flex flex-col gap-2 sm:flex-row"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Current password (if your account has one)" autoComplete="current-password" aria-label="Current password for two-factor setup" className="min-h-[40px]" /><button type="button" onClick={enableTwoFactor} disabled={loading} className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50">{loading && <Loader2 size={13} className="animate-spin" />} Set up authenticator</button></div>}
        {totpUri && <div className="space-y-3 rounded-[var(--radius-md)] bg-surface-2 p-4"><p className="text-xs text-fg-2">Scan this QR code in your authenticator app, or copy the setup URI. The setup material is kept in memory and is not stored by Latexy.</p>{totpQrDataUrl ? <img src={totpQrDataUrl} width={220} height={220} alt="Authenticator setup QR code" aria-describedby="totp-qr-help" className="h-[220px] w-[220px] rounded border border-line bg-white p-2" /> : <p role="status" className="text-[11px] text-fg-3">QR rendering is unavailable in this browser; copy the setup URI below.</p>}<p id="totp-qr-help" className="sr-only">This QR code contains your authenticator setup. If you cannot scan it, use the setup URI shown below.</p><code className="block max-h-20 overflow-auto break-all rounded border border-line bg-bg p-2 text-[10px] text-fg-2">{totpUri}</code><div className="flex flex-wrap gap-2"><button type="button" onClick={() => void copy(totpUri, 'uri')} className="inline-flex items-center gap-1.5 rounded border border-line px-3 py-1.5 text-[11px] text-fg-2"><Copy size={12} /> {copied === 'uri' ? 'Copied' : 'Copy setup URI'}</button><Input value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" aria-label="Authenticator code" className="min-h-[34px] max-w-[150px]" /><button type="button" onClick={verifyTwoFactor} disabled={loading} className="inline-flex items-center gap-1.5 rounded bg-accent px-3 py-1.5 text-[11px] font-semibold text-accent-fg disabled:opacity-50">Verify and enable</button></div></div>}
        {twoFactorEnabled && <div className="flex flex-col gap-2 sm:flex-row"><Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Current password (if your account has one)" autoComplete="current-password" aria-label="Current password for disabling two-factor" className="min-h-[40px]" /><button type="button" onClick={disableTwoFactor} disabled={loading} className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded border border-err/30 px-4 py-2 text-xs font-semibold text-err disabled:opacity-50">Disable authenticator</button></div>}
        {backupCodes && <div className="space-y-3 rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 p-4"><p className="text-xs font-semibold text-fg">Save your backup codes now</p><p className="text-[11px] text-fg-2">These are shown once and never saved in browser storage or sent to analytics. Each code works once.</p><code className="grid grid-cols-2 gap-1 rounded border border-line bg-bg p-3 text-xs text-fg">{backupCodes.map((item) => <span key={item}>{item}</span>)}</code><div className="flex flex-wrap items-center gap-2"><button type="button" onClick={() => void copy(backupCodes.join('\n'), 'codes')} className="inline-flex items-center gap-1.5 rounded border border-line px-3 py-1.5 text-[11px] text-fg-2"><Copy size={12} /> {copied === 'codes' ? 'Copied' : 'Copy codes'}</button><button type="button" onClick={() => downloadBackupCodes(backupCodes)} className="inline-flex items-center gap-1.5 rounded border border-line px-3 py-1.5 text-[11px] text-fg-2"><KeyRound size={12} /> Download</button><label className="flex items-center gap-2 text-[11px] text-fg-2"><input type="checkbox" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} /> I saved these codes securely</label><button type="button" disabled={!acknowledged} onClick={() => setBackupCodes(null)} className="rounded bg-accent px-3 py-1.5 text-[11px] font-semibold text-accent-fg disabled:opacity-40">Done</button></div></div>}
      </div>

      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4"><div><h3 className="text-sm font-medium text-fg">Passkeys</h3><p className="mt-1 text-[11px] text-fg-3">Sign in with Face ID, Touch ID, Windows Hello, or a security key. Registration requires a recent authenticated session.</p></div><KeyRound size={16} className="text-fg-3" /></div>
        {!hasWebAuthn && <p className="rounded border border-warn/20 bg-warn/10 px-3 py-2 text-[11px] text-warn">Passkeys are not supported in this browser.</p>}
        <div className="flex flex-col gap-2 sm:flex-row"><Input value={passkeyName} onChange={(e) => setPasskeyName(e.target.value.slice(0, 80))} placeholder="Passkey name (optional)" aria-label="Passkey name" className="min-h-[40px]" /><button type="button" onClick={addPasskey} disabled={loading || !hasWebAuthn} className="inline-flex min-h-[40px] items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50">{loading && <Loader2 size={13} className="animate-spin" />} Add passkey</button></div>
        {passkeysLoading ? <p className="text-[11px] text-fg-3">Loading passkeys…</p> : passkeys.length === 0 ? <p className="text-[11px] text-fg-3">No passkeys registered yet.</p> : <ul className="space-y-2">{passkeys.map((item) => <li key={item.id} className="flex items-center justify-between gap-3 rounded border border-line px-3 py-2"><span className="min-w-0 truncate text-xs text-fg">{item.name || 'Passkey'}<span className="ml-2 text-[10px] text-fg-3">{item.createdAt ? new Date(item.createdAt).toLocaleDateString() : ''}</span></span><button type="button" onClick={() => void removePasskey(item.id)} disabled={loading} aria-label={`Remove ${item.name || 'passkey'}`} className="rounded p-1.5 text-err hover:bg-err/10 disabled:opacity-40"><Trash2 size={14} /></button></li>)}</ul>}
      </div>
      <p className="flex items-center gap-1.5 text-[10px] text-fg-3"><CheckCircle size={11} className="text-ok" /> Security credentials are handled by Better Auth and WebAuthn; secrets are never included in URLs or logs.</p>
    </section>
  )
}

export default function SecuritySettings() {
  const { data: session, isPending, error } = useSession()
  const lastKnownSessionRef = useRef<typeof session>(null)
  const ownerEpochRef = useRef(0)
  const renderedOwnerRef = useRef<string | null>(null)

  // Keep the current account's private security draft mounted during a
  // transient refresh/error, but remount it synchronously when Better Auth
  // confirms a different owner (including A → B → A).
  if (session?.user?.id) {
    lastKnownSessionRef.current = session
  } else if (!isPending && !error) {
    lastKnownSessionRef.current = null
  }
  const effectiveSession = session ?? ((isPending || error) ? lastKnownSessionRef.current : null)
  const ownerId = effectiveSession?.user?.id ?? null
  if (renderedOwnerRef.current !== ownerId) {
    renderedOwnerRef.current = ownerId
    ownerEpochRef.current += 1
  }
  const ownerEpoch = ownerEpochRef.current
  const isCurrentOwner = useCallback(() => ownerEpochRef.current === ownerEpoch, [ownerEpoch])

  return (
    <SecuritySettingsForm
      key={ownerId ?? 'anonymous'}
      twoFactorEnabled={Boolean(effectiveSession?.user?.twoFactorEnabled)}
      isCurrentOwner={isCurrentOwner}
    />
  )
}
