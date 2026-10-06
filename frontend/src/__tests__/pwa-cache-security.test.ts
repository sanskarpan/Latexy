import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const CONFIG = readFileSync(new URL('../../next.config.js', import.meta.url), 'utf8')
const MANIFEST = JSON.parse(readFileSync(new URL('../../public/manifest.json', import.meta.url), 'utf8'))

describe('PWA cache privacy contract', () => {
  it('never persists authenticated resume API responses across logout', () => {
    expect(CONFIG).not.toContain('latexy-api-resumes')
    expect(CONFIG).not.toContain('latexy-pdf-cache')
    expect(CONFIG).not.toMatch(/urlPattern:\s*\/\\\/resumes/)
    expect(CONFIG).toContain('Never cache authenticated API payloads or PDFs')
    expect(CONFIG).toContain('cacheOnFrontEndNav: false')
    expect(CONFIG).toContain('aggressiveFrontEndNavCaching: false')
    expect(CONFIG).toContain("request.mode === 'navigate'")
    expect(CONFIG).toContain("handler: 'NetworkOnly'")
  })

  it('uses a full-URL-compatible static matcher and excludes desktop Monaco', () => {
    expect(CONFIG).toContain("'!monaco/**/*'")
    expect(CONFIG).toContain('urlPattern: /\\/_next\\/(?:static|image)\\//')
    expect(CONFIG).not.toContain('urlPattern: /^\\/(_next')
  })

  it('ships installable PNG icons including a maskable icon', () => {
    expect(MANIFEST.id).toBe('/')
    expect(MANIFEST.scope).toBe('/')
    expect(MANIFEST.display).toBe('standalone')
    expect(MANIFEST.icons).toEqual(expect.arrayContaining([
      expect.objectContaining({ src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' }),
      expect.objectContaining({ src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' }),
      expect.objectContaining({ src: '/icons/icon-512-maskable.png', purpose: 'maskable' }),
    ]))
    for (const icon of MANIFEST.icons) {
      expect(existsSync(new URL(`../../public${icon.src}`, import.meta.url))).toBe(true)
    }
  })
})
