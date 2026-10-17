import { describe, expect, it, vi } from 'vitest'
import { createElement, type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const motionPreference = vi.hoisted(() => ({ scrollReads: 0 }))

vi.mock('framer-motion', async () => {
  const React = await import('react')
  return {
    motion: {
      div: ({ children, className }: { children?: ReactNode; className?: string }) =>
        React.createElement('div', { className, 'data-marketing-motion': true }, children),
    },
    useScroll: () => {
      motionPreference.scrollReads += 1
      return { scrollYProgress: null }
    },
    useTransform: () => null,
  }
})

import { MotionItem, MotionReveal, MotionStagger, ScrollDepth } from '@/components/marketing/MotionPrimitives'

describe('marketing motion primitives', () => {
  it('renders deterministic motion wrappers for the server and initial hydration', () => {
    const html = renderToStaticMarkup(createElement('main', null,
      createElement(MotionReveal, null, createElement('h1', null, 'Updates')),
      createElement(MotionStagger, null,
        createElement(MotionItem, null, createElement('p', null, 'Release notes')),
      ),
      createElement(ScrollDepth, null, createElement('span', null, 'More information')),
    ))

    expect(html).toContain('<h1>Updates</h1>')
    expect(html).toContain('<p>Release notes</p>')
    expect(html).toContain('<span>More information</span>')
    expect(html.match(/data-marketing-motion/g)).toHaveLength(4)
    expect(motionPreference.scrollReads).toBe(1)
  })

  it('keeps server-rendered motion wrappers visible before hydration', () => {
    const repositoryRoot = resolve(process.cwd(), '..')
    const tokens = readFileSync(resolve(repositoryRoot, 'frontend/src/app/design-tokens.css'), 'utf8')
    const staticFallback = /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\[data-marketing-motion\]\s*\{\s*opacity:\s*1 !important;\s*transform:\s*none !important;/

    expect(tokens).toMatch(staticFallback)
  })
})
