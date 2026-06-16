import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { CompileResultCard } from '../components/CompileResultCard.js'

describe('CompileResultCard', () => {
  it('shows pages and size', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={2} sizeBytes={85000} compilationTimeMs={2300} pdfUrl="/dl/abc.pdf" atsScore={null} />
    )
    expect(lastFrame()).toContain('2')
    expect(lastFrame()).toContain('83')  // ~83 KB
  })

  it('shows compilation time', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={1} sizeBytes={40000} compilationTimeMs={1500} pdfUrl="/dl/x.pdf" atsScore={null} />
    )
    // New card shows locale-formatted ms: "1,500 ms"
    expect(lastFrame()).toContain('1,500 ms')
  })

  it('shows ATS score when provided', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={2} sizeBytes={85000} compilationTimeMs={2000} pdfUrl="/dl/abc.pdf" atsScore={72} />
    )
    expect(lastFrame()).toContain('72')
  })

  it('shows success message', () => {
    const { lastFrame } = render(
      <CompileResultCard pages={1} sizeBytes={50000} compilationTimeMs={1000} pdfUrl={null} atsScore={null} />
    )
    // New card header text changed
    expect(lastFrame()).toContain('Compilation Complete')
  })
})
