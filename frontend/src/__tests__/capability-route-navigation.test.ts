import { readFileSync } from 'node:fs'
import React, { type ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CapabilityGate from '@/components/CapabilityGate'
import CapabilityRouteBoundary from '@/components/CapabilityRouteBoundary'
import { capabilityForRoute } from '@/lib/capability-ui-policy'

const state = vi.hoisted(() => ({ grants: new Set<string>(), pathname: '/workspace' }))
vi.mock('@/contexts/EntitlementsContext', () => ({
  useEntitlements: () => ({ can: (key: string) => state.grants.has(key), loading: false, error: null, refresh: vi.fn() }),
}))
vi.mock('next/navigation', () => ({ usePathname: () => state.pathname }))
vi.mock('@/lib/auth-client', () => ({ useSession: () => ({ data: { user: { id: 'owner' } } }) }))
vi.mock('next/link', () => ({ default: (props: React.ComponentProps<'a'>) => React.createElement('a', props) }))

function source(relative: string) {
  return ts.createSourceFile(relative, readFileSync(new URL(relative, import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
}
const workspace = source('../app/workspace/page.tsx')
const editor = source('../app/workspace/[resumeId]/edit/page.tsx')
const builder = source('../app/workspace/builder/[resumeId]/page.tsx')
const variant = source('../app/workspace/variant/[resumeId]/page.tsx')
const onboarding = source('../components/onboarding/OnboardingFlow.tsx')
const home = source('../app/page.tsx')
const newResume = source('../app/workspace/new/page.tsx')

function find(source: ts.SourceFile, predicate: (node: ts.Node) => boolean): ts.Node[] {
  const matches: ts.Node[] = []
  function visit(node: ts.Node) { if (predicate(node)) matches.push(node); ts.forEachChild(node, visit) }
  visit(source)
  return matches
}

/** Render real page JSX including its surrounding gate, rather than a duplicate
 * test-only link. Small fragments avoid mocking the editor/compiler. */
function linkExpression(source: ts.SourceFile, href: string, index = 0): ts.Node {
  const links = find(source, (node) => ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'Link' &&
    node.openingElement.attributes.properties.some((attribute) => ts.isJsxAttribute(attribute) && attribute.name.getText(source) === 'href' && attribute.initializer?.getText(source).includes(href) === true))
  expect(links.length, href).toBeGreaterThan(index)
  const link = links[index]
  for (let parent = link.parent; parent && !ts.isSourceFile(parent); parent = parent.parent) {
    if (ts.isJsxElement(parent) && parent.openingElement.tagName.getText(source) === 'CapabilityGate') return parent
    if (ts.isConditionalExpression(parent) && parent.condition.getText(source).startsWith('can(')) return parent
  }
  return link
}

const emptyIcon = () => null
function renderExpression(expression: ts.Node, extra: Record<string, unknown> = {}) {
  const scope = {
    React, CapabilityGate,
    Link: (props: React.ComponentProps<'a'>) => React.createElement('a', props),
    Sparkles: emptyIcon, Pencil: emptyIcon, GitMerge: emptyIcon, TrendingUp: emptyIcon, Wand2: emptyIcon,
    ArrowRight: emptyIcon, LayoutTemplate: emptyIcon, Upload: emptyIcon, PenLine: emptyIcon, CheckCircle: emptyIcon,
    Eyebrow: ({ children }: { children: ReactNode }) => React.createElement('span', null, children),
    IconTile: emptyIcon,
    can: (key: string) => state.grants.has(key), t: (key: string) => key,
    resume: { id: 'resume' }, variant: { id: 'variant' }, resumeId: 'resume',
    data: { source_resume_id: 'source', source_title: 'Saved source title' },
    dirty: false, confirmDiscardIfDirty: () => true,
    userType: 'new', freePlanCopy: 'the current free allowance', onComplete: vi.fn(), onSkip: vi.fn(), ...extra,
  }
  const js = ts.transpileModule(`const view = (${expression.getText()})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
  }).outputText
  const view = new Function(...Object.keys(scope), `${js}; return view`)(...Object.values(scope)) as ReactNode
  return renderToStaticMarkup(React.createElement(React.Fragment, null, view))
}

beforeEach(() => { state.grants = new Set(); state.pathname = '/workspace' })

describe('optional route entry controls render OFF and ON', () => {
  it.each([
    ['workspace grid Optimize', workspace, '/workspace/${resume.id}/optimize', 0, 'd01', '/workspace/resume/optimize'],
    ['workspace list Optimize', workspace, '/workspace/${resume.id}/optimize', 1, 'd01', '/workspace/resume/optimize'],
    ['workspace variant Optimize', workspace, '/workspace/${variant.id}/optimize', 0, 'd01', '/workspace/variant/optimize'],
    ['workspace Merge including mobile icon', workspace, '/workspace/merge', 0, 'b13', '/workspace/merge'],
    ['editor Career Path', editor, '/workspace/${resumeId}/career', 0, 'e04', '/workspace/resume/career'],
    ['editor Manage visibility', editor, '/workspace/variant/${resumeId}', 0, 'b12', '/workspace/variant/resume'],
    ['homepage Templates', home, '/templates', 0, 'b04', '/templates'],
    ['new resume Builder', newResume, '/workspace/builder/new', 0, 'b08', '/workspace/builder/new'],
  ] as const)('%s disappears on denial and returns without changing other controls', (_name, page, href, index, feature, renderedHref) => {
    const expression = linkExpression(page, href, index)
    expect(renderExpression(expression)).toBe('')
    state.grants.add(feature)
    const allowed = renderExpression(expression)
    expect(allowed).toContain(`href="${renderedHref}"`)
    if (feature === 'b13') expect(allowed).toContain('aria-label="Merge resumes"')
    state.grants.delete(feature)
    expect(renderExpression(expression)).toBe('')
    state.grants.add(feature)
    expect(renderExpression(expression)).toBe(allowed)
  })

  it('keeps the linked source title readable when only its builder destination is denied', () => {
    const expression = linkExpression(variant, '/workspace/builder/${data.source_resume_id}')
    expect(renderExpression(expression)).toBe('<span>Saved source title</span>')
    state.grants.add('b08')
    expect(renderExpression(expression)).toContain('href="/workspace/builder/source"')
    expect(renderExpression(expression)).toContain('Saved source title')
  })

  it('independently hides onboarding Template and Studio actions, retaining import and completion', () => {
    const ready = find(onboarding, (node) => ts.isObjectLiteralExpression(node) && node.properties.some((property) => ts.isPropertyAssignment(property) && property.name.getText(onboarding) === 'id' && property.initializer.getText(onboarding) === "'get-started'"))[0] as ts.ObjectLiteralExpression
    const content = ready.properties.find((property) => ts.isPropertyAssignment(property) && property.name.getText(onboarding) === 'content') as ts.PropertyAssignment
    const render = () => renderExpression(content.initializer)
    const denied = render()
    expect(denied).not.toContain('href="/templates"')
    expect(denied).not.toContain('href="/try"')
    expect(denied).toContain('href="/workspace/new"')
    expect(denied).toContain('onboarding.createFirst')
    expect(denied).toContain('onboarding.skipExplore')
    state.grants.add('b04')
    expect(render()).toContain('href="/templates"')
    expect(render()).not.toContain('href="/try"')
    state.grants.delete('b04'); state.grants.add('a09')
    expect(render()).not.toContain('href="/templates"')
    expect(render()).toContain('href="/try"')
    state.grants.add('b04')
    expect(render()).toContain('href="/templates"')
    expect(render()).toContain('href="/try"')
  })
})

describe('baseline recovery and direct route consistency', () => {
  it.each([
    ['builder Advanced Editor', builder], ['variant Advanced editor', variant],
  ] as const)('%s stays reachable with every optional grant OFF', (_name, page) => {
    expect(renderExpression(linkExpression(page, '/workspace/${resumeId}/edit'))).toContain('href="/workspace/resume/edit"')
  })

  it('keeps workspace source editing reachable independently of Optimize', () => {
    expect(renderExpression(linkExpression(workspace, '/workspace/${resume.id}/edit'))).toContain('href="/workspace/resume/edit"')
  })

  it.each([
    ['/templates', 'b04'], ['/workspace/builder/new', 'b08'], ['/workspace/variant/resume', 'b12'],
    ['/workspace/merge', 'b13'], ['/workspace/resume/optimize', 'd01'],
    ['/workspace/resume/batch-tailor', 'd05'], ['/workspace/resume/career', 'e04'],
  ])('denies direct %s content OFF and restores it ON using %s', (pathname, feature) => {
    state.pathname = pathname
    expect(capabilityForRoute(pathname)).toBe(feature)
    const render = () => renderToStaticMarkup(React.createElement(CapabilityRouteBoundary, null, React.createElement('button', null, 'Optional tool action')))
    const denied = render()
    expect(denied).toContain('Feature unavailable')
    expect(denied).not.toContain('Optional tool action')
    expect(denied).toContain('href="/workspace"')
    state.grants.add(feature)
    expect(render()).toContain('Optional tool action')
    expect(render()).not.toContain('Feature unavailable')
  })
})
