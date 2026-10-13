import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function label(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(label).join(' ')
  return value && typeof value === 'object' && 'props' in value ? label((value as Element).props.children) : ''
}

async function harness(authenticated = true) {
  vi.resetModules()
  let index = 0
  let grants = new Set(['b04', 'b05', 'b01', 'c01'])
  const slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void }> = []
  let effects: Array<() => void> = []
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  const memo = (callback: () => unknown, deps: unknown[]) => {
    const slot = index++
    if (!slots[slot] || !sameDeps(slots[slot].deps, deps)) slots[slot] = { value: callback(), deps }
    return slots[slot].value
  }
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useRef: (initial: unknown) => { const slot = index++; slots[slot] ??= { value: { current: initial } }; return slots[slot].value },
    useState: (initial: unknown) => {
      const slot = index++; slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[slot].value, (next: unknown) => { slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[slot].value) : next }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => memo(() => callback, deps),
    useMemo: memo,
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = index++; const previous = slots[slot]
      if (!previous || !sameDeps(previous.deps, deps)) {
        const next = { deps, cleanup: previous?.cleanup }; slots[slot] = next
        effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
      }
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants; return { can: (key: string) => snapshot.has(key) }
  } }))
  const session = authenticated ? { user: { id: 'owner' } } : null
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: session, isPending: false, error: null }) }))
  const router = { push: vi.fn(), replace: vi.fn() }
  vi.doMock('next/navigation', () => ({ useRouter: () => router }))
  const toast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() })
  vi.doMock('sonner', () => ({ toast }))
  vi.doMock('@/components/TemplateCard', () => ({ default: 'template-card' }))
  vi.doMock('@/components/TemplatePreviewModal', () => ({ default: 'template-preview' }))
  vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn(), location: { search: '' }, prompt: vi.fn(() => 'en') })
  const templates = ['professional', 'academic', 'regional', 'presentation'].map(category => ({
    id: category, category, name: `${category} template`, category_label: category, description: '', tags: [],
  }))
  const api = { getTemplates: vi.fn().mockResolvedValue(templates), getTemplateCategories: vi.fn().mockResolvedValue(templates.map(template => ({ category: template.category, label: template.category, count: 1 }))), useTemplate: vi.fn().mockResolvedValue({ resume_id: 'created' }) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/app/templates/page')).default
  const render = () => { index = 0; return Component() }
  const flush = async () => { const queued = effects; effects = []; queued.forEach(effect => effect()); for (let i = 0; i < 8; i++) await Promise.resolve() }
  render(); await flush()
  const cards = (tree: unknown) => elements(tree).filter(node => node.type === 'template-card')
  const card = (tree: unknown, id: string) => cards(tree).find(node => (node.props.template as { id: string }).id === id)!
  const preview = (tree: unknown) => elements(tree).find(node => node.type === 'template-preview')!
  return { api, router, render, flush, card, cards, preview, allow: (keys: string[]) => { grants = new Set(keys) } }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/lib/auth-client', '@/lib/api-client', 'next/navigation', 'sonner', '@/components/TemplateCard', '@/components/TemplatePreviewModal']) vi.doUnmock(name)
  vi.unstubAllGlobals(); vi.resetModules()
})

it.each([true, false])('hides cached specialty cards/categories on B05 revocation while preserving regular browse (authenticated=%s)', async authenticated => {
  const h = await harness(authenticated)
  expect(h.cards(h.render())).toHaveLength(4)
  h.allow(['b04', 'b01', 'c01'])
  const tree = h.render()
  expect(h.cards(tree).map(node => (node.props.template as { id: string }).id)).toEqual(['professional'])
  const buttons = elements(tree).filter(node => node.type === 'button').map(label)
  expect(buttons.some(text => text.includes('academic'))).toBe(false)
  expect(buttons.some(text => text.includes('regional'))).toBe(false)
  expect(buttons.some(text => text.includes('presentation'))).toBe(false)
  expect(buttons.some(text => text.replace(/\s+/g, ' ').includes('All ( 1 )'))).toBe(true)
  h.allow(['b04', 'b05', 'b01', 'c01'])
  expect(h.cards(h.render())).toHaveLength(4)
})

it.each(['academic', 'regional', 'presentation'])('denies a retained %s preview/use callback and masks its open preview after revocation', async id => {
  const h = await harness()
  const oldCard = h.card(h.render(), id)
  const open = oldCard.props.onPreview as (id: string) => void
  const use = oldCard.props.onSelect as (id: string) => Promise<boolean>
  open(id)
  expect(h.preview(h.render()).props.templateId).toBe(id)
  h.allow(['b04', 'b01', 'c01'])
  expect(h.preview(h.render()).props.templateId).toBeNull()
  open(id)
  expect(h.preview(h.render()).props.templateId).toBeNull()
  expect(await use(id)).toBe(false)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
  const regular = h.card(h.render(), 'professional')
  ;(regular.props.onPreview as (id: string) => void)('professional')
  expect(h.preview(h.render()).props.templateId).toBe('professional')
  expect(await (regular.props.onSelect as (id: string) => Promise<boolean>)('professional')).toBe(true)
  expect(h.api.useTemplate).toHaveBeenCalledExactlyOnceWith('professional', undefined, undefined)
})

it('keeps an unrelated search and specialty selection preference while exposing permitted cards during revocation', async () => {
  const h = await harness()
  const search = elements(h.render()).find(node => node.type === 'input' && node.props.id === 'template-search')!
  ;(search.props.onChange as (event: unknown) => void)({ target: { value: 'template' } })
  const category = elements(h.render()).find(node => node.type === 'button' && label(node).includes('academic'))!
  ;(category.props.onClick as () => void)()
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['academic'])
  h.allow(['b04', 'b01', 'c01'])
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['professional'])
  expect(elements(h.render()).find(node => node.type === 'input' && node.props.id === 'template-search')?.props.value).toBe('template')
  h.allow(['b04', 'b05', 'b01', 'c01'])
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['academic'])
})

it('matches the server specialty categories exactly', async () => {
  const h = await harness()
  h.allow(['b04'])
  expect(h.cards(h.render())).toHaveLength(1)
  const server = readFileSync(new URL('../../../backend/app/api/template_routes.py', import.meta.url), 'utf8')
  expect(server).toContain('{"academic", "regional", "presentation"}')
})

it('keeps the owned outcome of an already-admitted template use after specialty revocation', async () => {
  const h = await harness()
  let resolve!: (result: { resume_id: string }) => void
  h.api.useTemplate.mockImplementation(() => new Promise(done => { resolve = done }))
  const use = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  const pending = use('academic')
  expect(h.api.useTemplate).toHaveBeenCalledOnce()
  h.allow(['b04', 'b01', 'c01'])
  h.render()
  resolve({ resume_id: 'created' })
  expect(await pending).toBe(true)
  expect(h.router.push).toHaveBeenCalledExactlyOnceWith('/workspace/created/edit')
})
