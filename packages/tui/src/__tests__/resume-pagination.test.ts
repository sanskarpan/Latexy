import { beforeEach, describe, expect, it, vi } from 'vitest'

const getMock = vi.fn()

vi.mock('../lib/api-client.js', () => ({
  getApiClient: () => ({ get: getMock }),
}))

describe('resume pagination', () => {
  beforeEach(() => {
    getMock.mockReset()
  })

  it('loads every API page so older resumes remain selectable', async () => {
    getMock
      .mockResolvedValueOnce({
        resumes: [{ id: 'resume-1', title: 'Newest', updated_at: '2026-08-31T00:00:00Z' }],
        total: 201,
        page: 1,
        pages: 3,
      })
      .mockResolvedValueOnce({
        resumes: [{ id: 'resume-101', title: 'Middle', updated_at: '2026-08-30T00:00:00Z' }],
        total: 201,
        page: 2,
        pages: 3,
      })
      .mockResolvedValueOnce({
        resumes: [{ id: 'resume-201', title: 'Oldest', updated_at: '2026-08-29T00:00:00Z' }],
        total: 201,
        page: 3,
        pages: 3,
      })

    const { listAllResumes } = await import('../tools/shared.js')
    const result = await listAllResumes()

    expect(result.total).toBe(201)
    expect(result.resumes.map(resume => resume.id)).toEqual([
      'resume-1',
      'resume-101',
      'resume-201',
    ])
    expect(getMock).toHaveBeenNthCalledWith(1, '/resumes/?page=1&limit=100')
    expect(getMock).toHaveBeenNthCalledWith(2, '/resumes/?page=2&limit=100')
    expect(getMock).toHaveBeenNthCalledWith(3, '/resumes/?page=3&limit=100')
  })

  it('preserves archive and document-type filters on every page', async () => {
    getMock
      .mockResolvedValueOnce({ resumes: [], total: 101, pages: 2 })
      .mockResolvedValueOnce({ resumes: [], total: 101, pages: 2 })

    const { listAllResumes } = await import('../tools/shared.js')
    await listAllResumes({ archived: true, documentType: 'academic_cv' })

    expect(getMock).toHaveBeenNthCalledWith(
      1,
      '/resumes/?page=1&limit=100&archived=true&document_type=academic_cv',
    )
    expect(getMock).toHaveBeenNthCalledWith(
      2,
      '/resumes/?page=2&limit=100&archived=true&document_type=academic_cv',
    )
  })
})
