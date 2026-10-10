import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')
const ast = ts.createSourceFile('page.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const expressions: Record<string, string> = {}
let menuFilter = '', renderGuard = '', redirectEffect = ''
function visit(node: ts.Node) {
  if (ts.isVariableDeclaration(node) && ['visualPanels', 'visibleRightTab'].includes(node.name.getText(ast))) {
    expressions[node.name.getText(ast)] = node.initializer!.getText(ast)
  }
  if (ts.isCallExpression(node)) {
    if (ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === 'filter' && node.expression.expression.getText(ast).includes("id: 'comments'")) {
      menuFilter = node.arguments[0].getText(ast)
    }
    if (node.expression.getText(ast) === 'useEffect' && node.arguments[0]?.getText(ast).includes('visualPanels.includes(rightTab)')) {
      redirectEffect = node.arguments[0].getText(ast)
    }
  }
  if (ts.isBinaryExpression(node) && ts.isParenthesizedExpression(node.right)) {
    const panel = node.right.expression
    if (ts.isJsxSelfClosingElement(panel) && panel.tagName.getText(ast) === 'CommentsPanel') renderGuard = node.left.getText(ast)
  }
  ts.forEachChild(node, visit)
}
visit(ast)
function evaluate(expression: string, context: Record<string, unknown>) {
  expect(expression).not.toBe('')
  const js = ts.transpileModule(`const value = ${expression}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return runInNewContext(`${js}\nvalue`, context)
}

describe('Comments remain reachable in persisted Visual mode', () => {
  const context = () => ({ editorMode: 'wysiwyg', rightTab: 'comments', visibleRightTab: 'comments', visualPanels: evaluate(expressions.visualPanels, {}) })
  it('preserves a comment deep link instead of redirecting to the PDF', () => {
    const values = context()
    expect(values.visualPanels).toContain('comments')
    if (expressions.visibleRightTab) expect(evaluate(expressions.visibleRightTab, values)).toBe('comments')
    else {
      const setRightTab = vi.fn()
      evaluate(redirectEffect, { ...values, setRightTab })()
      expect(setRightTab).not.toHaveBeenCalled()
    }
    expect(source).toContain("if (searchParams.get('comment_id')) setRightTab('comments')")
  })
  it('offers Comments in the actual More menu filter', () => {
    expect(evaluate(menuFilter, context())({ id: 'comments' })).toBe(true)
  })
  it('renders Comments in Visual while retaining the existing comment permission', () => {
    expect(evaluate(renderGuard, context())).toBe(true)
    expect(source).toContain("canComment={collabRole !== 'viewer'}")
    expect(source).toContain("highlightCommentId={searchParams.get('comment_id') ?? undefined}")
  })
})
