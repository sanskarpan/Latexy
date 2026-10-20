import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const state = vi.hoisted(() => ({ reduced: false, props: [] as Record<string, unknown>[] }))
vi.mock('react', async (original) => ({
  ...await original<typeof import('react')>(),
  useSyncExternalStore: () => state.reduced,
}))
vi.mock('framer-motion', async () => {
  const React = await import('react')
  return {
    motion: {
      div: (props: Record<string, unknown> & { children?: ReactNode }) => {
        state.props.push(props)
        return React.createElement('div', { 'data-marketing-motion': true }, props.children)
      },
    },
    useScroll: () => ({ scrollYProgress: 'scroll' }),
    useTransform: (_value: unknown, _input: unknown, output: number[]) => output,
  }
})

import { MotionItem, MotionReveal, MotionStagger, ScrollDepth } from '@/components/marketing/MotionPrimitives'

function renderPrimitives() {
  return renderToStaticMarkup(createElement('main', null,
    createElement(MotionReveal, null, createElement('h1', null, 'Updates')),
    createElement(MotionStagger, null,
      createElement(MotionItem, null, createElement('p', null, 'Release notes'))),
    createElement(ScrollDepth, null, createElement('span', null, 'More information')),
  ))
}

describe('marketing motion primitives', () => {
  beforeEach(() => { state.reduced = false; state.props = [] })

  it('preserves normal reveal, stagger and scroll behavior', () => {
    const html = renderPrimitives()
    expect(html).toContain('<h1>Updates</h1>')
    expect(html.match(/data-marketing-motion/g)).toHaveLength(4)
    expect(state.props[0]).toMatchObject({ initial: { opacity: 0, y: 24 }, transition: { delay: 0, duration: 0.62 } })
    expect(state.props[1]).toMatchObject({ initial: 'hidden', variants: { show: { transition: { staggerChildren: 0.08 } } } })
    expect(state.props[2]).toMatchObject({ variants: { hidden: { opacity: 0, y: 22 } } })
    expect(state.props[3]).toMatchObject({ style: { y: [0, -120], opacity: [1, 0.86] } })
  })

  it('removes motion and delays without changing wrapper types or hiding content', () => {
    state.reduced = true
    const html = renderPrimitives()
    expect(html.match(/data-marketing-motion/g)).toHaveLength(4)
    expect(state.props[0]).toMatchObject({ initial: false, animate: { opacity: 1, y: 0 }, transition: { delay: 0, duration: 0 } })
    expect(state.props[0].whileInView).toBeUndefined()
    expect(state.props[1]).toMatchObject({ initial: false, animate: 'show', variants: { show: { transition: { staggerChildren: 0 } } } })
    expect(state.props[2]).toMatchObject({ animate: { opacity: 1, y: 0, transition: { duration: 0 } }, variants: { hidden: { opacity: 1, y: 0 } } })
    expect(state.props[3]).toMatchObject({ style: { y: 0, opacity: 1 } })
  })

  it('provides a no-JavaScript visibility fallback for either motion preference', () => {
    const layout = readFileSync(resolve(process.cwd(), 'src/app/layout.tsx'), 'utf8')
    expect(layout).toMatch(/<noscript>[\s\S]*?\[data-marketing-motion\][\s\S]*?opacity: 1 !important; transform: none !important;[\s\S]*?<\/noscript>/)
  })

  it('keeps server-rendered wrappers visible before hydration under reduced motion', () => {
    const tokens = readFileSync(resolve(process.cwd(), 'src/app/design-tokens.css'), 'utf8')
    expect(tokens).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\[data-marketing-motion\]\s*\{\s*opacity:\s*1 !important;\s*transform:\s*none !important;/)
  })
})
