import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../components/GlobalHeader.tsx', import.meta.url), 'utf8')
const ast = ts.createSourceFile('GlobalHeader.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const links: ts.JsxOpeningElement[] = []
let mobile: ts.VariableDeclaration | undefined
const walk = (node: ts.Node) => {
  if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'mobileNavigation') mobile = node
  if (ts.isJsxOpeningElement(node) && node.tagName.getText(ast) === 'Link') links.push(node)
  ts.forEachChild(node, walk)
}
walk(ast)
const attribute = (link: ts.JsxOpeningElement, name: string) => link.attributes.properties.find(
  (item): item is ts.JsxAttribute => ts.isJsxAttribute(item) && item.name.getText(ast) === name,
)
const literal = (link: ts.JsxOpeningElement, name: string) => {
  const value = attribute(link, name)?.initializer
  return value && ts.isStringLiteral(value) ? value.text : undefined
}
const mobileLinks = links.filter(link => mobile && link.pos >= mobile.pos && link.end <= mobile.end)
const desktopLinks = links.filter(link => literal(link, 'role') === 'menuitem')

describe('transient account and mobile menu navigation', () => {
  it('covers every mobile menu link and desktop account destination', () => {
    expect(mobileLinks).toHaveLength(10)
    expect(desktopLinks).toHaveLength(8)
    expect(desktopLinks.map(link => literal(link, 'href'))).toEqual([
      '/dashboard', '/billing', '/developer', '/byok', '/settings', '/admin', '/privacy', '/terms',
    ])
    expect(mobileLinks.some(link => attribute(link, 'href')?.initializer?.getText(ast) === '{item.href}')).toBe(true)
  })

  it.each([['mobile', mobileLinks], ['desktop account', desktopLinks]] as const)(
    'does not start speculative requests from the %s menu', (_name, menuLinks) => {
      for (const link of menuLinks) {
        const value = attribute(link, 'prefetch')?.initializer
        expect(value && ts.isJsxExpression(value) && value.expression?.kind === ts.SyntaxKind.FalseKeyword,
          `Prefetch must be false for ${attribute(link, 'href')?.initializer?.getText(ast)}`).toBe(true)
        expect(link.attributes.properties.some(ts.isJsxSpreadAttribute)).toBe(false)
        // Keep normal Next Link navigation and the existing menu-close handler.
        expect(attribute(link, 'href')).toBeDefined()
        expect(attribute(link, 'onClick')).toBeDefined()
      }
    },
  )
})
