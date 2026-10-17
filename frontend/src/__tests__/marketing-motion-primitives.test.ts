import { afterEach, describe, expect, it, vi } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const motionPreference = vi.hoisted(() => ({ reduce: true, scrollReads: 0 }))

vi.mock('framer-motion', () => ({
  motion: {
    div: () => {
      throw new Error('Reduced-motion rendering must not mount a Framer Motion wrapper')
    },
  },
  useReducedMotion: () => motionPreference.reduce,
  useScroll: () => {
    motionPreference.scrollReads += 1
    return { scrollYProgress: null }
  },
  useTransform: () => null,
}))

import { MotionItem, MotionReveal, MotionStagger, ScrollDepth } from '@/components/marketing/MotionPrimitives'

afterEach(() => {
  motionPreference.reduce = true
  motionPreference.scrollReads = 0
})

describe('marketing motion primitives', () => {
  it('renders reduced-motion content statically without viewport or scroll observers', () => {
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
    expect(html).not.toContain('data-marketing-motion')
    expect(motionPreference.scrollReads).toBe(0)
  })

  it('keeps server-rendered motion wrappers visible before hydration', () => {
    const repositoryRoot = resolve(process.cwd(), '..')
    const tokens = readFileSync(resolve(repositoryRoot, 'frontend/src/app/design-tokens.css'), 'utf8')
    const staticFallback = /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\[data-marketing-motion\]\s*\{\s*opacity:\s*1 !important;\s*transform:\s*none !important;/

    expect(tokens).toMatch(staticFallback)
  })
})
