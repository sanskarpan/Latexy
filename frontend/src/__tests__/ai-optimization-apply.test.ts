import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

// Exercise the actual saved-page JSX callbacks; the AIPanel button passes a
// MouseEvent, whereas the review modal intentionally supplies edited text.
const ast = ts.createSourceFile('page.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function evaluate(expression: string, context: Record<string, unknown>) {
  expect(expression).not.toBe('')
  const js = ts.transpileModule(`const result = ${expression}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return runInNewContext(`${js}\nresult`, { ...context })
}

function jsxProp(component: string, property: string) {
  let expression = ''
  function visit(node: ts.Node) {
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(ast) === component) {
      const attr = node.attributes.properties.find(prop => ts.isJsxAttribute(prop) && prop.name.getText(ast) === property)
      if (attr && ts.isJsxAttribute(attr) && attr.initializer && ts.isJsxExpression(attr.initializer)) expression = attr.initializer.expression!.getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  return expression
}

function applyCallback(context: Record<string, unknown>) {
  let expression = ''
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === 'handleApplyOptimization' && node.initializer && ts.isCallExpression(node.initializer)) {
      expression = node.initializer.arguments[0].getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  return evaluate(expression, context)
}

describe('AI optimization apply boundaries', () => {
  it('does not forward the AIPanel button MouseEvent as reviewed resume text', () => {
    const applyOptimizationCandidate = vi.fn(() => false)
    const handleApplyOptimization = applyCallback({ stagedAiLatex: 'staged resume text', applyOptimizationCandidate })
    const onApply = evaluate(jsxProp('AIPanel', 'onApply'), { handleApplyOptimization })
    onApply({ type: 'click', currentTarget: { tagName: 'BUTTON' } })
    expect(applyOptimizationCandidate).toHaveBeenCalledExactlyOnceWith('staged resume text', true)
  })

  it('still forwards the reviewed text from the Visual review modal', () => {
    const applyOptimizationCandidate = vi.fn(() => false)
    const handleApplyOptimization = applyCallback({ stagedAiLatex: 'staged resume text', applyOptimizationCandidate })
    const onApply = evaluate(jsxProp('VisualChangeReviewModal', 'onApply'), { stagedAiLatex: 'staged resume text', handleApplyOptimization })
    onApply('user-reviewed resume text')
    expect(applyOptimizationCandidate).toHaveBeenCalledExactlyOnceWith('user-reviewed resume text', false)
  })
})
