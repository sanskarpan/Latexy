/**
 * Unit tests for P2 Feature 69 — Multi-Resume Merge
 *
 * 69A — parseLatexSections (client-side section detection)
 * 69B — mergeResumes API client method (request shape)
 * 69C — section defaults logic (all-sections default to first selected)
 */

import { describe, test, expect, vi, afterEach } from 'vitest'
import { apiClient } from '../lib/api-client'

// ─────────────────────────────────────────────────────────────────────────────
// Replicate parseLatexSections verbatim from workspace/merge/page.tsx
// ─────────────────────────────────────────────────────────────────────────────

function parseLatexSections(latex: string): string[] {
  const matches = latex.matchAll(/\\section\*?\{([^}]+)\}/g)
  const names: string[] = []
  for (const m of matches) {
    if (!names.includes(m[1])) names.push(m[1])
  }
  return names
}

// ─────────────────────────────────────────────────────────────────────────────
// 69A · parseLatexSections
// ─────────────────────────────────────────────────────────────────────────────

const LATEX_A = String.raw`
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{Alice}\end{center}
\section*{Experience}
Software Engineer at Acme Corp, 2020--2023.
\section*{Skills}
Python, FastAPI, PostgreSQL.
\section*{Education}
B.Sc. Computer Science, MIT, 2020.
\end{document}
`.trim()

const LATEX_B = String.raw`
\documentclass[11pt]{article}
\begin{document}
\begin{center}\textbf{Bob}\end{center}
\section*{Experience}
Data Scientist at DataCo, 2021--2023.
\section*{Skills}
Python, TensorFlow, PyTorch.
\section*{Projects}
Built an ML pipeline handling 10M events/day.
\end{document}
`.trim()

