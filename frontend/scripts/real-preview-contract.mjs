import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

/** Accept only credential-free loopback origins. Never print a rejected URL. */
export function localHttpOrigin(value) {
  let url
  try { url = new URL(value) } catch { throw new Error('An explicit local HTTP origin is required') }
  if (!['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
      || url.protocol !== 'http:' || url.username || url.password || url.origin !== value) {
    throw new Error('An explicit credential-free local HTTP origin is required')
  }
  return url.origin
}

/** Browser-created data/blob resources are local, but remote blob origins are not. */
export function isLocalPreviewResource(value) {
  const url = new URL(value)
  if (url.protocol === 'data:' || url.protocol === 'about:') return true
  if (url.protocol === 'blob:') return isLocalPreviewResource(url.pathname)
  return ['http:', 'https:', 'ws:', 'wss:'].includes(url.protocol)
    && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    && !url.username && !url.password
}

export function firstEditableBullet(source) {
  const match = /^\\item[ \t]+([^\r\n]+)/m.exec(source)
  if (!match) throw new Error('The current demo source has no plain editable bullet')
  return match[1]
}

/** Standalone Node benchmark reads the same shipped seed used by /try. */
export async function readDemoSource(filename = resolve(process.cwd(), 'src/lib/first-use-resume.ts')) {
  const sourceModule = await readFile(filename, 'utf8')
  const match = /export const FIRST_USE_ENGINE_RESUME_TEMPLATE = String\.raw`([^`]*)`/.exec(sourceModule)
  if (!match) throw new Error('The shipped engine demo source could not be read')
  return match[1]
}

/** Keep the normal guest allowance/cooldown; fail rather than resetting it. */
export function guestCooldownMilliseconds(status, now = Date.now()) {
  if (status.blocked || status.remainingUses < 1 || status.trialLimit !== 3) {
    throw new Error('The normal isolated guest trial is unavailable')
  }
  if (!Number.isInteger(status.usageCount) || status.usageCount < 1) {
    throw new Error('Guest admission was not recorded by the real trial service')
  }
  const lastUsed = Date.parse(status.lastUsed ?? '')
  if (!Number.isFinite(lastUsed)) throw new Error('The real guest cooldown timestamp is missing')
  // Five minutes is trial_service.COOLDOWN_PERIOD. Allow a small clock skew,
  // then fail closed if this is not the normal bounded local-service trial.
  const milliseconds = Math.max(0, 300_000 - (now - lastUsed)) + 1_000
  if (milliseconds > 361_000) throw new Error('The guest cooldown exceeds the probe bound')
  return milliseconds
}

/** Uses the Playwright-managed Chromium installed by CI, never system Chrome. */
export function previewBrowserLaunchOptions() {
  return { headless: true }
}
