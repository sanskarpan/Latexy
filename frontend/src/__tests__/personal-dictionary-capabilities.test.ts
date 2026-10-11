import { afterEach, describe, expect, it, vi } from 'vitest'

type Node = { type: unknown; props: Record<string, any> }

function find(root: unknown, predicate: (node: Node) => boolean): Node {
  const pending = [root]
  while (pending.length) {
    const node = pending.shift()
    if (!node || typeof node !== 'object' || !('props' in node)) continue
    const element = node as Node
    if (predicate(element)) return element
    pending.push(...[element.props.children].flat(Infinity))
  }
  throw new Error('Expected dictionary control is missing')
}

async function fixture(initialGrant: boolean) {
  vi.resetModules()
  let grant = initialGrant
  let cursor = 0
  const slots: any[] = []
  const addWord = vi.fn()
  const removeWord = vi.fn()
  const dictionary = vi.fn((_scope: unknown, _shouldSync: boolean) => ({ words: new Set(['known']), addWord, removeWord, loading: false, error: null }))
  vi.doMock('react', () => ({
    useMemo: (fn: () => unknown) => fn(),
    useEffect: () => {},
    useRef: (value: unknown) => {
      const index = cursor++
      slots[index] ??= { current: value }
      return slots[index]
    },
    useState: (value: unknown) => {
      const index = cursor++
      if (!(index in slots)) slots[index] = value
      return [slots[index], (next: unknown) => { slots[index] = next }]
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({ jsx: (type: unknown, props: unknown) => ({ type, props }), jsxs: (type: unknown, props: unknown) => ({ type, props }) }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session: { user: { id: 'dictionary-owner' }, session: { token: 'synthetic-token' } }, isPending: false, error: null }) }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: (key: string) => key === 'c16' && grant }) }))
  vi.doMock('@/hooks/useSpellCheck', () => ({ usePersonalDictionary: dictionary, normalizeDictionaryWord: (word: string) => word.trim().toLowerCase() }))
  const Component = (await import('@/components/PersonalDictionarySettings')).default
  return {
    render: () => { cursor = 0; return Component() },
    setGrant: (value: boolean) => { grant = value },
    addWord, removeWord, dictionary,
  }
}

afterEach(() => {
  for (const name of ['react', 'react/jsx-runtime', '@/hooks/useRequireAuth', '@/contexts/EntitlementsContext', '@/hooks/useSpellCheck']) vi.doUnmock(name)
  vi.resetModules()
})

describe('personal dictionary capability', () => {
  it('hides the dictionary and pauses synchronization without a verified c16 grant', async () => {
    const f = await fixture(false)
    expect(f.render()).toBeNull()
    expect(f.dictionary.mock.calls[0][1]).toBe(false)
    expect(f.addWord).not.toHaveBeenCalled()
    expect(f.removeWord).not.toHaveBeenCalled()
  })

  it('admits dictionary changes with a grant', async () => {
    const f = await fixture(true)
    let root = f.render()
    find(root, n => n.type === 'input').props.onChange({ target: { value: 'Example' } })
    root = f.render()
    find(root, n => n.type === 'form').props.onSubmit({ preventDefault: vi.fn() })
    expect(f.addWord).toHaveBeenCalledWith('example')
    find(root, n => n.props['aria-label'] === 'Remove known from personal dictionary').props.onClick()
    expect(f.removeWord).toHaveBeenCalledWith('known')
    expect(f.dictionary.mock.calls[f.dictionary.mock.calls.length - 1]?.[1]).toBe(true)
  })

  it('rejects captured add/remove callbacks after capability revocation', async () => {
    const f = await fixture(true)
    let root = f.render()
    find(root, n => n.type === 'input').props.onChange({ target: { value: 'Example' } })
    root = f.render()
    const add = find(root, n => n.type === 'form').props.onSubmit
    const remove = find(root, n => n.props['aria-label'] === 'Remove known from personal dictionary').props.onClick
    f.setGrant(false)
    expect(f.render()).toBeNull()
    add({ preventDefault: vi.fn() })
    remove()
    expect(f.addWord).not.toHaveBeenCalled()
    expect(f.removeWord).not.toHaveBeenCalled()
    expect(f.dictionary.mock.calls[f.dictionary.mock.calls.length - 1]?.[1]).toBe(false)
  })
})
