'use client'

import { FormEvent, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Loader2, ShieldCheck } from 'lucide-react'
import { authClient } from '@/lib/auth-client'
import { Input } from '@/components/ui/input'

function readableError(error: { message?: string; code?: string } | null | undefined): string {
  if (error?.code?.toUpperCase().includes('INVALID')) return 'That code was not accepted. Check it and try again.'
  if (error?.code?.toUpperCase().includes('LOCK')) return 'Too many failed attempts. Please wait and try again later.'
  if (error?.code?.toUpperCase().includes('EXPIRED') || error?.code?.toUpperCase().includes('COOKIE')) return 'This verification has expired. Start sign-in again.'
  return error?.message || 'Verification failed. Please try again.'
}

export default function TwoFactorPage() {
  const router = useRouter()
  const [code, setCode] = useState('')
  const [backupMode, setBackupMode] = useState(false)
  const [trustDevice, setTrustDevice] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const normalized = code.trim()
    if (!normalized) { setError('Enter your verification code.'); return }
    setLoading(true); setError('')
    try {
      const result = backupMode
        ? await authClient.twoFactor.verifyBackupCode({ code: normalized, trustDevice })
        : await authClient.twoFactor.verifyTotp({ code: normalized, trustDevice })
      if (result.error) throw result.error
      // Never honor a callback URL from the challenge. The challenge cookie is
      // already tied to the pending sign-in; this fixed destination prevents
      // an attacker from turning the 2FA page into an open redirect.
      router.replace('/workspace')
    } catch (e) {
      setError(readableError(e as { message?: string; code?: string }))
      setCode('')
    } finally { setLoading(false) }
  }

  return (
    <div className="bg-bg text-fg">
      <div className="mx-auto flex min-h-[70vh] max-w-md items-center justify-center px-5 py-16">
        <section className="w-full space-y-6 rounded-[var(--radius-lg)] border border-line bg-surface p-6 shadow-[var(--shadow-2)] sm:p-8" aria-labelledby="two-factor-title">
          <div className="text-center"><ShieldCheck className="mx-auto text-accent-strong" size={26} /><h1 id="two-factor-title" className="mt-3 font-display text-2xl font-semibold text-fg">Verify your sign-in</h1><p className="mt-2 text-sm text-fg-2">Enter the code from your authenticator app to continue.</p></div>
          <form onSubmit={submit} className="space-y-4">
            <label htmlFor="two-factor-code" className="block text-xs font-medium uppercase tracking-[0.16em] text-fg-3">{backupMode ? 'Backup code' : 'Authenticator code'}</label>
            <Input id="two-factor-code" value={code} onChange={(event) => setCode(backupMode ? event.target.value.slice(0, 32) : event.target.value.replace(/\D/g, '').slice(0, 6))} inputMode={backupMode ? 'text' : 'numeric'} autoComplete="one-time-code" autoFocus required placeholder={backupMode ? 'xxxxx-xxxxx' : '000000'} className="min-h-[44px] text-center tracking-[0.2em]" />
            <label className="flex items-center gap-2 text-xs text-fg-2"><input type="checkbox" checked={trustDevice} onChange={(event) => setTrustDevice(event.target.checked)} /> Trust this device for 30 days</label>
            {error && <p role="alert" className="rounded border border-err/20 bg-err/10 px-3 py-2 text-xs text-err">{error}</p>}
            <button type="submit" disabled={loading} className="inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50">{loading && <Loader2 size={14} className="animate-spin" />} Verify and continue</button>
          </form>
          <div className="flex items-center justify-between gap-3 text-xs"><button type="button" onClick={() => { setBackupMode((current) => !current); setCode(''); setError('') }} className="text-accent-strong underline-offset-4 hover:underline">{backupMode ? 'Use authenticator code' : 'Use a backup code'}</button><button type="button" onClick={() => router.replace('/login')} className="text-fg-3 underline-offset-4 hover:underline">Cancel</button></div>
        </section>
      </div>
    </div>
  )
}
