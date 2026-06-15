import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { LogStreamCard } from '../components/LogStreamCard.js'

describe('LogStreamCard', () => {
  it('renders log lines', () => {
    const { lastFrame } = render(
      <LogStreamCard lines={['This is pdflatex', 'Output written on resume.pdf']} />
    )
    expect(lastFrame()).toContain('pdflatex')
    expect(lastFrame()).toContain('Output written')
  })

  it('shows line count', () => {
    const lines = Array.from({ length: 10 }, (_, i) => `line ${i}`)
    const { lastFrame } = render(<LogStreamCard lines={lines} />)
    expect(lastFrame()).toContain('10')
  })

  it('shows error lines in output', () => {
    const { lastFrame } = render(
      <LogStreamCard lines={['[ERR] LaTeX Warning: Font shape undefined']} />
    )
    expect(lastFrame()).toContain('LaTeX Warning')
  })

  it('shows only last maxVisible lines when overflow', () => {
    const lines = Array.from({ length: 30 }, (_, i) => `line-${i}`)
    const { lastFrame } = render(<LogStreamCard lines={lines} maxVisible={5} />)
    expect(lastFrame()).toContain('line-29')
    expect(lastFrame()).not.toContain('line-0')
  })
})
