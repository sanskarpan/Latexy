import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient, type PaginatedResumesResponse } from '../lib/api-client'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('apiClient.listAllResumes', () => {
  it('loads every page in order so library and picker surfaces exceed 20 rows', async () => {
    const page = (pageNumber: number, pages: number, ids: string[]): PaginatedResumesResponse => ({
      resumes: ids.map((id) => ({ id, title: id }) as PaginatedResumesResponse['resumes'][number]),
      total: 401,
      page: pageNumber,
      limit: 200,
      pages,
    })
    const list = vi.spyOn(apiClient, 'listResumesPaginated')
      .mockResolvedValueOnce(page(1, 3, ['r1']))
      .mockResolvedValueOnce(page(2, 3, ['r201']))
      .mockResolvedValueOnce(page(3, 3, ['r401']))

    await expect(apiClient.listAllResumes()).resolves.toMatchObject([
      { id: 'r1' },
      { id: 'r201' },
      { id: 'r401' },
    ])
    expect(list.mock.calls).toEqual([
      [1, 200, false],
      [2, 200, false],
      [3, 200, false],
    ])
  })

  it('preserves archived filtering across every page', async () => {
    const list = vi.spyOn(apiClient, 'listResumesPaginated')
      .mockResolvedValueOnce({ resumes: [], total: 201, page: 1, limit: 200, pages: 2 })
      .mockResolvedValueOnce({ resumes: [], total: 201, page: 2, limit: 200, pages: 2 })

    await apiClient.listAllResumes(true)

    expect(list.mock.calls).toEqual([
      [1, 200, true],
      [2, 200, true],
    ])
  })
})
