import { describe, expect, test } from 'vitest'
import { diffRenderedPixels } from '../lib/rendered-pdf-diff'

const WHITE = [255, 255, 255, 255]
const BLACK = [0, 0, 0, 255]

describe('rendered PDF pixel diff', () => {
  test('classifies added and removed ink without flagging unchanged pixels', () => {
    const before = new Uint8ClampedArray([...WHITE, ...BLACK, ...WHITE])
    const after = new Uint8ClampedArray([...BLACK, ...WHITE, ...WHITE])

    const result = diffRenderedPixels(before, after)

    expect(result).toMatchObject({
      changedPixels: 2,
      addedPixels: 1,
      removedPixels: 1,
      modifiedPixels: 0,
    })
    expect(Array.from(result.pixels.slice(0, 4))).toEqual([22, 163, 74, 255])
    expect(Array.from(result.pixels.slice(4, 8))).toEqual([220, 38, 38, 255])
  })

  test('classifies color-only changes separately and honors the noise threshold', () => {
    const before = new Uint8ClampedArray([100, 20, 20, 255, 250, 250, 250, 255])
    const after = new Uint8ClampedArray([20, 100, 20, 255, 245, 245, 245, 255])

    const result = diffRenderedPixels(before, after, 10)

    expect(result).toMatchObject({
      changedPixels: 1,
      addedPixels: 0,
      removedPixels: 0,
      modifiedPixels: 1,
    })
    expect(Array.from(result.pixels.slice(0, 4))).toEqual([217, 119, 6, 255])
  })

  test('rejects mismatched or non-RGBA buffers', () => {
    expect(() => diffRenderedPixels(new Uint8ClampedArray(4), new Uint8ClampedArray(8))).toThrow()
    expect(() => diffRenderedPixels(new Uint8ClampedArray(3), new Uint8ClampedArray(3))).toThrow()
  })
})
