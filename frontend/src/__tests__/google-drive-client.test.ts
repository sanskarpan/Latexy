import { afterEach, describe, expect, test, vi } from 'vitest'
import { readFileSync } from 'node:fs'

import { apiClient } from '../lib/api-client'

function mockJson(body: object) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    headers: { get: () => 'application/json' },
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(JSON.stringify(body)),
  }))
}

afterEach(() => {
  apiClient.setAuthToken(null)
  apiClient.setTenantSlug(null)
  vi.unstubAllGlobals()
})

describe('Google Drive API client', () => {
  test('uses typed status/connect/complete/disconnect contracts without exposing credentials', async () => {
    mockJson({ connected: false, scope: null })
    await expect(apiClient.getGoogleDriveStatus()).resolves.toEqual({ connected: false, scope: null })

    mockJson({ authorization_url: 'https://accounts.google.com/o/oauth2/auth?state=opaque' })
    await expect(apiClient.startGoogleDriveOAuth()).resolves.toHaveProperty('authorization_url')
    const [connectUrl, connectInit] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(connectUrl).toContain('/google-drive/connect')
    expect(String(connectInit.body ?? '')).not.toContain('access_token')

    mockJson({ success: true, message: 'connected' })
    await apiClient.completeGoogleDriveOAuth('one-time-ticket')
    const [, completeInit] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(completeInit.body))).toEqual({ ticket: 'one-time-ticket' })
    expect(String(completeInit.body)).not.toContain('client_secret')

    mockJson({ success: true, message: 'disconnected' })
    await apiClient.disconnectGoogleDrive()
    const [disconnectUrl, disconnectInit] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(disconnectUrl).toContain('/google-drive/disconnect')
    expect(disconnectInit.method).toBe('DELETE')
  })

  test('exports a saved resume and preserves create/update retry semantics', async () => {
    mockJson({ success: true, provider: 'google_drive', action: 'updated', retry_behavior: 'same_file_for_resume' })
    const result = await apiClient.exportResumeToGoogleDrive('resume/with spaces')
    expect(result.action).toBe('updated')
    expect(result.retry_behavior).toBe('same_file_for_resume')
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/google-drive/resumes/resume%2Fwith%20spaces/export')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({})
    expect(String(init.body)).not.toContain('token')
  })

  test('surfaces provider failures to the retryable caller', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      headers: { get: () => 'application/json' },
      text: () => Promise.resolve(JSON.stringify({ detail: 'Google Drive provider unavailable' })),
    }))
    await expect(apiClient.exportResumeToGoogleDrive('resume-1')).rejects.toThrow('HTTP 502')

    const source = readFileSync(new URL('../components/ExportDropdown.tsx', import.meta.url), 'utf8')
    expect(source).toContain('setExportError({ format, message })')
    expect(source).toContain('>Retry</button>')
  })

  test('keeps export UX truthful and preserves the existing live-buffer paths', () => {
    const source = readFileSync(new URL('../components/ExportDropdown.tsx', import.meta.url), 'utf8')
    const settingsSource = readFileSync(new URL('../app/settings/page.tsx', import.meta.url), 'utf8')
    expect(source).toContain("key: 'google_drive'")
    expect(source).toContain('Connect Google Drive in Settings before exporting.')
    expect(source).toContain('Open Settings')
    expect(source).toContain("result.action === 'created'")
    expect(source).toContain('same file')
    expect(settingsSource).toContain("hostname: 'accounts.google.com'")
    expect(settingsSource).toContain("pathname: '/o/oauth2/v2/auth'")
    expect(source).toContain('latexContent !== undefined')
    expect(source).not.toContain('access_token')
    expect(source).not.toContain('refresh_token')
  })
})
