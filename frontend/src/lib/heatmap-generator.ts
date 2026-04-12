/**
 * Heatmap generator for PDF preview — Feature 51.
 *
 * Produces rule-based recruiter attention predictions based on
 * published eye-tracking research on resume scanning patterns.
 */

export interface HeatmapRegion {
  yPercent: number       // top edge of region as % of page height
  heightPercent: number  // height as % of page height
  intensity: number      // 0.0 (cold/blue) → 1.0 (hot/red)
  label: string
}

/**
 * Return heatmap regions for the given page (0-indexed).
 * Page 0 uses research-backed attention weights.
 * Subsequent pages use uniformly lower intensity.
 */
export function computePageHeatmap(pageIndex: number): HeatmapRegion[] {
  if (pageIndex === 0) {
    return [
      { yPercent: 0,  heightPercent: 20, intensity: 0.95, label: 'Name & Contact' },
      { yPercent: 20, heightPercent: 5,  intensity: 0.75, label: 'Section headers' },
      { yPercent: 25, heightPercent: 50, intensity: 0.60, label: 'First job entries' },
      { yPercent: 75, heightPercent: 25, intensity: 0.30, label: 'Bottom of page' },
    ]
  }
  // Page 2+: uniformly lower intensity
  return [
    {
      yPercent: 0,
      heightPercent: 100,
      intensity: 0.15 * (1 / (pageIndex + 1)),
      label: `Page ${pageIndex + 1}`,
    },
  ]
}

/**
 * Map a 0–1 intensity value to a CSS rgba colour matching the spec:
 *   1.0 → red   rgba(239,68,68,0.35)
 *   0.5 → amber rgba(251,191,36,0.25)
 *   0.0 → blue  rgba(59,130,246,0.15)
 */
export function heatmapColor(intensity: number): string {
  if (intensity >= 0.65) return 'rgba(239,68,68,0.35)'
  if (intensity >= 0.35) return 'rgba(251,191,36,0.25)'
  return 'rgba(59,130,246,0.15)'
}
