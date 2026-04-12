/**
 * Unit tests for P2 Features 51 and 59.
 *
 * Feature 51: Resume Heatmap — heatmap-generator functions
 * Feature 59: Resume Confidence Score — API types shape
 */

import { describe, test, expect } from 'vitest'
import { computePageHeatmap, heatmapColor } from '../lib/heatmap-generator'

// ─────────────────────────────────────────────────────────────────────────────
// Feature 51 · Resume Heatmap
// ─────────────────────────────────────────────────────────────────────────────

describe('Feature 51 · computePageHeatmap', () => {
  test('page 0 returns region at yPercent=0 with intensity >= 0.9', () => {
    const regions = computePageHeatmap(0)
    const topRegion = regions.find((r) => r.yPercent === 0)
    expect(topRegion).toBeDefined()
    expect(topRegion!.intensity).toBeGreaterThanOrEqual(0.9)
  })

  test('page 0 regions cover 100% of page height', () => {
    const regions = computePageHeatmap(0)
    const totalHeight = regions.reduce((sum, r) => sum + r.heightPercent, 0)
    expect(totalHeight).toBe(100)
  })

  test('page 0 has at least 2 regions', () => {
    const regions = computePageHeatmap(0)
    expect(regions.length).toBeGreaterThanOrEqual(2)
  })

  test('page 0 first region has highest intensity', () => {
    const regions = computePageHeatmap(0)
    const maxIntensity = Math.max(...regions.map((r) => r.intensity))
    expect(regions[0].intensity).toBe(maxIntensity)
  })

  test('page 1 returns lower intensity than page 0 top region', () => {
    const page0 = computePageHeatmap(0)
    const page1 = computePageHeatmap(1)
    const page0Max = Math.max(...page0.map((r) => r.intensity))
    const page1Max = Math.max(...page1.map((r) => r.intensity))
    expect(page1Max).toBeLessThan(page0Max)
  })

  test('page 2 intensity is less than page 1', () => {
    const page1 = computePageHeatmap(1)
    const page2 = computePageHeatmap(2)
    const page1Max = Math.max(...page1.map((r) => r.intensity))
    const page2Max = Math.max(...page2.map((r) => r.intensity))
    expect(page2Max).toBeLessThan(page1Max)
  })

  test('all regions have required fields', () => {
    const regions = computePageHeatmap(0)
    for (const r of regions) {
      expect(typeof r.yPercent).toBe('number')
      expect(typeof r.heightPercent).toBe('number')
      expect(typeof r.intensity).toBe('number')
      expect(typeof r.label).toBe('string')
      expect(r.label.length).toBeGreaterThan(0)
      expect(r.intensity).toBeGreaterThanOrEqual(0)
      expect(r.intensity).toBeLessThanOrEqual(1)
    }
  })
})

describe('Feature 51 · heatmapColor', () => {
  test('intensity 1.0 returns red color', () => {
    const color = heatmapColor(1.0)
    expect(color).toContain('239,68,68')
  })

  test('intensity 0.5 returns amber color', () => {
    const color = heatmapColor(0.5)
    expect(color).toContain('251,191,36')
  })

  test('intensity 0.0 returns blue color', () => {
    const color = heatmapColor(0.0)
    expect(color).toContain('59,130,246')
  })

  test('intensity 0.95 (Name & Contact) returns red', () => {
    const color = heatmapColor(0.95)
    expect(color).toContain('239,68,68')
  })

  test('intensity 0.3 (Bottom of page) returns blue', () => {
    const color = heatmapColor(0.30)
    expect(color).toContain('59,130,246')
  })
})
