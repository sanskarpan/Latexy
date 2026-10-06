export interface RenderedDiffResult {
  pixels: Uint8ClampedArray
  changedPixels: number
  addedPixels: number
  removedPixels: number
  modifiedPixels: number
}

/**
 * Compare two equally-sized, opaque RGBA page rasters.
 *
 * The output keeps the newer page as a faint grayscale backdrop and marks ink
 * added in green, removed in red, and otherwise changed in amber. This is a
 * presentation diff: source-level accept/reject remains a separate workflow.
 */
export function diffRenderedPixels(
  before: Uint8ClampedArray,
  after: Uint8ClampedArray,
  threshold = 32,
): RenderedDiffResult {
  if (before.length !== after.length || before.length % 4 !== 0) {
    throw new Error('Rendered page buffers must have equal RGBA dimensions')
  }

  const pixels = new Uint8ClampedArray(after.length)
  let changedPixels = 0
  let addedPixels = 0
  let removedPixels = 0
  let modifiedPixels = 0

  for (let i = 0; i < after.length; i += 4) {
    const beforeR = before[i]
    const beforeG = before[i + 1]
    const beforeB = before[i + 2]
    const afterR = after[i]
    const afterG = after[i + 1]
    const afterB = after[i + 2]
    const channelDelta = Math.max(
      Math.abs(beforeR - afterR),
      Math.abs(beforeG - afterG),
      Math.abs(beforeB - afterB),
      Math.abs(before[i + 3] - after[i + 3]),
    )

    if (channelDelta <= threshold) {
      const gray = Math.round((afterR + afterG + afterB) / 3)
      const faded = Math.round(224 + gray * 0.12)
      pixels.set([faded, faded, faded, 255], i)
      continue
    }

    changedPixels += 1
    const beforeInk = 255 - (beforeR + beforeG + beforeB) / 3
    const afterInk = 255 - (afterR + afterG + afterB) / 3
    if (afterInk - beforeInk > threshold) {
      addedPixels += 1
      pixels.set([22, 163, 74, 255], i)
    } else if (beforeInk - afterInk > threshold) {
      removedPixels += 1
      pixels.set([220, 38, 38, 255], i)
    } else {
      modifiedPixels += 1
      pixels.set([217, 119, 6, 255], i)
    }
  }

  return { pixels, changedPixels, addedPixels, removedPixels, modifiedPixels }
}
