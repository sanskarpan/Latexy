import { readFileSync } from 'node:fs'
import QRCode from 'qrcode'
import { describe, expect, it } from 'vitest'
import { validatePasskeyName } from '../lib/passkey-security'

const authSource = readFileSync(new URL('../lib/auth.ts', import.meta.url), 'utf8')
const clientSource = readFileSync(new URL('../lib/auth-client.ts', import.meta.url), 'utf8')
const signInSource = readFileSync(new URL('../components/auth/SignInForm.tsx', import.meta.url), 'utf8')
const securitySource = readFileSync(new URL('../components/auth/SecuritySettings.tsx', import.meta.url), 'utf8')
const routeSource = readFileSync(new URL('../app/api/auth/[...all]/route.ts', import.meta.url), 'utf8')
const challengeSource = readFileSync(new URL('../app/two-factor/page.tsx', import.meta.url), 'utf8')
const migrationSource = readFileSync(new URL('../../../backend/alembic/versions/0047_auth_two_factor_and_passkeys.py', import.meta.url), 'utf8')

describe('B58 authentication security contract', () => {
  it('uses the installed Better Auth plugins with explicit WebAuthn origin policy', () => {
    expect(authSource).toContain("import { genericOAuth, twoFactor } from 'better-auth/plugins'")
    expect(authSource).toContain("import { passkey } from '@better-auth/passkey'")
    expect(authSource).toContain('PASSKEY_RP_ID')
    expect(authSource).toContain('PASSKEY_ORIGINS')
    expect(authSource).toContain('twoFactor({')
    expect(authSource).toContain('allowPasswordless: true')
    expect(authSource).toContain("storeBackupCodes: 'encrypted'")
    expect(authSource).toContain('accountLockout:')
    expect(clientSource).toContain('twoFactorClient({ twoFactorPage: \'/two-factor\' })')
    expect(clientSource).toContain('passkeyClient()')
  })

  it('does not allow 2FA sign-in responses to navigate around the challenge', () => {
    expect(signInSource).toContain('twoFactorRedirect')
    expect(signInSource.indexOf('twoFactorRedirect')).toBeLessThan(signInSource.indexOf('window.location.href = dest'))
    expect(signInSource).not.toContain('We couldn’t find an account with that email.')
  })

  it('uses the signed challenge cookie and a fixed post-verification destination', () => {
    expect(challengeSource).toContain('verifyTotp')
    expect(challengeSource).toContain('verifyBackupCode')
    expect(challengeSource).toContain("router.replace('/workspace')")
    expect(challengeSource).not.toContain('searchParams')
    expect(challengeSource).toContain('Cancel')
  })

  it('gates credential deletion server-side and protects the last login method', () => {
    expect(routeSource).toContain("await auth.api.listSessions({ headers: request.headers })")
    expect(routeSource).toContain("'/two-factor/enable'")
    expect(routeSource).toContain("'/two-factor/disable'")
    expect(routeSource).toContain("'/two-factor/generate-backup-codes'")
    expect(routeSource).toContain("code: 'SESSION_NOT_FRESH'")
    expect(routeSource).toContain("code: 'CANNOT_REMOVE_LAST_LOGIN_METHOD'")
    expect(routeSource).toContain('passkey.rows[0]?.user_id !== session.user.id')
    expect(routeSource).toContain('validatePasskeyName(body.name)')
    expect(routeSource).toContain("headers.delete('content-length')")
    expect(routeSource).toContain("/passkey/generate-register-options")
    expect(routeSource).toContain("/passkey/verify-registration")
    expect(routeSource).toContain('validatePasskeyName(rawName)')
    expect(routeSource).toContain("EMAIL_DELIVERY_UNAVAILABLE")
  })

  it('keeps setup material transient and requires acknowledgement for backup codes', () => {
    expect(securitySource).toContain("if ('method' in result.data && result.data.method !== 'totp')")
    expect(securitySource).toContain("if (!('totpURI' in result.data) || !('backupCodes' in result.data))")
    expect(securitySource.indexOf("if ('method' in result.data && result.data.method !== 'totp')")).toBeLessThan(
      securitySource.indexOf('setTotpUri(totpURI)'),
    )
    expect(securitySource).toContain('Authenticator setup is unavailable for this account.')
    expect(securitySource).toContain('setAcknowledged(false)')
    expect(securitySource).toContain('I saved these codes securely')
    expect(securitySource).toContain("setBackupCodes(null)")
    expect(securitySource).toContain("import { downloadBlob } from '@/lib/download'")
    expect(securitySource).not.toContain('localStorage')
    expect(securitySource).not.toContain('sessionStorage')
  })

  it('matches Better Auth 1.6.25 plugin schema and indexes sensitive lookups', () => {
    for (const field of ['two_factor_enabled', 'twoFactor', 'secret', 'backupCodes', 'failedVerificationCount', 'lockedUntil', 'passkey', 'publicKey', 'credentialID', 'deviceType', 'backedUp']) {
      expect(migrationSource).toContain(field)
    }
    expect(migrationSource).toContain('idx_two_factor_secret')
    expect(migrationSource).toContain('uq_passkey_credential_id')
    expect(migrationSource).toContain('ck_two_factor_backup_codes_encrypted')
    expect(migrationSource).toContain('ck_two_factor_secret_encrypted')
  })

  it('rejects hostile passkey names at the boundary and normalizes safe names', () => {
    expect(validatePasskeyName('  MacBook Pro  ')).toEqual({ name: 'MacBook Pro' })
    expect(validatePasskeyName('')).toHaveProperty('error')
    expect(validatePasskeyName('x'.repeat(81))).toHaveProperty('error')
    expect(validatePasskeyName('safe\u0000name')).toHaveProperty('error')
    expect(validatePasskeyName('safe\u007fname')).toHaveProperty('error')
    expect(validatePasskeyName('\ud800')).toHaveProperty('error')
    expect(validatePasskeyName('é'.repeat(80))).toEqual({ name: 'é'.repeat(80) })
    expect(validatePasskeyName('😀'.repeat(80))).toHaveProperty('error')
    expect(validatePasskeyName(null)).toHaveProperty('error')
  })

  it('renders the TOTP enrollment payload as a real PNG QR code', async () => {
    const dataUrl = await QRCode.toDataURL('otpauth://totp/Latexy:test@example.invalid?secret=REDACTED', {
      errorCorrectionLevel: 'M',
      margin: 1,
      width: 220,
    })
    expect(dataUrl).toMatch(/^data:image\/png;base64,/)
  })
})
