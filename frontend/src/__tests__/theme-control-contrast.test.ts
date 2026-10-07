import fs from 'node:fs'
import path from 'node:path'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import postcss from 'postcss'
import type { AcceptedPlugin } from 'postcss'
import tailwindcss from 'tailwindcss'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import config from '../../tailwind.config'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

const theme = vi.hoisted(() => ({ contrast: 'normal', ready: true, toggleContrast: () => {} }))
vi.mock('@/components/theme/ThemeProvider', () => ({ useTheme: () => theme }))
import ContrastToggle from '@/components/theme/ContrastToggle'

const tokens = postcss.parse(fs.readFileSync(path.join(process.cwd(), 'src/app/design-tokens.css'), 'utf8'))
let utilities: postcss.Root

beforeAll(async () => {
  theme.contrast = 'high'
  const html = renderToStaticMarkup(React.createElement(React.Fragment, null,
    React.createElement(Button, { variant: 'destructive' }, 'Delete'),
    React.createElement(Badge, { variant: 'destructive' }, 'Failed'),
    React.createElement(ContrastToggle)))
  theme.contrast = 'normal'
  // Tailwind carries a separate PostCSS patch version. Its runtime plugin uses
  // the same public API, while the duplicate AST types are not assignable.
  const plugin = tailwindcss({ ...config, content: [{ raw: html, extension: 'html' }] }) as unknown as AcceptedPlugin
  const result = await postcss([plugin])
    .process('@tailwind utilities;', { from: undefined })
  utilities = result.root
}, 60000)

function palette(aesthetic: string, mode: string, contrast = 'normal') {
  const colors: Record<string, string> = {}
  const selectors = [':root', `:root[data-aesthetic="${aesthetic}"]`,
    `:root[data-aesthetic="${aesthetic}"][data-mode="${mode}"]`]
  if (contrast === 'high') selectors.push(`:root[data-contrast="high"][data-mode="${mode}"]`)
  for (const selector of selectors) {
    tokens.walkRules(selector, (rule) => {
      rule.walkDecls((decl) => { if (decl.prop.startsWith('--')) colors[decl.prop] = decl.value })
    })
  }
  return colors
}

function luminance(color: string) {
  const channels = color.slice(1).match(/../g)!.map((value) => parseInt(value, 16) / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
  return channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
}

function contrastRatio(a: string, b: string) {
  const values = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

// Resolve actual generated utility order rather than assuming class-string order.
// This catches competing foreground classes and equal-colored hover states.
function renderedColors(html: string, colors: Record<string, string>, hover = false) {
  const classes = html.match(/class="([^"]+)"/)![1].split(/\s+/)
  const resolved: Record<string, string> = { color: colors['--fg'], 'background-color': colors['--bg'] }
  utilities.walkRules((rule) => {
    const matches = classes.some((className) => {
      const selector = `.${className.replace(/:/g, '\\:')}`
      return rule.selector === selector || (hover && rule.selector === `${selector}:hover`)
    })
    if (!matches) return
    rule.walkDecls((decl) => {
      if (decl.prop !== 'color' && decl.prop !== 'background-color') return
      const token = decl.value.match(/^var\((--[\w-]+)\)$/)
      if (token) resolved[decl.prop] = colors[token[1]]
      else if (/^#[\da-f]{6}$/i.test(decl.value)) resolved[decl.prop] = decl.value
      else if (decl.value.startsWith('rgb(255 255 255')) resolved[decl.prop] = '#FFFFFF'
    })
  })
  return resolved
}

describe('theme foreground contrast', () => {
  it('keeps actual destructive buttons and badges readable in all palette variants', () => {
    const variants = [['typeset', 'light'], ['typeset', 'dark'], ['compiler', 'light'], ['compiler', 'dark']]
    for (const contrast of ['normal', 'high']) {
      for (const [aesthetic, mode] of variants) {
        for (const component of [React.createElement(Button, { variant: 'destructive' }, 'Delete'),
          React.createElement(Badge, { variant: 'destructive' }, 'Failed')]) {
          const colors = renderedColors(renderToStaticMarkup(component), palette(aesthetic, mode, contrast))
          expect(contrastRatio(colors.color, colors['background-color']), `${aesthetic}/${mode}/${contrast}`).toBeGreaterThanOrEqual(4.5)
        }
      }
    }
  })

  it('keeps the selected high-contrast control visible before and during hover', () => {
    theme.contrast = 'high'
    const html = renderToStaticMarkup(React.createElement(ContrastToggle))
    for (const mode of ['light', 'dark']) {
      for (const hover of [false, true]) {
        const colors = renderedColors(html, palette('typeset', mode, 'high'), hover)
        expect(contrastRatio(colors.color, colors['background-color']), `${mode}/hover=${hover}`).toBeGreaterThanOrEqual(4.5)
      }
    }
    theme.contrast = 'normal'
  })
})
