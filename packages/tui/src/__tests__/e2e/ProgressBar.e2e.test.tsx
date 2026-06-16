import React from 'react'
import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import { ProgressBar } from '../../components/ProgressBar.js'

describe('ProgressBar', () => {
  it('renders at 0%', () => {
    const { lastFrame } = render(<ProgressBar value={0} />)
    expect(lastFrame()).toBeTruthy()
    expect(lastFrame()).toContain('0%')
  })

  it('renders at 100%', () => {
    const { lastFrame } = render(<ProgressBar value={100} />)
    expect(lastFrame()).toContain('100%')
  })

  it('renders at 50%', () => {
    const { lastFrame } = render(<ProgressBar value={50} />)
    expect(lastFrame()).toContain('50%')
  })

  it('can hide percent display', () => {
    const { lastFrame } = render(<ProgressBar value={75} showPercent={false} />)
    expect(lastFrame()).not.toContain('%')
  })

  it('renders with custom width', () => {
    const { lastFrame } = render(<ProgressBar value={50} width={10} />)
    expect(lastFrame()).toBeTruthy()
  })
})
