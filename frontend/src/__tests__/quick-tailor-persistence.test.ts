import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const MODAL_SOURCE = readFileSync(
  new URL('../components/QuickTailorModal.tsx', import.meta.url),
  'utf8',
)

describe('Quick Tailor persistence ownership', () => {
  it('does not make the browser authoritative for saving worker output', () => {
    expect(MODAL_SOURCE).not.toContain('apiClient.updateResume(forkId')
    expect(MODAL_SOURCE).toContain('worker\'s owner-scoped persistence')
  })

  it('keeps ordinary dismissal separate from explicit cancellation', () => {
    expect(MODAL_SOURCE).toContain('const handleCancel')
    expect(MODAL_SOURCE).toContain('const handleDismiss')
    expect(MODAL_SOURCE).toContain('tailoring will continue in the background')
    expect(MODAL_SOURCE).not.toContain("if (step === 'progress') {\n      handleCancel()")
  })
})
