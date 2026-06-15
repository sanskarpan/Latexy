import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { ToolUseCard } from '../components/ToolUseCard.js'
import type { Message } from '../stores/messages.js'

const base: Message = {
  id: 'm1',
  role: 'tool_use',
  content: '',
  timestamp: new Date().toISOString(),
  toolName: 'compile_pdf',
}

describe('ToolUseCard', () => {
  it('shows tool name and running text when running', () => {
    const { lastFrame } = render(<ToolUseCard message={{ ...base, toolState: 'running' }} />)
    expect(lastFrame()).toContain('compile_pdf')
    expect(lastFrame()).toContain('running')
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
