import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ReactElement } from 'react'
import PdfImportWizard from '@/components/PdfImportWizard'
import type { EngineCapability } from '@/lib/engine-capability'

const state = vi.hoisted(() => ({ capability: { status: 'loading' } as EngineCapability | { status: 'loading' }, admitted: { current: null as unknown } }))
vi.mock('react', async original => ({ ...await original<typeof import('react')>(), useRef: () => state.admitted }))
vi.mock('@/hooks/useEngineCapability', () => ({ useEngineCapability: () => ({ ...state.capability, checking: state.capability.status === 'loading', retry: vi.fn() }) }))
vi.mock('@/components/PDFPreview', () => ({ default: () => null }))
afterEach(() => { state.admitted.current = null; state.capability = { status: 'loading' } })

const file = new File(['synthetic PDF'], 'resume.pdf', { type: 'application/pdf' })
const props = { file, title: 'Keep my title', ownerId: 'owner-a', onCreated: vi.fn(), onCancel: vi.fn() }
function wizard(overrides: Partial<typeof props> = {}) {
  const tree = PdfImportWizard({ ...props, ...overrides })
  return tree.props.children[1] as ReactElement<{ enabled?: boolean; file?: File; title?: string }>
}

describe('PDF import staged rollout gate', () => {
  it.each([{ status: 'loading' }, { status: 'unsupported' }, { status: 'error', reason: 'authorization' }, { status: 'error', reason: 'unavailable' }] as const)('does not mount the uploading wizard for $status', capability => {
    state.capability = capability
    expect(wizard().type).toBe('section')
  })
  it('passes the exact selected file and title only after support is confirmed', () => {
    state.capability = { status: 'supported' }
    expect(wizard().props).toMatchObject({ file, title: 'Keep my title', enabled: true })
  })
  it('preserves reviewed field state across a same-file recheck while disabling adaptation', () => {
    state.capability = { status: 'supported' }
    const original = wizard()
    state.capability = { status: 'error', reason: 'authorization' }
    expect(wizard().type).toBe(original.type)
    expect(wizard().props.enabled).toBe(false)
    state.capability = { status: 'supported' }
    expect(wizard().type).toBe(original.type)
    expect(wizard().props.enabled).toBe(true)
  })
  it('does not inherit admission for a different account or selected file', () => {
    state.capability = { status: 'supported' }; wizard()
    state.capability = { status: 'unsupported' }
    expect(wizard({ ownerId: 'owner-b' }).type).toBe('section')
    expect(wizard({ file: new File(['other PDF'], 'other.pdf') }).type).toBe('section')
  })
})
