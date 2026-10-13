import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

type Session = { user: { id: string }; session: { token: string } }
type State = { data: Session | null; isPending: boolean; isRefetching: boolean; error: unknown; refetch: () => Promise<void> }
type Atom = { value: State; set: (next: State) => void }
const source = readFileSync(new URL('../components/GlobalHeader.tsx', import.meta.url), 'utf8')
const ast = ts.createSourceFile('GlobalHeader.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const component = ast.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'GlobalHeader') as ts.FunctionDeclaration
const statements = component.body!.statements
const declarationName = (node: ts.Statement) => ts.isVariableStatement(node) ? node.declarationList.declarations[0].name.getText(ast) : ''
const authorityStatements = statements.filter(node => ['unauthorized', 'confirmedNoSession', 'effectiveSession', 'effectiveUserId'].includes(declarationName(node))
  || (ts.isIfStatement(node) && node.expression.getText(ast) === 'unauthorized'))
const latchJs = ts.transpileModule(authorityStatements.map(node => node.getText(ast)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const evaluateLatch = new Function('context', `with (context) { ${latchJs}; return { effectiveUserId, confirmedNoSession } }`) as
  (context: Record<string, unknown>) => { effectiveUserId: string | undefined; confirmedNoSession: boolean }
const purgeStatement = statements.find(node => ts.isExpressionStatement(node) && ts.isCallExpression(node.expression)
  && node.expression.expression.getText(ast) === 'useEffect' && node.expression.arguments[0].getText(ast).includes('const previousOwner = lastOfflinePdfOwnerRef.current')) as ts.ExpressionStatement
const purgeCall = purgeStatement.expression as ts.CallExpression
const purgeJs = ts.transpileModule(`const purge = ${purgeCall.arguments[0].getText(ast)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
const executePurge = new Function('context', `with (context) { ${purgeJs}; return purge() }`) as (context: Record<string, unknown>) => void

async function harness() {
  const sessionModule = path.join(path.dirname(createRequire(import.meta.url).resolve('better-auth/client')), 'session-atom.mjs')
  const { getSessionAtom } = await import(pathToFileURL(sessionModule).href)
  const known = { user: { id: 'owner-A' }, session: { token: 'synthetic-token' } }
  let release!: (next: { data: Session | null; error: { status: number; message: string } | null }) => void
  const response = new Promise<{ data: Session | null; error: { status: number; message: string } | null }>(resolve => { release = resolve })
  const fetch = vi.fn(() => response)
  const { session: atom } = getSessionAtom(fetch, {}) as { session: Atom }
  atom.set({ ...atom.value, data: known, isPending: false, isRefetching: false, error: null })
  const lastKnownSessionRef = { current: null as Session | null }; const lastOfflinePdfOwnerRef = { current: null as string | null }
  const cleanup = { rememberOfflinePdfOwner: vi.fn(), forgetOfflinePdfOwner: vi.fn(), clearAllDraftsExcept: vi.fn().mockResolvedValue(undefined),
    clearOfflineCompiledPdfsExcept: vi.fn().mockResolvedValue(undefined), clearAllOfflineCompiledPdfs: vi.fn().mockResolvedValue(undefined),
    clearAllDrafts: vi.fn().mockResolvedValue(undefined), clearCompileQueue: vi.fn().mockResolvedValue(undefined) }
  let identity!: ReturnType<typeof evaluateLatch>
  const render = () => { const { data: session, isPending: sessionPending, isRefetching: sessionRefetching, error: sessionError } = atom.value
    identity = evaluateLatch({ session, sessionPending, sessionRefetching, sessionError, lastKnownSessionRef, isConfirmedSessionUnauthorized }); return identity }
  const flushPurge = () => executePurge({ ...identity, ...cleanup, lastOfflinePdfOwnerRef })
  return { atom, known, release, fetch, cleanup, lastKnownSessionRef, lastOfflinePdfOwnerRef, render, flushPurge }
}

describe('actual header session authority and offline purge', () => {
  it.each([401, 503])('distinguishes installed Better Auth%s from stable-data refetch before cleanup effects', async status => {
    const h = await harness(); expect(h.render().effectiveUserId).toBe('owner-A'); h.flushPurge()
    const completion = h.atom.value.refetch(); await Promise.resolve()
    expect(h.atom.value.data).toBe(h.known); expect(h.atom.value.isPending).toBe(false); expect(h.atom.value.isRefetching).toBe(true)
    expect(h.render().effectiveUserId).toBe('owner-A'); h.flushPurge()
    expect(h.cleanup.forgetOfflinePdfOwner).not.toHaveBeenCalled(); expect(h.cleanup.clearAllDrafts).not.toHaveBeenCalled()
    h.release({ data: null, error: { status, message: `Synthetic ${status}` } }); await completion
    const identity = h.render()
    if (status === 503) {
      expect(identity.effectiveUserId).toBe('owner-A'); expect(identity.confirmedNoSession).toBe(false); h.flushPurge()
      expect(h.lastKnownSessionRef.current).toBe(h.known); expect(h.cleanup.forgetOfflinePdfOwner).not.toHaveBeenCalled()
      expect(h.cleanup.clearAllOfflineCompiledPdfs).not.toHaveBeenCalled(); expect(h.cleanup.clearCompileQueue).not.toHaveBeenCalled()
    } else {
      expect(identity.effectiveUserId).toBeUndefined(); expect(identity.confirmedNoSession).toBe(true)
      expect(h.lastKnownSessionRef.current).toBeNull(); expect(h.cleanup.forgetOfflinePdfOwner).not.toHaveBeenCalled()
      h.flushPurge(); expect(h.cleanup.forgetOfflinePdfOwner).toHaveBeenCalledOnce()
      expect(h.cleanup.clearAllOfflineCompiledPdfs).toHaveBeenCalledOnce(); expect(h.cleanup.clearAllDrafts).toHaveBeenCalledOnce()
      expect(h.cleanup.clearCompileQueue).toHaveBeenCalledOnce(); expect(h.lastOfflinePdfOwnerRef.current).toBeNull()
    }
  })
  it.each([401, 'empty'])('purges persisted offline owner even with an empty in-memory owner on confirmed %s', async status => {
    const h = await harness()
    h.atom.set({ ...h.atom.value, data: null, error: status === 401 ? { status: 401 } : null })
    expect(h.render().effectiveUserId).toBeUndefined(); h.flushPurge()
    expect(h.cleanup.forgetOfflinePdfOwner).toHaveBeenCalledOnce(); expect(h.cleanup.clearAllOfflineCompiledPdfs).toHaveBeenCalledOnce()
  })
})
