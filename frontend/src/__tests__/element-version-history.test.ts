import { readFileSync } from 'node:fs'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../lib/api-client'
import { applyRestoredBullet, reconcileBulletIds, safeBuilderIdentity } from '../lib/resume-builder'

const PANEL_SOURCE = readFileSync(
  new URL('../components/ElementVersionHistoryPanel.tsx', import.meta.url),
  'utf8',
)

function mockFetch(body: unknown, status = 200) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    headers: {},
    json: () => Promise.resolve(body),
    text: () => Promise.resolve(body == null ? '' : JSON.stringify(body)),
  }))
}

afterEach(() => {
  apiClient.setAuthToken(null)
  vi.unstubAllGlobals()
})

describe('per-element version API client', () => {
  it('uses encoded resume and element ids and supports pagination', async () => {
    mockFetch({ items: [], next_cursor: 'opaque' })
    await apiClient.getResumeElementVersions('resume/id', 'experience:one:bullet:0', { limit: 20, cursor: 'next/token' })
    const [url] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit]
    expect(url).toContain('/resumes/resume%2Fid/element-versions')
    expect(url).toContain('element_key=experience%3Aone%3Abullet%3A0')
    expect(url).toContain('cursor=next%2Ftoken')
  })

  it('exposes immutable create, restore, and fork operations', async () => {
    mockFetch({})
    await apiClient.createResumeElementVersion('r', {
      element_key: 'experience:one:bullet:0',
      content: 'A version',
      expected_head_version_id: 'head',
      source: 'ai',
      operation: 'edit',
    })
    expect(vi.mocked(fetch).mock.calls[0][1]).toMatchObject({ method: 'POST' })

    mockFetch({})
    await apiClient.restoreResumeElementVersion('r', 'v', 'head')
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/v/restore')

    mockFetch({})
    await apiClient.forkResumeElementVersion('r', 'v', 'head')
    expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/v/fork')
  })
})

describe('per-element history UI contract', () => {
  it('labels restore as a new snapshot and discloses tracker evidence limits', () => {
    expect(PANEL_SOURCE).toContain('Restore creates a new snapshot; it never erases history.')
    expect(PANEL_SOURCE).toContain('not proof this version caused an interview')
    expect(PANEL_SOURCE).toContain('Link tracker evidence (optional)')
    expect(PANEL_SOURCE).toContain('No application linked')
  })

  it('reconciles edits, insertions, deletions, reorders, and duplicate lines without positional drift', () => {
    const previous = ['Alpha', 'Beta', 'Gamma']
    const ids = ['a', 'b', 'c']
    expect(reconcileBulletIds(previous, ids, ['Alpha revised', 'Beta', 'Gamma'], 'entry')).toEqual(['a', 'b', 'c'])
    const inserted = reconcileBulletIds(previous, ids, ['Alpha', 'Inserted', 'Beta', 'Gamma'], 'entry')
    expect(inserted[0]).toBe('a'); expect(inserted[2]).toBe('b'); expect(inserted[3]).toBe('c'); expect(new Set(inserted).size).toBe(4)
    expect(reconcileBulletIds(previous, ids, ['Alpha', 'Gamma'], 'entry')).toEqual(['a', 'c'])
    expect(reconcileBulletIds(previous, ids, ['Gamma', 'Alpha', 'Beta'], 'entry')).toEqual(['c', 'a', 'b'])
    const duplicate = reconcileBulletIds(['Same', 'Same'], ['same-a', 'same-b'], ['Same', 'Same'], 'entry')
    expect(duplicate).toEqual(['same-a', 'same-b'])
    expect(new Set(duplicate).size).toBe(2)
  })

  it('does not let malformed imported IDs enter API element keys', () => {
    const safe = safeBuilderIdentity('entry with spaces/controls/and-a-very-long-tail-' + 'x'.repeat(220))
    expect(safe).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/)
    const ids = reconcileBulletIds(['one', 'two'], ['bad id', 'same'], ['one', 'two'], 'entry with spaces')
    expect(ids).toHaveLength(2)
    expect(new Set(ids).size).toBe(2)
    expect(ids.every(id => /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/.test(id))).toBe(true)
  })

  it('restores the selected experience/project bullet by explicit identity', () => {
    const resume = {
      basics: { name: '', label: '', email: '', phone: '', location: '', website: '', linkedin: '', github: '', summary: '' },
      experience: [{ id: 'exp:one', title: 'Role', company: 'Acme', location: '', start_date: '', end_date: '', current: false, summary: '', bullets: ['keep', 'change'], bullet_ids: ['bullet:a', 'bullet:b'], technologies: [] }],
      education: [], projects: [{ id: 'proj', name: 'Project', role: '', url: '', start_date: '', end_date: '', description: '', bullets: ['project'], bullet_ids: ['bullet:p'], technologies: [] }],
      skills: [], certifications: [], awards: [], languages: [], interests: [], section_order: [], hidden_sections: [],
    }
    expect(applyRestoredBullet(resume, 'experience', 'exp:one', 'bullet:b', 'restored')).toBe(true)
    expect(resume.experience[0].bullets).toEqual(['keep', 'restored'])
    expect(applyRestoredBullet(resume, 'project', 'proj', 'bullet:p', 'project restored')).toBe(true)
    expect(resume.projects[0].bullets).toEqual(['project restored'])
    expect(applyRestoredBullet(resume, 'experience', 'exp:one', 'bullet:b', 'stale restore', 'change')).toBe(false)
    expect(resume.experience[0].bullets).toEqual(['keep', 'restored'])
  })
})
