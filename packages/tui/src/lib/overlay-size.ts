import { useEffect, useState } from 'react'
import { useStdout } from 'ink'

/**
 * Chrome an overlay costs beyond its list rows.
 *
 * Border, padding and marginY (6), title, filter field and their blank lines (5),
 * the "… N more" line and footer (2), plus what AppShell keeps below it: the
 * prompt box (3) and the hint line (1), and the status bar above (1).
 *
 * The first attempt at this used 8, which is roughly the overlay's own chrome and
 * ignores everything around it — so `min(10, rows - 8)` still returned the full 10
 * rows for any terminal taller than 18, and a 20-row terminal overflowed exactly
 * as before.
 */
const CHROME_ROWS = 18

/** Below this there is no arrangement that fits; show the minimum and let it clip. */
const MIN_ROWS = 2
const MAX_ROWS = 10

export interface OverlaySize {
  rows: number
  width: number
}

/**
 * Fit an overlay to the terminal, and follow it when the terminal changes.
 *
 * A fixed 10-row window and a fixed 60-column box overflowed a small terminal: at
 * 60x20 the picker drew a 37-line frame, so the title and the filter field
 * scrolled away and every keystroke re-emitted the whole thing.
 */
export function useOverlaySize(): OverlaySize {
  const { stdout } = useStdout()
  const measure = (): OverlaySize => {
    const termRows = stdout?.rows ?? 24
    const termCols = stdout?.columns ?? 80
    return {
      rows: Math.max(MIN_ROWS, Math.min(MAX_ROWS, termRows - CHROME_ROWS)),
      // AppShell wraps overlays in marginX={4}, so 8 columns are already spent.
      width: Math.max(28, Math.min(72, termCols - 10)),
    }
  }

  const [size, setSize] = useState<OverlaySize>(measure)

  // Reading stdout.rows during render alone left the overlay on stale dimensions
  // after a resize — borders drawn at the old width against newly-wrapped content
  // — until some other state change happened to force a re-render.
  useEffect(() => {
    if (stdout == null) return
    const onResize = (): void => { setSize(measure()) }
    stdout.on('resize', onResize)
    onResize()
    return () => { stdout.off('resize', onResize) }
  }, [stdout])

  return size
}
