import { describe, it, expect } from 'vitest'
import { render } from 'ink-testing-library'
import React from 'react'
import { StatusBar } from '../components/StatusBar.js'

describe('StatusBar', () => {
  it('shows brand name Latexy', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unknown" wsConnected={false} />)
    expect(lastFrame()).toContain('Latexy')
  })

  it('shows user email and plan badge when logged in', () => {
    const { lastFrame } = render(<StatusBar email="a@b.com" plan="pro" health="healthy" wsConnected={true} />)
    expect(lastFrame()).toContain('a@b.com')
    expect(lastFrame()).toContain('PRO')
  })

  it('shows health status', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unhealthy" wsConnected={false} />)
    expect(lastFrame()).toContain('unhealthy')
  })

  it('shows disconnected indicator when not connected', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unknown" wsConnected={false} />)
    expect(lastFrame()).toContain('disconnected')
  })
})
