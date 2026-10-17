import { createRequire } from 'node:module'
import {
    act,
    createElement,
    Fragment,
    StrictMode,
    startTransition,
    Suspense,
    useState,
} from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProjectSearchModal from '@/components/ProjectSearchModal'

const search = vi.hoisted(() => vi.fn())
const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('@/lib/api-client', () => ({ apiClient: { searchResumes: search } }))
vi.mock('next/navigation', () => ({ useRouter: () => router }))
vi.mock('lucide-react', () => ({
    Search: () => null,
    X: () => null,
    FileText: () => null,
    Clock: () => null,
}))

type HostNode = {
    type: string
    props: Record<string, unknown>
    children: HostNode[]
    text?: string
    focus: () => void
}
type HostRenderer = {
    createContainer: (...args: unknown[]) => unknown
    updateContainer: (...args: unknown[]) => void
    flushSync: (work: () => void) => void
}
type Deferred<T> = {
    promise: Promise<T>
    resolve: (value: T) => void
    reject: (reason: unknown) => void
}

function deferred<T>(): Deferred<T> {
    let resolve!: (value: T) => void
    let reject!: (reason: unknown) => void
    const promise = new Promise<T>((accept, fail) => {
        resolve = accept
        reject = fail
    })
    return { promise, resolve, reject }
}

function textContent(node: HostNode): string {
    return node.text ?? node.children.map(textContent).join('')
}

function descendants(node: HostNode): HostNode[] {
    return [node, ...node.children.flatMap(descendants)]
}

function committedSnapshot(node: HostNode): string {
    const fields = descendants(node).flatMap(child => {
        if (child.type === 'input') return [`input[value=${String(child.props.value ?? '')}]`]
        if (child.props.role === 'alert') return [`alert[text=${textContent(child)}]`]
        return []
    })
    return `${textContent(node)}\n${fields.join('\n')}`
}

const require = createRequire(import.meta.url)
const fiberRequire = createRequire(require.resolve('@react-three/fiber'))
// This is a real React ConcurrentRoot host test, but @react-three/fiber supplies
// react-reconciler 0.27 while the app's ReactDOM 18.3.1 uses reconciler 0.29.2.
// The Playwright acceptance test covers the actual DOM renderer behavior.
const reconcile = fiberRequire('react-reconciler') as (
    host: Record<string, unknown>
) => HostRenderer
const { ConcurrentRoot, DefaultEventPriority } = fiberRequire('react-reconciler/constants') as {
    ConcurrentRoot: number
    DefaultEventPriority: number
}

function concurrentRoot() {
    const snapshots: string[] = []
    const container: HostNode = { type: 'root', props: {}, children: [], focus: () => {} }
    const remove = (parent: HostNode, child: HostNode) => {
        parent.children = parent.children.filter(item => item !== child)
    }
    const append = (parent: HostNode, child: HostNode) => {
        remove(parent, child)
        parent.children.push(child)
    }
    const renderer = reconcile({
        now: Date.now,
        supportsMutation: true,
        isPrimaryRenderer: true,
        getRootHostContext: () => ({}),
        getChildHostContext: () => ({}),
        getPublicInstance: (instance: HostNode) => instance,
        prepareForCommit: () => null,
        // This runs after host mutations and before layout effects, so the captured
        // tree proves what React actually committed before reset effects ran.
        resetAfterCommit: () => snapshots.push(committedSnapshot(container)),
        shouldSetTextContent: () => false,
        createInstance: (type: string, props: Record<string, unknown>) => ({
            type,
            props,
            children: [],
            focus: () => {},
        }),
        createTextInstance: (text: string) => ({
            type: 'text',
            props: {},
            children: [],
            text,
            focus: () => {},
        }),
        appendInitialChild: append,
        appendChild: append,
        appendChildToContainer: append,
        insertBefore: (parent: HostNode, child: HostNode, before: HostNode) => {
            remove(parent, child)
            parent.children.splice(parent.children.indexOf(before), 0, child)
        },
        insertInContainerBefore: (parent: HostNode, child: HostNode, before: HostNode) => {
            remove(parent, child)
            parent.children.splice(parent.children.indexOf(before), 0, child)
        },
        removeChild: remove,
        removeChildFromContainer: remove,
        clearContainer: (parent: HostNode) => {
            parent.children = []
        },
        finalizeInitialChildren: () => false,
        prepareUpdate: () => true,
        commitUpdate: (
            instance: HostNode,
            _payload: unknown,
            _type: unknown,
            _previous: unknown,
            props: Record<string, unknown>
        ) => {
            instance.props = props
        },
        commitTextUpdate: (instance: HostNode, _previous: string, next: string) => {
            instance.text = next
        },
        resetTextContent: () => {},
        hideInstance: () => {},
        unhideInstance: () => {},
        hideTextInstance: () => {},
        unhideTextInstance: () => {},
        scheduleTimeout: setTimeout,
        cancelTimeout: clearTimeout,
        noTimeout: -1,
        getCurrentEventPriority: () => DefaultEventPriority,
        detachDeletedInstance: () => {},
    })
    const root = renderer.createContainer(
        container,
        ConcurrentRoot,
        null,
        false,
        null,
        '',
        (error: unknown) => {
            throw error
        },
        null
    )
    return { container, root, renderer, snapshots }
}

