import { expect, it } from 'vitest'

import { metadata } from '../app/page'

it('publishes the approved Search Console proof only through homepage metadata', () => {
  expect(metadata).toEqual({
    verification: {
      google: '-JuXguMIM_kaznXdcKY8ygd7x6Iuhndu1xvV3_arsHs',
    },
  })
})
