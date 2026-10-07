import { describe, expect, it } from 'vitest'
import { visualFeedback } from './visual-feedback'

describe('visual feedback source isolation', () => {
  it('hides source instructions throughout nested AI feedback without mutating the report', () => {
    const report = { score: 75, sections: [{ strengths: ['Clear summary'], issues: ['Remove \\vspace{5pt}', '```latex code```'] }] }
    const safe = visualFeedback(report)
    expect(safe.score).toBe(75)
    expect(safe.sections[0].strengths).toEqual(['Clear summary'])
    expect(JSON.stringify(safe)).not.toContain('\\vspace')
    expect(JSON.stringify(safe)).not.toContain('```')
    expect(report.sections[0].issues[0]).toBe('Remove \\vspace{5pt}')
  })
  it('retains ordinary résumé advice, currency, and empty states', () => {
    expect(visualFeedback({ advice: 'Explain the $20k budget and 35% result', score: null })).toEqual({ advice: 'Explain the $20k budget and 35% result', score: null })
  })
})
