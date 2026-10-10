import { describe, expect, it } from 'vitest'
import { GUIDED_BUILDER_VERSION, supportsGuidedBuilder } from '@/lib/builder-capabilities'

describe('guided builder capability contract', () => {
  it('accepts only the explicit supported version', () => {
    expect(supportsGuidedBuilder({ guided_builder_version: GUIDED_BUILDER_VERSION })).toBe(true)
  })

  it.each([undefined, null, {}, false, [], { guided_builder_version: 0 },
    { guided_builder_version: '1' }, { guided_builder_version: true },
    { guided_builder_version: 2 }, { guided_builder_version: 1.5 }])('fails closed for %j', value => {
    expect(supportsGuidedBuilder(value)).toBe(false)
  })
})
