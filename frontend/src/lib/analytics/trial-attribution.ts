/**
 * Consented trial -> account -> subscription linkage.
 *
 * The browser supplies only its opaque trial fingerprint and an explicit
 * consent flag. Acquisition source values are resolved by the backend from the
 * server-stored first-touch landing row; no campaign, email, IP or token is
 * read from this client.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'

export interface TrialAttributionClaimResult {
  recorded?: boolean
  reason?: string
  source_recorded?: boolean
}

export async function claimTrialAttribution(
  token: string | null | undefined,
  deviceFingerprint: string | null | undefined,
): Promise<boolean> {
  if (!token || !deviceFingerprint) return false
  if (typeof window === 'undefined') return false
  if (typeof process !== 'undefined' && process.env.NEXT_PUBLIC_PLAYWRIGHT_TEST === '1') return false

  try {
    const response = await fetch(`${API_BASE}/analytics/trial/claim`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        device_fingerprint: deviceFingerprint,
        consent_granted: true,
      }),
      credentials: 'include',
    })
    if (!response.ok) return false
    const result = (await response.json().catch(() => ({}))) as TrialAttributionClaimResult
    return Boolean(result.recorded) || result.reason === 'already_linked'
  } catch {
    // Attribution must never block or fail authentication/navigation.
    return false
  }
}
