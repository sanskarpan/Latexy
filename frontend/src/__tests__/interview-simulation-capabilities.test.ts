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
function findButton(tree: unknown, text: string) {
  return elements(tree).find(node => node.type === 'button' && label(node).replace(/\s+/g, ' ').includes(text))
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }

async function harness() {
  vi.resetModules()
  let index = 0
  let grants = new Set(['e02', 'e03'])
  const slots: unknown[] = []
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useRef: (initial: unknown) => {
      const slot = index++
      slots[slot] ??= { current: initial }
      return slots[slot]
    },
    useState: (initial: unknown) => {
      const slot = index++
      if (!(slot in slots)) slots[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
      return [slots[slot], (next: unknown) => {
        slots[slot] = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[slot]) : next
      }]
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({
    useEntitlements: () => {
      const snapshot = grants
      return { can: (feature: string) => snapshot.has(feature) }
    },
  }))
  const api = { evaluateInterviewSimulation: vi.fn().mockResolvedValue({ feedback: [], overall_feedback: 'Admitted feedback' }) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/components/InterviewSimulation')).default
  const props: Parameters<typeof Component>[0] = { prepId: 'prep', questions: [{ question: 'Tell me about a project', category: 'behavioral', what_interviewer_assesses: 'Project experience', star_hint: null }] }
  const render = () => { index = 0; return Component(props) }
  const answer = (tree: unknown) => {
    const field = elements(tree).find(node => node.type === 'textarea')!
    ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'An answer longer than twenty characters' } })
  }
  return { api, render, answer, allow: (features: string[]) => { grants = new Set(features) } }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/lib/api-client']) vi.doUnmock(name)
  vi.resetModules()
})

it('hides E03 new sessions independently of the E02 prep grant and restores them when allowed', async () => {
  const h = await harness()
  h.allow(['e02'])
  expect(findButton(h.render(), 'Start Coach')).toBeUndefined()
  h.allow(['e03'])
  expect(findButton(h.render(), 'Start Coach')).toBeDefined()
})

it('rejects a retained start callback after E03 revocation without changing the draft', async () => {
  const h = await harness()
  const start = findButton(h.render(), 'Start Coach')!
  h.allow(['e02'])
  h.render()
  click(start)
  expect(elements(h.render()).some(node => node.type === 'textarea')).toBe(false)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
})

it('hides submission and rejects its retained callback after live E03 revocation', async () => {
  const h = await harness()
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  h.allow(['e02'])
  const denied = h.render()
  expect(findButton(denied, 'Finish session')).toBeUndefined()
  expect(elements(denied).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
  h.allow(['e03'])
  await click(findButton(h.render(), 'Finish session')!)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledExactlyOnceWith('prep', {
    mode: 'coach', answers: [{ question_index: 0, answer: 'An answer longer than twenty characters' }],
  })
})

it('retains already-admitted feedback after revocation while blocking a new session', async () => {
  const h = await harness()
  let resolve!: (value: { feedback: unknown[]; overall_feedback: string }) => void
  h.api.evaluateInterviewSimulation.mockImplementation(() => new Promise(done => { resolve = done }))
  click(findButton(h.render(), 'Mock mode')!)
  click(findButton(h.render(), 'Start Mock')!)
  h.answer(h.render())
  click(findButton(h.render(), 'Finish session')!)
  h.allow(['e02'])
  h.render()
  resolve({ feedback: [], overall_feedback: 'Admitted feedback' })
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
  expect(label(h.render())).toContain('Admitted feedback')
  expect(findButton(h.render(), 'Start another session')).toBeUndefined()
  h.allow(['e03'])
  const restart = findButton(h.render(), 'Start another session')!
  h.allow(['e02'])
  h.render()
  click(restart)
  expect(label(h.render())).toContain('Admitted feedback')
})
