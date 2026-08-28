import { describe, expect, it } from 'vitest'

import { shouldCloseTemplatePreview } from '@/lib/template-use'

describe('template use result contract', () => {
  it('keeps the preview open when creation did not succeed', () => {
    expect(shouldCloseTemplatePreview(false)).toBe(false)
  })

  it('closes after successful and legacy void callbacks', () => {
    expect(shouldCloseTemplatePreview(true)).toBe(true)
    expect(shouldCloseTemplatePreview(undefined)).toBe(true)
  })
})