function result(resumeId: string, title: string, content: string, line = 7) {
    return {
        resume_id: resumeId,
        resume_title: title,
        updated_at: '2026-10-16T12:00:00Z',
        matches: [
            {
                line_number: line,
                line_content: content,
                context_before: [],
                context_after: [],
                highlight_start: 0,
                highlight_end: content.length,
            },
        ],
    }
}

function harness(strict = false) {
    vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
    const host = concurrentRoot()
    const onClose = vi.fn()
    const renderTree = async (tree: React.ReactNode) => {
        await act(async () => {
            host.renderer.updateContainer(tree, host.root, null, null)
        })
    }
    const render = async (ownerId: string | null, open = true) => {
        const modal = createElement(ProjectSearchModal, { ownerId, open, onClose })
        const tree = strict ? createElement(StrictMode, null, modal) : modal
        await renderTree(tree)
    }
    const input = () => descendants(host.container).find(node => node.type === 'input')
    const typeQuery = async (query: string) => {
        const field = input()
        if (!field) throw new Error('Search input was not rendered')
        await act(async () => {
            const onChange = field.props.onChange as
                ((event: { target: { value: string } }) => void) | undefined
            if (!onChange) throw new Error('Search input has no change handler')
            onChange({ target: { value: query } })
            vi.advanceTimersByTime(300)
        })
    }
    const settle = async (promise: Promise<unknown>) => {
        await act(async () => {
            await promise
        })
    }
    const unmount = async () => {
        await act(async () => {
            host.renderer.updateContainer(null, host.root, null, null)
        })
    }
    return { ...host, onClose, render, renderTree, input, typeQuery, settle, unmount }
}

function loadingVisible(container: HostNode) {
    return descendants(container).some(node =>
        String(node.props.className ?? '').includes('animate-spin')
    )
}

function resultRow(container: HostNode, title: string) {
    return descendants(container).find(
        node =>
            typeof node.props.onClick === 'function' &&
            String(node.props.className ?? '').includes('border-b') &&
            textContent(node).includes(title)
    )
}

function rowIsSelected(row: HostNode | undefined) {
    return String(row?.props.className ?? '')
        .split(/\s+/)
        .includes('bg-surface-2')
}

beforeEach(() => {
    vi.useFakeTimers()
    search.mockReset()
    router.push.mockReset()
})

afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
})

