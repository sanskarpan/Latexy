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
    expect(lastFrame()).toContain('pro')  // plan badge is lowercase in new design
  })

  it('shows health status', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unhealthy" wsConnected={false} />)
    expect(lastFrame()).toContain('unhealthy')
  })

  it('shows disconnected indicator when not connected', () => {
    const { lastFrame } = render(<StatusBar email={null} plan={null} health="unknown" wsConnected={false} />)
    expect(lastFrame()).toContain('disconnected')
  })

  it('uses compact labels and omits email before fields collide at 60 columns', () => {
    const { lastFrame } = render(
      <StatusBar
        email="a-long-address@example.com"
        plan="pro"
        health="healthy"
        wsConnected={true}
        columns={60}
      />,
    )
    expect(lastFrame()).toContain('Latexy')
    expect(lastFrame()).toContain('pro')
    expect(lastFrame()).toContain('● ws')
    expect(lastFrame()).toContain('✦ healthy')
    expect(lastFrame()).not.toContain('example.com')
  })

  it('keeps only status glyphs in very narrow terminals', () => {
    const { lastFrame } = render(
      <StatusBar email="a@b.com" plan="free" health="unhealthy" wsConnected={false} columns={40} />,
    )
    expect(lastFrame()).not.toContain('Latexy')
    expect(lastFrame()).not.toContain('unhealthy')
    expect(lastFrame()).toContain('○')
    expect(lastFrame()).toContain('✦')
  })
})