describe('Feature 69 · parseLatexSections', () => {
  test('extracts starred section names in order', () => {
    const sections = parseLatexSections(LATEX_A)
    expect(sections).toEqual(['Experience', 'Skills', 'Education'])
  })

  test('extracts unstarred \\section{} as well as \\section*{}', () => {
    const latex = String.raw`\begin{document}\section{Work}stuff.\section*{Skills}more.\end{document}`
    expect(parseLatexSections(latex)).toEqual(['Work', 'Skills'])
  })

  test('returns empty array when no sections present', () => {
    const latex = String.raw`\begin{document}\begin{center}Name\end{center}\end{document}`
    expect(parseLatexSections(latex)).toEqual([])
  })

  test('deduplicates repeated section names', () => {
    const latex = String.raw`\begin{document}\section*{Skills}a.\section*{Skills}b.\end{document}`
    expect(parseLatexSections(latex)).toEqual(['Skills'])
  })

  test('handles section name with spaces', () => {
    const latex = String.raw`\begin{document}\section*{Work Experience}content.\end{document}`
    expect(parseLatexSections(latex)).toEqual(['Work Experience'])
  })

  test('handles section name with special characters', () => {
    const latex = String.raw`\begin{document}\section*{Awards \& Honors}content.\end{document}`
    expect(parseLatexSections(latex)).toEqual(['Awards \\& Honors'])
  })

  test('returns correct union of sections from two resumes', () => {
    const secA = parseLatexSections(LATEX_A)
    const secB = parseLatexSections(LATEX_B)
    const union = Array.from(new Set([...secA, ...secB]))
    expect(union).toContain('Experience')
    expect(union).toContain('Skills')
    expect(union).toContain('Education')
    expect(union).toContain('Projects')
    expect(union).toHaveLength(4)
  })

  test('section order preserves source order', () => {
    const latex = String.raw`\begin{document}\section*{Z}z.\section*{A}a.\section*{M}m.\end{document}`
    expect(parseLatexSections(latex)).toEqual(['Z', 'A', 'M'])
  })

  test('empty string returns empty array', () => {
    expect(parseLatexSections('')).toEqual([])
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 69B · mergeResumes API client — request shape
// ─────────────────────────────────────────────────────────────────────────────

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Feature 69 · mergeResumes API client', () => {
  function mockFetch(responseBody: object, status = 200) {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 200 ? 'OK' : 'Error',
        json: () => Promise.resolve(responseBody),
        text: () => Promise.resolve(JSON.stringify(responseBody)),
      })
    )
  }

  test('sends POST to /resumes/merge with correct body', async () => {
    const expected = { merged_latex: '\\documentclass{article}...', new_resume_id: 'new-123' }
    mockFetch(expected)

    const result = await apiClient.mergeResumes(['id-a', 'id-b'], { Skills: 'id-b' })

    const mockFn = vi.mocked(fetch)
    const [url, init] = mockFn.mock.calls[0] as [string, RequestInit]

    expect(url).toContain('/resumes/merge')
    expect(init.method).toBe('POST')

    const body = JSON.parse(init.body as string)
    expect(body.resume_ids).toEqual(['id-a', 'id-b'])
    expect(body.section_choices).toEqual({ Skills: 'id-b' })
  })

  test('returns merged_latex and new_resume_id from response', async () => {
    const expected = { merged_latex: 'merged content', new_resume_id: 'new-abc' }
    mockFetch(expected)

    const result = await apiClient.mergeResumes(['id-a', 'id-b'], {})
    expect(result.merged_latex).toBe('merged content')
    expect(result.new_resume_id).toBe('new-abc')
  })

  test('sends empty section_choices when none provided', async () => {
    mockFetch({ merged_latex: 'x', new_resume_id: 'y' })

    await apiClient.mergeResumes(['id-a', 'id-b'], {})

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string)
    expect(body.section_choices).toEqual({})
  })

  test('throws on non-ok HTTP response', async () => {
    mockFetch({ detail: 'Not found' }, 403)

    await expect(apiClient.mergeResumes(['a', 'b'], {})).rejects.toThrow('HTTP 403')
  })

  test('sends Authorization header when token is set', async () => {
    mockFetch({ merged_latex: 'x', new_resume_id: 'y' })
    apiClient.setAuthToken('test-token-xyz')

    await apiClient.mergeResumes(['id-a', 'id-b'], {})

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const headers = init.headers as Record<string, string>
    expect(headers['Authorization']).toBe('Bearer test-token-xyz')
  })

  test('encodes all 4 IDs when merging max resumes', async () => {
    mockFetch({ merged_latex: 'x', new_resume_id: 'new' })

    const ids = ['id-1', 'id-2', 'id-3', 'id-4']
    await apiClient.mergeResumes(ids, {})

    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    const body = JSON.parse(init.body as string)
    expect(body.resume_ids).toEqual(ids)
    expect(body.resume_ids).toHaveLength(4)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// 69C · Section defaults logic (no React — pure data logic)
// ─────────────────────────────────────────────────────────────────────────────

describe('Feature 69 · section defaults logic', () => {
  /** Mirrors the default-choice computation in the merge page's step-2 useEffect. */
  function computeDefaults(
    selected: string[],
    detectedSections: Record<string, string[]>
  ): Record<string, string> {
    const allSections = Array.from(new Set(Object.values(detectedSections).flat()))
    const defaults: Record<string, string> = {}
    for (const sec of allSections) {
      defaults[sec] = selected[0]
    }
    return defaults
  }

  test('all sections default to first selected resume', () => {
    const selected = ['id-a', 'id-b']
    const sections = { 'id-a': ['Experience', 'Skills'], 'id-b': ['Projects'] }
    const defaults = computeDefaults(selected, sections)
    expect(defaults['Experience']).toBe('id-a')
    expect(defaults['Skills']).toBe('id-a')
    expect(defaults['Projects']).toBe('id-a')
  })

  test('unique sections from all resumes are included', () => {
    const selected = ['id-a', 'id-b', 'id-c']
    const sections = {
      'id-a': ['Experience'],
      'id-b': ['Skills'],
      'id-c': ['Education', 'Awards'],
    }
    const defaults = computeDefaults(selected, sections)
    expect(Object.keys(defaults).sort()).toEqual(
      ['Awards', 'Education', 'Experience', 'Skills']
    )
  })

  test('duplicate section names across resumes appear only once', () => {
    const selected = ['id-a', 'id-b']
    const sections = { 'id-a': ['Skills', 'Education'], 'id-b': ['Skills', 'Projects'] }
    const defaults = computeDefaults(selected, sections)
    expect(Object.keys(defaults).filter(k => k === 'Skills')).toHaveLength(1)
  })

  test('empty sections map yields empty defaults', () => {
    expect(computeDefaults(['id-a', 'id-b'], {})).toEqual({})
  })
})
