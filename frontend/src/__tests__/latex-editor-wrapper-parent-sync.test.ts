import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import { createEditorParentValueGuard, syncControlledEditorModel } from '@/components/LaTeXEditor'

const componentPath = new URL('../components/LaTeXEditor.tsx', import.meta.url)
const component = ts.createSourceFile('LaTeXEditor.tsx', readFileSync(componentPath, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

// Exercise the installed wrapper's real passive value effect, rather than a
// hand-written approximation of its full-model replacement behavior.
const require = createRequire(import.meta.url)
const wrapperPath = join(dirname(require.resolve('@monaco-editor/react')), 'index.mjs')
const wrapper = ts.createSourceFile(wrapperPath, readFileSync(wrapperPath, 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.JS)
const effects: Array<{ callback: string; value: string }> = []
function findValueEffect(node: ts.Node) {
  if (ts.isCallExpression(node) && node.arguments.length >= 2
    && ts.isArrowFunction(node.arguments[0]) && ts.isArrayLiteralExpression(node.arguments[1])
    && node.arguments[1].elements.length === 1) {
    const callback = node.arguments[0].getText(wrapper)
    if (callback.includes('executeEdits') && callback.includes('getFullModelRange') && callback.includes('===void 0')) {
      effects.push({ callback, value: node.arguments[1].elements[0].getText(wrapper) })
    }
  }
  ts.forEachChild(node, findValueEffect)
}
findValueEffect(wrapper)
if (effects.length !== 1) throw new Error('Expected one installed Monaco controlled-value effect')
const effect = effects[0]
const editorRefName = effect.callback.match(/([\w$]+)\.current\.getOption\(/)?.[1]
const monacoRefName = effect.callback.match(/([\w$]+)\.current\.editor\.EditorOption/)?.[1]
const suppressionRefName = effect.callback.match(/([\w$]+)\.current=!0/)?.[1]
if (!editorRefName || !monacoRefName || !suppressionRefName) throw new Error('Unrecognized installed Monaco value effect')

function wrapperValueProps(value: string, collabEnabled: boolean) {
  const props: Record<string, string> = {}
  let editors = 0
  function visit(node: ts.Node) {
    if (ts.isJsxSelfClosingElement(node) && node.tagName.getText(component) === 'MonacoEditor') {
      editors++
      for (const attribute of node.attributes.properties) {
        if (ts.isJsxAttribute(attribute) && ['value', 'defaultValue'].includes(attribute.name.getText(component))) {
          if (!attribute.initializer || !ts.isJsxExpression(attribute.initializer) || !attribute.initializer.expression) throw new Error('Expected a value expression')
          props[attribute.name.getText(component)] = runInNewContext(attribute.initializer.expression.getText(component), { value, collabEnabled })
        } else if (ts.isJsxSpreadAttribute(attribute) && /\b(?:value|defaultValue)\b/.test(attribute.expression.getText(component))) {
          Object.assign(props, runInNewContext(`(${attribute.expression.getText(component)})`, { value, collabEnabled }))
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(component)
  if (editors !== 1) throw new Error('Expected one product Monaco wrapper')
  return props
}

function modelWithWrapper(value: string, readOnly = false) {
  let source = value
  const writes: string[] = []
  const model = {
    getValue: () => source,
    setValue: (next: string) => { writes.push(next); source = next },
    getFullModelRange: () => ({ fullModel: true }),
  }
  const editor = {
    getOption: () => readOnly,
    getModel: () => model,
    getValue: model.getValue,
    setValue: model.setValue,
    executeEdits: (_name: string, edits: Array<{ text: string }>) => model.setValue(edits[0].text),
    pushUndoStop: () => {},
  }
  return {
    model, writes,
    flushDelayedWrapperValue(props: Record<string, string>) {
      runInNewContext(`(${effect.callback})()`, {
        [editorRefName!]: { current: editor },
        [monacoRefName!]: { current: { editor: { EditorOption: { readOnly: 0 } } } },
        [suppressionRefName!]: { current: false },
        [effect.value]: props.value,
      })
    },
  }
}

describe('Monaco wrapper and guarded parent synchronization', () => {
  it.each([false, true])('initializes fetched REST content with collaboration %s', collabEnabled => {
    const props = wrapperValueProps('fetched REST source', collabEnabled)
    expect(props.defaultValue ?? props.value).toBe('fetched REST source')
  })

  it('does not let the real wrapper roll a newer local edit back to a delayed parent echo', () => {
    const guard = createEditorParentValueGuard('saved')
    guard.recordLocalValue('saved word0')
    guard.observeParentValue('saved word0')
    // The parent render is captured, then another native input arrives before
    // its passive wrapper effect runs. The product guard must own this sync.
    const delayedProps = wrapperValueProps('saved word0', false)
    guard.recordLocalValue('saved word0 word1 word2')
    const runtime = modelWithWrapper('saved word0 word1 word2')
    runtime.flushDelayedWrapperValue(delayedProps)
    expect(runtime.model.getValue()).toBe('saved word0 word1 word2')
    expect(syncControlledEditorModel({ model: runtime.model, parentValue: 'saved word0', valueGuard: guard, collaborationBound: false })).toBe(false)
    expect(runtime.writes).toEqual([])
  })

  it.each([false, true])('lets only the guarded path apply a trusted restore with readOnly %s', readOnly => {
    const runtime = modelWithWrapper('local edit', readOnly)
    const guard = createEditorParentValueGuard('saved')
    guard.recordLocalValue('local edit')
    guard.observeParentValue('trusted server restore')
    runtime.flushDelayedWrapperValue(wrapperValueProps('trusted server restore', false))
    expect(runtime.model.getValue()).toBe('local edit')
    expect(syncControlledEditorModel({ model: runtime.model, parentValue: 'trusted server restore', valueGuard: guard, collaborationBound: false })).toBe(true)
    expect(runtime.model.getValue()).toBe('trusted server restore')
    expect(runtime.writes).toEqual(['trusted server restore'])
  })

  it('leaves a bound collaborative model under Y.js ownership', () => {
    const runtime = modelWithWrapper('remote collaborative source')
    const guard = createEditorParentValueGuard('initial REST source')
    guard.observeParentValue('late parent echo')
    runtime.flushDelayedWrapperValue(wrapperValueProps('late parent echo', true))
    expect(syncControlledEditorModel({ model: runtime.model, parentValue: 'late parent echo', valueGuard: guard, collaborationBound: true })).toBe(false)
    expect(runtime.model.getValue()).toBe('remote collaborative source')
    expect(runtime.writes).toEqual([])
  })
})
