'use client'

import { useEffect } from 'react'
import { useEntitlements } from '@/contexts/EntitlementsContext'

const CODE_RE = /^[A-Z0-9]{16,64}$/
// Keep the client-side bearer token no longer than the server's maximum
// configurable attribution window (168 hours). The server still enforces the
// account-age window authoritatively when the claim is made.
const REFERRAL_COOKIE_MAX_AGE = 7 * 24 * 60 * 60

/** Capture only a bounded opaque referral token on a first-party cookie. */
export default function ReferralCapture() {
  const { can } = useEntitlements()
  const referralAllowed = can('i03')
  useEffect(() => {
    if (!referralAllowed) return
    const raw = new URLSearchParams(window.location.search).get('ref')
    if (!raw) return
    const code = raw.trim().toUpperCase()
    if (!CODE_RE.test(code)) return
    document.cookie = `latexy_referral=${encodeURIComponent(code)}; Max-Age=${REFERRAL_COOKIE_MAX_AGE}; Path=/; SameSite=Lax${window.location.protocol === 'https:' ? '; Secure' : ''}`
  }, [referralAllowed])
  return null
}
