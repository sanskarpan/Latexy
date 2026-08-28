import { describe, expect, it } from 'vitest'

import { TEMPLATE_CATEGORY_ORDER } from '@/lib/template-categories'

describe('template gallery categories', () => {
  it('keeps the shipped presentation templates discoverable', () => {
    expect(TEMPLATE_CATEGORY_ORDER).toContain('presentation')
    expect(new Set(TEMPLATE_CATEGORY_ORDER).size).toBe(TEMPLATE_CATEGORY_ORDER.length)
  })
})
