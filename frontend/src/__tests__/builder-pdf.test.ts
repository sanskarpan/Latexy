import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BuilderResumeResponse } from '@/lib/api-client'

const fixture = vi.hoisted(() => ({
  cleanups: [] as (() => void)[],
  api: { compileLatex: vi.fn(), getJobState: vi.fn(), getJobResult: vi.fn(), downloadPdf: vi.fn() },
  download: vi.fn(),
}))
vi.mock('react', () => ({
  useState: (value: unknown) => [value, vi.fn()],
  useRef: (value: unknown) => ({ current: value }),
  useCallback: (callback: unknown) => callback,
  useEffect: (effect: () => (() => void) | void) => {
    const cleanup = effect()
    if (cleanup) fixture.cleanups.push(cleanup)
  },
}))
vi.mock('@/lib/api-client', () => ({ apiClient: fixture.api }))
vi.mock('@/lib/download', () => ({ downloadBlob: fixture.download }))
// React's hooks are mocked above; this harness executes the production closure.
import { useBuilderPdf as createPdfHarness } from '@/hooks/useBuilderPdf'

const saved = {
  resume: { id: 'resume-owned', title: 'Alex résumé', structured_version: 4, latex_content: 'saved source', metadata: { compiler: 'lualatex' } },
} as unknown as BuilderResumeResponse

function setup(prepare = vi.fn().mockResolvedValue(saved), isCurrent = () => true) {
  fixture.api.compileLatex.mockResolvedValue({ success: true, job_id: 'job-owned' })
  fixture.api.getJobState.mockResolvedValue({ job_id: 'job-owned', status: 'completed' })
  fixture.api.getJobResult.mockResolvedValue({ success: true, job_id: 'job-owned', pdf_job_id: 'job-owned' })
  fixture.api.downloadPdf.mockResolvedValue(new Blob(['%PDF-1.7'], { type: 'application/pdf' }))
  vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:owned-preview')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
  return createPdfHarness({ resumeId: 'resume-owned', prepareResume: prepare, isCurrent })
}

afterEach(() => {
  fixture.cleanups.splice(0).forEach(cleanup => cleanup())
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe('guided builder PDF completion', () => {
  it('saves first, compiles the exact revision, and downloads its owned output', async () => {
    const prepare = vi.fn().mockResolvedValue(saved)
    const hook = setup(prepare)
    await hook.downloadPdf()
    expect(prepare.mock.invocationCallOrder[0]).toBeLessThan(fixture.api.compileLatex.mock.invocationCallOrder[0])
    expect(fixture.api.compileLatex).toHaveBeenCalledWith({ latex_content: 'saved source', resume_id: 'resume-owned', compiler: 'lualatex' })
    expect(fixture.api.downloadPdf).toHaveBeenCalledWith('job-owned', expect.any(AbortSignal))
    expect(fixture.download).toHaveBeenCalledWith(expect.any(Blob), 'Alex résumé.pdf')
  })
  it('reuses a preview only for the same saved version and content', async () => {
    const hook = setup()
    await hook.previewPdf()
    await hook.previewPdf()
    await hook.downloadPdf()
    expect(fixture.api.compileLatex).toHaveBeenCalledTimes(1)
    expect(fixture.download).toHaveBeenCalledTimes(1)
    hook.clearPreview()
    await hook.downloadPdf()
    expect(fixture.api.compileLatex).toHaveBeenCalledTimes(2)
  })
  it('prepares a new PDF after the saved revision changes instead of using an old preview', async () => {
    const prepare = vi.fn().mockResolvedValue(saved)
    const hook = setup(prepare)
    await hook.previewPdf()
    prepare.mockResolvedValue({ resume: { ...saved.resume, structured_version: 5, latex_content: 'updated source' } })
    await hook.previewPdf()
    expect(fixture.api.compileLatex).toHaveBeenCalledTimes(2)
    expect(fixture.api.compileLatex).toHaveBeenLastCalledWith({ latex_content: 'updated source', resume_id: 'resume-owned', compiler: 'lualatex' })
    await hook.downloadPdf()
    expect(fixture.api.compileLatex).toHaveBeenCalledTimes(2)
  })
  it('does not reuse a PDF when content differs even if the version number is unchanged', async () => {
    const prepare = vi.fn().mockResolvedValue(saved)
    const hook = setup(prepare)
    await hook.previewPdf()
    prepare.mockResolvedValue({ resume: { ...saved.resume, latex_content: 'different source' } })
    await hook.previewPdf()
    expect(fixture.api.compileLatex).toHaveBeenCalledTimes(2)
  })
  it('does not compile when saving fails', async () => {
    const hook = setup(vi.fn().mockRejectedValue(new Error('save conflict')))
    await expect(hook.downloadPdf()).rejects.toThrow('save conflict')
    expect(fixture.api.compileLatex).not.toHaveBeenCalled()
  })
  it('rejects a different document returned while preparing', async () => {
    const hook = setup(vi.fn().mockResolvedValue({ resume: { ...saved.resume, id: 'another-resume' } }))
    await expect(hook.previewPdf()).rejects.toThrow('Save your resume')
    expect(fixture.api.compileLatex).not.toHaveBeenCalled()
  })
  it('rejects mismatched PDF artifact identities', async () => {
    const hook = setup()
    fixture.api.getJobResult.mockResolvedValue({ success: true, job_id: 'job-owned', pdf_job_id: 'unrelated-job' })
    await expect(hook.downloadPdf()).rejects.toThrow('PDF output is unavailable')
    expect(fixture.api.downloadPdf).not.toHaveBeenCalled()
  })
  it('does not download failed compilation output', async () => {
    const hook = setup()
    fixture.api.getJobState.mockResolvedValue({ job_id: 'job-owned', status: 'failed' })
    await expect(hook.downloadPdf()).rejects.toThrow('Your saved resume is safe')
    expect(fixture.api.downloadPdf).not.toHaveBeenCalled()
  })
  it('discards late output after the draft is changed', async () => {
    const hook = setup()
    fixture.api.compileLatex.mockImplementation(async () => {
      hook.clearPreview()
      return { success: true, job_id: 'job-owned' }
    })
    await expect(hook.downloadPdf()).rejects.toThrow('changed')
    expect(fixture.api.getJobState).not.toHaveBeenCalled()
    expect(fixture.download).not.toHaveBeenCalled()
  })
  it('discards output when the authenticated owner changes', async () => {
    let current = true
    const hook = setup(vi.fn().mockImplementation(async () => { current = false; return saved }), () => current)
    await expect(hook.downloadPdf()).rejects.toThrow('changed')
    expect(fixture.api.compileLatex).not.toHaveBeenCalled()
  })
})
