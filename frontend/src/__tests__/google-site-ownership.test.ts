import { expect, it, vi } from 'vitest'

import { metadata } from '../app/page'

// Next compiles localFont at build time; this test exercises metadata.
vi.mock('@/components/marketing/review-fonts', () => ({ reviewFonts: 'review-fonts' }))

it('publishes the approved Search Console proof only through homepage metadata', () => {
  expect(metadata.verification).toEqual({
    google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs',
  })
})
