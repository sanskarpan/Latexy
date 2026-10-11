import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { engineEditorMode, readEngineCapability } from '../lib/engine-capability'

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); vi.doUnmock('@/lib/api-client') })

describe('staged engine capability contract', () => {
  it('accepts only the exact advertised protocol version', async () => {
    expect(await readEngineCapability(json({ resume_engine_version: 1 }))).toEqual({ status: 'supported' })
    for (const body of [{}, null, [], { resume_engine_version: '1' }, { resume_engine_version: true }, { resume_engine_version: 0 }, { resume_engine_version: 2 }]) {
      expect(await readEngineCapability(json(body))).toEqual({ status: 'unsupported' })
    }
  })
  it('treats only a capability 404 as deployment absence', async () => {
    expect(await readEngineCapability(json({ detail: 'Not Found' }, 404))).toEqual({ status: 'unsupported' })
    for (const status of [401, 403]) {
      expect(await readEngineCapability(json({ detail: 'Not Found' }, status))).toEqual({ status: 'error', reason: 'authorization' })
    }
    for (const status of [400, 405, 408, 429, 500, 502, 503]) {
      expect(await readEngineCapability(json({ detail: 'Not Found' }, status))).toEqual({ status: 'error', reason: 'unavailable' })
    }
  })
  it('does not misclassify HTML or a broken response as a missing version', async () => {
    await expect(readEngineCapability(new Response('<html>Sign in</html>'))).rejects.toThrow()
  })
  it('derives source fallback without replacing user mode preferences or accepting auth errors', () => {
    const preference = { mode: 'pdf' as const, autoCompile: false, source: 'My unsaved document' }
    expect(engineEditorMode(preference.mode, 'unsupported')).toBe('source')
    expect(engineEditorMode(preference.mode, 'supported')).toBe('pdf')
    expect(engineEditorMode(preference.mode, 'error')).toBe('pdf')
    expect(preference).toEqual({ mode: 'pdf', autoCompile: false, source: 'My unsaved document' })
    for (const status of ['supported', 'unsupported', 'loading', 'error'] as const) {
      expect(engineEditorMode('source', status)).toBe('source')
      expect(engineEditorMode('wysiwyg', status)).toBe('wysiwyg')
    }
  })
  it('uses an uncached GET, forwards abort, and never makes a mutation or legacy request on denial', async () => {
    const fetch = vi.fn().mockResolvedValue(json({}, 403))
    vi.stubGlobal('fetch', fetch)
    const { apiClient } = await import('../lib/api-client')
    apiClient.setAuthToken('owner-token')
    const controller = new AbortController()
    expect(await apiClient.getEngineCapability(controller.signal)).toEqual({ status: 'error', reason: 'authorization' })
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toMatch(/\/public\/engine\/capabilities$/)
    expect(fetch.mock.calls[0][1]).toMatchObject({ cache: 'no-store', signal: controller.signal, headers: { Authorization: 'Bearer owner-token' } })
    expect(fetch.mock.calls[0][1].body).toBeUndefined()
    expect(fetch.mock.calls[0][1].method ?? 'GET').toBe('GET')
  })
  it('keeps source-mode permissions and legacy terminal-PDF transport on both editor pages', () => {
    const guest = readFileSync(resolve('src/app/try/page.tsx'), 'utf8')
    const saved = readFileSync(resolve('src/app/workspace/[resumeId]/edit/page.tsx'), 'utf8')
    for (const source of [guest, saved]) {
      expect(source).toContain('engineEditorMode(preferredEditorMode, engineCapability.status, engineCapability.sourceFallback)')
      expect(source).toContain("if (!engineSupported || editorMode !== 'pdf'")
      expect(source).toContain('<EngineCapabilityNotice capability={engineCapability} />')
      expect(source).toContain("autoCompile || (engineSupported && editorMode === 'pdf')")
      expect(source).toContain('apiClient.downloadPdf(')
      expect(source).not.toMatch(/setEditorMode\('source'\)/)
    }
    expect(saved).toContain('readOnly={!canEditDocument}')
    expect(saved).toContain('if (!canEditDocument) return')
  })
})
