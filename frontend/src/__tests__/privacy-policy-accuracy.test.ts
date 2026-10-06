import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const rootPolicy = fs.readFileSync(
  path.join(process.cwd(), '../legal/privacy-policy.md'),
  'utf8',
)
const publicPolicy = fs.readFileSync(
  path.join(process.cwd(), 'public/legal/privacy-policy.md'),
  'utf8',
)

describe('privacy policy accuracy', () => {
  it('keeps the source and published copies byte-identical', () => {
    expect(publicPolicy).toBe(rootPolicy)
  })

  it('names the actual production processors and first-party telemetry', () => {
    for (const provider of ['Vercel', 'Modal', 'Neon', 'Upstash', 'Cloudflare R2']) {
      expect(publicPolicy).toContain(provider)
    }
    expect(publicPolicy).toContain('first-party Web Vitals')
    expect(publicPolicy).toContain('does not currently embed Google Analytics')
  })

  it('does not make the previous unsupported certification or control claims', () => {
    for (const claim of [
      'SOC 2',
      'ISO 27001',
      'AES-256',
      'multi-factor authentication',
      'Geographic redundancy',
      '[Company Address]',
    ]) {
      expect(publicPolicy).not.toContain(claim)
    }
    expect(publicPolicy).toContain('does not claim a privacy or security certification')
    expect(publicPolicy).toContain('There is not currently a self-service account-deletion control')
  })
})
