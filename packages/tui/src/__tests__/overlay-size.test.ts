import { describe, expect, it } from 'vitest'
import { measureOverlaySize } from '../lib/overlay-size.js'

describe('measureOverlaySize', () => {
  it('keeps overlays inside a 40-column terminal after AppShell margins', () => {
    expect(measureOverlaySize(24, 40)).toEqual({ rows: 6, width: 30 })
  })

  it('caps overlays on large terminals', () => {
    expect(measureOverlaySize(80, 160)).toEqual({ rows: 10, width: 72 })
  })

  it('uses stable fallback dimensions when a stream omits its size', () => {
    expect(measureOverlaySize()).toEqual({ rows: 6, width: 70 })
  })
})
