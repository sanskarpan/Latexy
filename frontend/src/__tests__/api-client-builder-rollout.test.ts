import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiClient } from '@/lib/api-client'

const response = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), {
  status, headers: { 'content-type': 'application/json' },
})
const actions = {
  create: () => apiClient.createBuilderResume({ title: 'Resume', template_id: 'template' }),
  get: () => apiClient.getBuilderResume('resume/id'),
  update: () => apiClient.updateBuilderResume('resume/id', { expected_structured_version: 4 }),
  seed: () => apiClient.seedBuilderFromUpload(new File(['Resume'], 'resume.txt', { type: 'text/plain' })),
  pdf: () => apiClient.exportResume('resume/id', 'pdf', true),
  docx: () => apiClient.exportResume('resume/id', 'docx', true),
  canva: () => apiClient.exportCanva('resume/id', true),
  figma: () => apiClient.exportFigma('resume/id', true),
}
const paths = {
  create: '/resumes/builder/v1',
  get: '/resumes/resume%2Fid/builder/v1',
  update: '/resumes/resume%2Fid/builder/v1',
  seed: '/resumes/builder/v1/seed-upload',
  pdf: '/export/builder/v1/resume%2Fid/pdf',
  docx: '/export/builder/v1/resume%2Fid/docx',
  canva: '/export/builder/v1/resume%2Fid/canva',
  figma: '/export/builder/v1/resume%2Fid/figma',
}

afterEach(() => {
  vi.unstubAllGlobals()
  apiClient.setAuthToken(null)
})

describe('guided builder staged rollout API', () => {
  it('reads explicit builder capabilities without cached readiness', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(response({ guided_builder_version: 1 }))
    vi.stubGlobal('fetch', fetch)
    expect(await apiClient.getBuilderCapabilities()).toEqual({ guided_builder_version: 1 })
    expect(new URL(fetch.mock.calls[0][0], 'http://localhost').pathname).toBe('/resumes/builder/capabilities')
    expect(fetch.mock.calls[0][1].cache).toBe('no-store')
  })

  it.each(Object.keys(actions) as Array<keyof typeof actions>)(
    '%s uses a new-only route and never falls back when a rolling old instance returns 404', async action => {
      const fetch = vi.fn().mockResolvedValueOnce(response({ detail: 'Not Found' }, 404))
      vi.stubGlobal('fetch', fetch)
      apiClient.setAuthToken('owner-token')
      await expect(actions[action]()).rejects.toThrow('Not Found')
      expect(fetch).toHaveBeenCalledTimes(1)
      expect(new URL(fetch.mock.calls[0][0], 'http://localhost').pathname).toBe(paths[action])
    },
  )

  it('preserves general source-editor export routes by default', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(response({})))
    vi.stubGlobal('fetch', fetch)
    await apiClient.exportResume('resume-id', 'pdf')
    await apiClient.exportCanva('resume-id')
    await apiClient.exportFigma('resume-id')
    expect(fetch.mock.calls.map(([url]) => new URL(url, 'http://localhost').pathname)).toEqual([
      '/export/resume-id/pdf', '/export/resume-id/canva', '/export/resume-id/figma',
    ])
  })
})