describe('workspace search owner isolation with React', () => {
    it('masks search data across a same-mounted A → logged out → A transition, including stale completion', async () => {
        const h = harness(true)
        const oldSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        const freshSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        search.mockReturnValueOnce(oldSearch.promise).mockReturnValueOnce(freshSearch.promise)
        try {
            await h.render('account-a')
            await h.typeQuery('same phrase')
            expect(search).toHaveBeenCalledTimes(1)

            await h.render(null)
            expect(h.input()?.props.value).toBe('')
            expect(h.snapshots[h.snapshots.length - 1]).not.toContain('Account A Private Resume')
            await h.render('account-a')
            expect(h.input()?.props.value).toBe('')
            expect(h.snapshots[h.snapshots.length - 1]).not.toContain('Account A Private Resume')

            await h.typeQuery('same phrase')
            expect(search).toHaveBeenCalledTimes(2)
            oldSearch.resolve({
                results: [result('resume-old', 'Account A Private Resume', 'old private phrase')],
            })
            await h.settle(oldSearch.promise)
            expect(loadingVisible(h.container)).toBe(true)
            expect(textContent(h.container)).not.toContain('Account A Private Resume')
            expect(textContent(h.container)).not.toContain('old private phrase')

            freshSearch.resolve({
                results: [result('resume-fresh', 'Account A Fresh Resume', 'fresh phrase')],
            })
            await h.settle(freshSearch.promise)
            expect(textContent(h.container)).toContain('Account A Fresh Resume')
            expect(textContent(h.container)).not.toContain('Account A Private Resume')
        } finally {
            await h.unmount()
        }
    })

    it('keeps account B loading/results isolated from late A success and error for the same query', async () => {
        const h = harness()
        const accountASuccess = deferred<{ results: ReturnType<typeof result>[] }>()
        const accountBSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        const accountAError = deferred<never>()
        const accountBSearchAfterError = deferred<{ results: ReturnType<typeof result>[] }>()
        search
            .mockReturnValueOnce(accountASuccess.promise)
            .mockReturnValueOnce(accountBSearch.promise)
            .mockReturnValueOnce(accountAError.promise)
            .mockReturnValueOnce(accountBSearchAfterError.promise)
        try {
            await h.render('account-a')
            await h.typeQuery('shared query')
            await h.render('account-b')
            await h.typeQuery('shared query')
            expect(loadingVisible(h.container)).toBe(true)

            accountASuccess.resolve({
                results: [result('resume-a', 'Account A Private Resume', 'A secret phrase')],
            })
            await h.settle(accountASuccess.promise)
            expect(loadingVisible(h.container)).toBe(true)
            expect(textContent(h.container)).not.toContain('Account A Private Resume')

            // Start a newer A request from a separate lifecycle and leave it in flight
            // while B's current request is still loading.
            await h.render('account-a')
            await h.typeQuery('shared query')
            await h.render('account-b')
            await h.typeQuery('shared query')
            accountAError.reject(new Error('Account A private failure'))
            await h.settle(accountAError.promise.catch(() => undefined))
            expect(loadingVisible(h.container)).toBe(true)
            expect(textContent(h.container)).not.toContain('Account A private failure')

            accountBSearchAfterError.resolve({
                results: [result('resume-b', 'Account B Resume', 'B visible phrase')],
            })
            await h.settle(accountBSearchAfterError.promise)
            expect(textContent(h.container)).toContain('Account B Resume')
            expect(textContent(h.container)).not.toContain('Account A Private Resume')
        } finally {
            await h.unmount()
        }
    })

    it('keeps the committed owner usable when a concurrent account-switch render suspends and is abandoned', async () => {
        const h = harness()
        const accountASearch = deferred<{ results: ReturnType<typeof result>[] }>()
        const suspendedTransition = deferred<void>()
        search.mockReturnValueOnce(accountASearch.promise)
        let setOwner: ((ownerId: string) => void) | undefined
        let suspendAccountB = true
        function SuspendAccountB({ ownerId }: { ownerId: string }) {
            if (suspendAccountB && ownerId === 'account-b') throw suspendedTransition.promise
            return null
        }
        function App() {
            const [ownerId, updateOwner] = useState('account-a')
            setOwner = updateOwner
            return createElement(
                Suspense,
                { fallback: createElement('fallback') },
                createElement(
                    Fragment,
                    null,
                    createElement(ProjectSearchModal, { open: true, ownerId, onClose: h.onClose }),
                    createElement(SuspendAccountB, { ownerId })
                )
            )
        }
        try {
            await h.renderTree(createElement(App))
            await h.typeQuery('pending owner A')
            await act(async () => startTransition(() => setOwner?.('account-b')))
            expect(h.input()?.props.value).toBe('pending owner A')
            expect(textContent(h.container)).not.toContain('fallback')

            accountASearch.resolve({
                results: [result('resume-a', 'Still Current A', 'committed A result')],
            })
            await h.settle(accountASearch.promise)
            expect(textContent(h.container)).toContain('Still Current A')

            suspendAccountB = false
            await act(async () => {
                suspendedTransition.resolve()
                await suspendedTransition.promise
            })
            expect(h.input()?.props.value).toBe('')
            expect(textContent(h.container)).not.toContain('Still Current A')
        } finally {
            suspendedTransition.resolve()
            await h.unmount()
        }
    })

    it('hides old results in the committed tree before layout effects on close/reopen', async () => {
        const h = harness()
        const previousSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        const failedSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        search.mockReturnValueOnce(previousSearch.promise).mockReturnValueOnce(failedSearch.promise)
        try {
            await h.render('account-a')
            await h.typeQuery('reopen phrase')
            previousSearch.resolve({
                results: [result('resume-a', 'Private Resume A', 'private reopen phrase')],
            })
            await h.settle(previousSearch.promise)
            expect(textContent(h.container)).toContain('Private Resume A')

            await h.render('account-a', false)
            const resultReopenStart = h.snapshots.length
            await h.render('account-a', true)
            expect(h.input()?.props.value).toBe('')
            const resultReopenCommits = h.snapshots.slice(resultReopenStart)
            expect(resultReopenCommits.length).toBeGreaterThan(0)
            expect(resultReopenCommits.every(snapshot =>
                !snapshot.includes('Private Resume A') &&
                !snapshot.includes('private reopen phrase') &&
                !snapshot.includes('input[value=reopen phrase]')
            )).toBe(true)
            expect(textContent(h.container)).not.toContain('private reopen phrase')

            await h.typeQuery('private error query')
            expect(search).toHaveBeenCalledTimes(2)
            failedSearch.reject(new Error('private account search error'))
            await h.settle(failedSearch.promise.catch(() => undefined))
            expect(textContent(h.container)).toContain('private account search error')

            await h.render('account-a', false)
            const errorReopenStart = h.snapshots.length
            await h.render('account-a', true)
            const errorReopenCommits = h.snapshots.slice(errorReopenStart)
            expect(errorReopenCommits.length).toBeGreaterThan(0)
            expect(errorReopenCommits.every(snapshot =>
                !snapshot.includes('private account search error') &&
                !snapshot.includes('input[value=private error query]') &&
                !snapshot.includes('Private Resume A')
            )).toBe(true)
        } finally {
            failedSearch.resolve({ results: [] })
            await h.unmount()
        }
    })

    it('retains keyboard selection behavior after an isolated search', async () => {
        const h = harness()
        const matchingSearch = deferred<{ results: ReturnType<typeof result>[] }>()
        search.mockReturnValueOnce(matchingSearch.promise)
        try {
            await h.render('account-a')
            await h.typeQuery('match')
            matchingSearch.resolve({
                results: [
                    result('resume-a', 'First Resume', 'first match', 3),
                    result('resume-b', 'Second Resume', 'second match', 19),
                ],
            })
            await h.settle(matchingSearch.promise)
            expect(rowIsSelected(resultRow(h.container, 'First Resume'))).toBe(true)
            expect(rowIsSelected(resultRow(h.container, 'Second Resume'))).toBe(false)

            await act(async () => {
                const onKeyDown = h.input()?.props.onKeyDown as
                    ((event: { key: string; preventDefault: () => void }) => void) | undefined
                onKeyDown?.({ key: 'ArrowDown', preventDefault: vi.fn() })
            })
            expect(rowIsSelected(resultRow(h.container, 'First Resume'))).toBe(false)
            expect(rowIsSelected(resultRow(h.container, 'Second Resume'))).toBe(true)

            await act(async () => {
                const onKeyDown = h.input()?.props.onKeyDown as
                    ((event: { key: string; preventDefault: () => void }) => void) | undefined
                onKeyDown?.({ key: 'Enter', preventDefault: vi.fn() })
            })
            expect(router.push).toHaveBeenCalledWith('/workspace/resume-b/edit?line=19')
            expect(h.onClose).toHaveBeenCalledOnce()
        } finally {
            await h.unmount()
        }
    })
})
