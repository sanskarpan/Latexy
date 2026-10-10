import { afterEach, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function label(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(label).join(' ')
  return value && typeof value === 'object' && 'props' in value ? label((value as Element).props.children) : ''
}
function button(tree: unknown, text: string): Element {
  const result = elements(tree).find((node) => node.type === 'button' && label(node).includes(text))
  expect(result, text).toBeDefined()
  return result!
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }

async function harness(kind: 'writing' | 'imports') {
  vi.resetModules()
  let index = 0
  let grants = new Set(['d06', 'd07', 'd10', 'g02'])
  const slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void }> = []
  let effects: Array<() => void> = []
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  const useEffect = (effect: () => void | (() => void), deps?: unknown[]) => {
    const slot = index++
    const previous = slots[slot]
    if (!previous || !sameDeps(previous.deps, deps)) {
      const next = { deps, cleanup: previous?.cleanup }
      slots[slot] = next
      effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
    }
  }
  vi.doMock('react', async (importOriginal) => ({
    ...await importOriginal<typeof import('react')>(),
    useEffect,
    useLayoutEffect: useEffect,
    useRef: (initial: unknown) => {
      const slot = index++
      slots[slot] ??= { value: { current: initial } }
      return slots[slot].value
    },
    useState: (initial: unknown) => {
      const slot = index++
      slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[slot].value, (next: unknown) => {
        slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[slot].value) : next
      }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => {
      const slot = index++
      if (!slots[slot] || !sameDeps(slots[slot].deps, deps)) slots[slot] = { value: callback, deps }
      return slots[slot].value
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({
    useEntitlements: () => {
      // Each server refresh creates a fresh callback, including unchanged grants.
      const snapshot = grants
      return { can: (feature: string) => snapshot.has(feature) }
    },
  }))
  const api = {
    rewriteText: vi.fn(),
    suggestSynonyms: vi.fn().mockResolvedValue({ synonyms: ['replacement'] }),
    generateBulletVariants: vi.fn(),
    getBulletVariants: vi.fn().mockResolvedValue([{ id: 'set', target_label: 'Saved target', source_text: 'selected', options: ['saved option'] }]),
    deleteBulletVariantSet: vi.fn().mockResolvedValue(undefined),
    getGitHubStatus: vi.fn().mockResolvedValue({ connected: true }),
    importGitHubProjects: vi.fn().mockResolvedValue({ job_id: 'job' }),
    getGitHubImportResult: vi.fn().mockResolvedValue({ status: 'pending' }),
  }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
  const Component = kind === 'writing'
    ? (await import('@/components/WritingAssistantWidget')).default
    : (await import('@/components/ImportProjectsModal')).default
  const onAccept = vi.fn()
  const props = { isOpen: true, selectedText: 'selected', context: '', resumeId: 'resume', jobDescription: '', documentLatex: '', onAccept, onClose: vi.fn(), onInsert: vi.fn(), top: 10 }
  return {
    api, onAccept,
    allow: (features: string[]) => { grants = new Set(features) },
    render: () => { index = 0; return (Component as (props: unknown) => unknown)(props) },
    flush: async () => { const queued = effects; effects = []; queued.forEach((effect) => effect()); await Promise.resolve(); await Promise.resolve() },
  }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/lib/api-client', 'sonner']) vi.doUnmock(name)
  vi.useRealTimers()
  vi.resetModules()
})

it('disables nested writing actions and retained callbacks on live revocation, independently of siblings', async () => {
  const h = await harness('writing')
  const initial = h.render()
  const oldSynonyms = button(initial, 'Synonyms')
  const oldVariants = button(initial, 'Generate 3 variants')
  h.allow(['d06'])
  const denied = h.render()
  expect(button(denied, 'Improve').props.disabled).toBe(false)
  expect(button(denied, 'Synonyms').props.disabled).toBe(true)
  expect(button(denied, 'Generate 3 variants').props.disabled).toBe(true)
  await click(oldSynonyms)
  click(oldVariants)
  expect(h.api.suggestSynonyms).not.toHaveBeenCalled()
  expect(h.api.generateBulletVariants).not.toHaveBeenCalled()
  h.allow(['d07'])
  const synonymsOnly = h.render()
  expect(button(synonymsOnly, 'Improve').props.disabled).toBe(true)
  expect(button(synonymsOnly, 'Synonyms').props.disabled).toBe(false)
  await click(button(synonymsOnly, 'Synonyms'))
  expect(h.api.suggestSynonyms).toHaveBeenCalledOnce()
  const replacement = button(h.render(), 'replacement')
  h.allow([])
  expect(button(h.render(), 'replacement').props.disabled).toBe(true)
  click(replacement)
  expect(h.onAccept).not.toHaveBeenCalled()
})

it('keeps saved bullet reads, copy, and deletion available when generation is denied', async () => {
  const h = await harness('writing')
  h.allow([])
  const saved = button(h.render(), 'Saved bullet library')
  expect(saved.props.disabled).not.toBe(true)
  await click(saved)
  await Promise.resolve()
  const library = h.render()
  expect(h.api.getBulletVariants).toHaveBeenCalledWith('resume')
  expect(button(library, 'Copy').props.disabled).not.toBe(true)
  const remove = elements(library).find((node) => node.props['aria-label'] === 'Delete variants for Saved target')!
  expect(remove).toBeDefined()
  expect(remove.props.disabled).not.toBe(true)
  await click(remove)
  expect(h.api.deleteBulletVariantSet).toHaveBeenCalledWith('set')
})

it('does not resubmit GitHub imports on an unchanged entitlement refresh', async () => {
  vi.useFakeTimers()
  const h = await harness('imports')
  h.allow(['g02'])
  h.render()
  await h.flush()
  expect(h.api.importGitHubProjects).toHaveBeenCalledOnce()
  h.allow(['g02'])
  h.render()
  await h.flush()
  expect(h.api.getGitHubStatus).toHaveBeenCalledOnce()
  expect(h.api.importGitHubProjects).toHaveBeenCalledOnce()
  h.allow([])
  const denied = h.render()
  expect(button(denied, 'Insert into resume').props.disabled).toBe(true)
  await h.flush()
  await vi.advanceTimersByTimeAsync(2500)
  expect(h.api.importGitHubProjects).toHaveBeenCalledOnce()
  expect(h.api.getGitHubImportResult).not.toHaveBeenCalled()
})
