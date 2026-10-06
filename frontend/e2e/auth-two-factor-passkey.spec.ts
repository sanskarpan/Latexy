import { expect, test } from '@playwright/test'

test('two-factor challenge switches between authenticator and backup codes', async ({ page }) => {
  await page.goto('/two-factor')

  const code = page.getByLabel('Authenticator code')
  await expect(code).toBeVisible()
  await page.getByRole('button', { name: 'Use a backup code' }).click()
  await expect(page.getByLabel('Backup code')).toBeVisible()

  await page.getByRole('button', { name: 'Use authenticator code' }).click()
  await expect(page.getByLabel('Authenticator code')).toBeVisible()
})

test('passkey sign-in explains when WebAuthn is unavailable', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'PublicKeyCredential', { configurable: true, value: undefined })
  })
  await page.goto('/login', { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Sign in with a passkey' }).click()
  await expect(page.getByText('Passkeys need a supported browser on a secure connection. Use email and password instead.')).toBeVisible()
})
