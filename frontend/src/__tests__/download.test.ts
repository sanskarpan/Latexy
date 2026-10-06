import { afterEach, describe, expect, it, vi } from 'vitest'

import { downloadBlob } from '../lib/download'

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('downloadBlob', () => {
  it('waits before revoking the object URL so the browser can consume it', () => {
    vi.useFakeTimers()
    const click = vi.fn()
    const remove = vi.fn()
    const appendChild = vi.fn()
    const anchor = { href: '', download: '', click, remove }
    const createObjectURL = vi.fn(() => 'blob:download')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    vi.stubGlobal('document', {
      createElement: vi.fn(() => anchor),
      body: { appendChild },
    })

    downloadBlob(new Blob(['content']), 'resume.pdf')

    expect(anchor).toMatchObject({ href: 'blob:download', download: 'resume.pdf' })
    expect(appendChild).toHaveBeenCalledWith(anchor)
    expect(click).toHaveBeenCalledOnce()
    expect(remove).toHaveBeenCalledOnce()
    expect(revokeObjectURL).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1000)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:download')
  })
})
