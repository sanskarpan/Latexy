import React from 'react'
import { describe, it, expect, beforeEach } from 'vitest'
import { render } from 'ink-testing-library'
import { KeyboardHints } from '../../components/KeyboardHints.js'
import { $activeJobId, clearMessages } from '../../stores/messages.js'
import { $overlay, closeOverlay } from '../../stores/overlay.js'

describe('KeyboardHints', () => {
  beforeEach(() => {
    clearMessages()
    closeOverlay()
    $activeJobId.set(null)
  })

  it('shows default hints when idle', () => {
    const { lastFrame } = render(<KeyboardHints />)
    const frame = lastFrame() ?? ''
    expect(frame).toContain('Ctrl+C')
    expect(frame).toContain('Ctrl+L')
  })

  it('shows cancel hint when job is active', () => {
    $activeJobId.set('job-123')
    const { lastFrame } = render(<KeyboardHints />)
    const frame = lastFrame() ?? ''
    expect(frame).toContain('/cancel')
    $activeJobId.set(null)
  })

  it('shows Esc hint when overlay is open', () => {
    $overlay.set('some-overlay')
    const { lastFrame } = render(<KeyboardHints />)
    const frame = lastFrame() ?? ''
    expect(frame).toContain('Esc')
  })
})
