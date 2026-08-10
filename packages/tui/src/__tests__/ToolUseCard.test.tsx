import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { ToolUseCard } from '../components/ToolUseCard.js'
import { SPINNER_FRAMES } from '../components/Spinner.js'
import type { Message } from '../stores/messages.js'

const base: Message = {
  id: 'm1',
  role: 'tool_use',
  content: '',
  timestamp: new Date().toISOString(),
  toolName: 'compile_pdf',
}

describe('ToolUseCard', () => {
  it('shows tool name with spinner when running', () => {
    const { lastFrame } = render(<ToolUseCard message={{ ...base, toolState: 'running' }} />)
    const frame = lastFrame() ?? ''
    expect(frame).toContain('compile_pdf')
    // Assert the spinner itself renders. @inkjs/ui's Spinner returned nothing under
    // Ink 7 on Linux and took the whole subtree with it, so the tool name vanished
    // too and this test only caught it incidentally — on one platform.
    expect(
      SPINNER_FRAMES.some(f => frame.includes(f)),
      `no spinner frame in: ${JSON.stringify(frame)}`,
    ).toBe(true)
  })

  it('shows duration on success', () => {
    const { lastFrame } = render(<ToolUseCard message={{ ...base, toolState: 'success', durationMs: 2300 }} />)
    expect(lastFrame()).toContain('compile_pdf')
    expect(lastFrame()).toContain('2.3s')
  })

  it('shows error text on failure', () => {
    const { lastFrame } = render(
      <ToolUseCard message={{ ...base, toolState: 'error', toolResult: { error: 'LaTeX error' } }} />
    )
    expect(lastFrame()).toContain('error')
  })

  it('shows cancelled state', () => {
    const { lastFrame } = render(<ToolUseCard message={{ ...base, toolState: 'cancelled' }} />)
    expect(lastFrame()).toContain('cancelled')
  })
})
