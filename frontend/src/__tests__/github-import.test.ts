import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, describe, expect, test, vi } from 'vitest'

import { apiClient, type ProjectEvidence } from '../lib/api-client'
import {
  escapeLatex,
  insertProjectLatex,
  projectsToLatex,
} from '../lib/github-projects-latex'

const SETTINGS_SOURCE = readFileSync(
  fileURLToPath(new URL('../app/settings/page.tsx', import.meta.url)),
  'utf8'
)

function mockFetch(responseBody: object) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      statusText: 'OK',
      headers: {},
      json: () => Promise.resolve(responseBody),
      text: () => Promise.resolve(JSON.stringify(responseBody)),
    })
  )
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

const PROJECT: ProjectEvidence = {
  source: 'github',
  title: 'my_project',
  description: 'A cool tool for R&D',
  tech: ['Python', 'FastAPI'],
  metrics: { stars: 42, forks: 3 },
  dates: { last_active: '2026-01-01T00:00:00Z' },
  url: 'https://github.com/me/my_project',
  suggested_bullets: ['Built X, cutting latency 30%', 'Shipped Y to 10k users'],
  raw_excerpt: '',
}

describe('escapeLatex', () => {
  test('escapes LaTeX special characters', () => {
    expect(escapeLatex('R&D')).toBe('R\\&D')
    expect(escapeLatex('my_project')).toBe('my\\_project')
    expect(escapeLatex('100% #1 $x')).toBe('100\\% \\#1 \\$x')
    expect(escapeLatex('a~b^c')).toBe('a\\textasciitilde{}b\\textasciicircum{}c')
  })

  test('escapes backslash before other specials to avoid double-escaping', () => {
    expect(escapeLatex('a\\b')).toBe('a\\textbackslash{}b')
  })
})

describe('projectsToLatex', () => {
  test('returns empty string for no selections', () => {
    expect(projectsToLatex([])).toBe('')
  })

  test('renders a project with escaped title, tech, repo link, and kept bullets', () => {
    const out = projectsToLatex([{ project: PROJECT, bullets: PROJECT.suggested_bullets }])
    expect(out).toContain('\\textbf{my\\_project}')
    expect(out).toContain('\\href{https://github.com/me/my_project}')
    expect(out).toContain('\\textit{Python, FastAPI}')
    expect(out).toContain('\\begin{itemize}')
    expect(out).toContain('\\item Built X, cutting latency 30\\%')
    expect(out).toContain('imported from GitHub')
  })

  test('falls back to description when no bullets are kept', () => {
    const out = projectsToLatex([{ project: PROJECT, bullets: [] }])
    expect(out).not.toContain('\\begin{itemize}')
    expect(out).toContain('A cool tool for R\\&D')
  })

  test('omits a non-http url (no href injection)', () => {
    const out = projectsToLatex([
      { project: { ...PROJECT, url: 'javascript:alert(1)' }, bullets: ['did a thing'] },
    ])
    expect(out).not.toContain('\\href')
    expect(out).toContain('\\item did a thing')
  })

  test('separates multiple projects with a smallskip', () => {
    const out = projectsToLatex([
      { project: PROJECT, bullets: ['one'] },
      { project: { ...PROJECT, title: 'second' }, bullets: ['two'] },
    ])
    expect(out).toContain('\\smallskip')
    expect(out).toContain('\\textbf{second}')
  })
})

describe('insertProjectLatex', () => {
  test('inserts at the editor cursor and returns the complete buffer', () => {
    let buffer = 'before-after'
    const cursor = 7
    const editor = {
      insertAtCursor: vi.fn((snippet: string) => {
        buffer = `${buffer.slice(0, cursor)}${snippet}${buffer.slice(cursor)}`
      }),
      getValue: vi.fn(() => buffer),
    }

    const result = insertProjectLatex(editor, 'stale state', 'PROJECT')

    expect(editor.insertAtCursor).toHaveBeenCalledWith('PROJECT')
    expect(result).toBe('before-PROJECTafter')
  })

  test('appends safely when the editor is temporarily unavailable', () => {
    expect(insertProjectLatex(null, 'existing resume', 'PROJECT')).toBe(
      'existing resume\nPROJECT'
    )
    expect(insertProjectLatex(null, 'existing resume\n', 'PROJECT')).toBe(
      'existing resume\nPROJECT'
    )
  })

  test('ignores an empty snippet without touching the editor', () => {
    const editor = {
      insertAtCursor: vi.fn(),
      getValue: vi.fn(() => 'changed'),
    }

    expect(insertProjectLatex(editor, 'existing resume', '')).toBe('existing resume')
    expect(editor.insertAtCursor).not.toHaveBeenCalled()
    expect(editor.getValue).not.toHaveBeenCalled()
  })
})

describe('GitHub import client', () => {
  test('importGitHubProjects POSTs and returns a job id', async () => {
    mockFetch({ job_id: 'gh-job-1' })
    const res = await apiClient.importGitHubProjects()
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/github/import-projects')
    expect(init.method).toBe('POST')
    expect(res.job_id).toBe('gh-job-1')
  })

  test('getGitHubImportResult GETs the job status envelope', async () => {
    mockFetch({ status: 'completed', projects: [PROJECT], error: null })
    const res = await apiClient.getGitHubImportResult('gh-job-1')
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/github/import-projects/gh-job-1')
    expect(res.status).toBe('completed')
    expect(res.projects[0].title).toBe('my_project')
  })
})

describe('GitHub OAuth client', () => {
  test('settings uses the authenticated two-step handshake', () => {
    expect(SETTINGS_SOURCE).toContain('apiClient.startGitHubOAuth()')
    expect(SETTINGS_SOURCE).toContain('apiClient.completeGitHubOAuth(ticket)')
    expect(SETTINGS_SOURCE).toContain('if (!sessionData)')
    expect(SETTINGS_SOURCE).toContain('window.location.assign(authorizationUrl)')
    expect(SETTINGS_SOURCE).not.toContain('`${API_BASE}/github/connect`')
  })

  test('starts OAuth through an authenticated POST and returns the provider URL', async () => {
    mockFetch({ authorization_url: 'https://github.com/login/oauth/authorize?state=opaque' })
    apiClient.setAuthToken('latexy-session')

    const result = await apiClient.startGitHubOAuth()

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/github/connect')
    expect(init.method).toBe('POST')
    expect((init.headers as Record<string, string>).Authorization).toBe(
      'Bearer latexy-session'
    )
    expect(result.authorization_url).toContain('github.com/login/oauth/authorize')
  })

  test('completes a one-time ticket through the authenticated API', async () => {
    mockFetch({ success: true, message: 'GitHub account connected' })
    apiClient.setAuthToken('latexy-session')

    await apiClient.completeGitHubOAuth('one-time-ticket')

    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/github/complete')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ ticket: 'one-time-ticket' })
    expect((init.headers as Record<string, string>).Authorization).toBe(
      'Bearer latexy-session'
    )
    expect(String(init.body)).not.toContain('latexy-session')
  })
})
