import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import Panel from '@/components/SuggestionsPanel'
import { canCreateSuggestion, canResolveSuggestion, type Suggestion } from '@/lib/suggestions'

const suggestion: Suggestion = {
  id: 'peer:proposal', authorId: 'someone-else', authorName: 'Author', createdAt: 1,
  originalText: 'Before', replacementText: 'After', offset: 0, prefix: '', suffix: '', status: 'pending',
}
const page = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')

function buttonMarkup(markup: string, label: string): string {
  return [...markup.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)].map((match) => match[0]).find((button) => button.endsWith(` ${label}</button>`)) ?? ''
}

function props(role: string, f07: boolean, c01: boolean) {
  return {
    suggestions: [suggestion], canSuggest: f07 && canCreateSuggestion(role), admissionsEnabled: f07,
    canResolve: f07 && c01 && canResolveSuggestion(role), canReject: (item: Suggestion) => canResolveSuggestion(role) || item.authorId === 'current-user',
    modeEnabled: true, onToggleMode: vi.fn(), onCreate: vi.fn(), onAccept: vi.fn(), onReject: vi.fn(), error: null, onRetry: vi.fn(),
  }
}

// Render real panel markup, including its disabled buttons. This is component
// coverage; the browser test exercises navigation and live entitlement refresh.
describe('suggestion recovery panel', () => {
  it.each(['owner', 'editor'])('keeps rejection enabled for %s when F07 and C01 are off', (role) => {
    const markup = renderToStaticMarkup(createElement(Panel, props(role, false, false)))
    expect(buttonMarkup(markup, 'Accept')).toContain(' disabled=""')
    expect(buttonMarkup(markup, 'Reject')).toBeTruthy()
    expect(buttonMarkup(markup, 'Reject')).not.toContain(' disabled=""')
    expect(markup).toContain('New suggestions and acceptance are disabled')
    expect(markup).not.toContain('id="suggestion-find"')
    expect(markup).not.toContain('Viewers cannot suggest')
  })
  it.each(['viewer', 'commenter'])('does not let %s decide another actor’s suggestion', (role) => {
    const markup = renderToStaticMarkup(createElement(Panel, props(role, false, false)))
    expect(buttonMarkup(markup, 'Reject')).toContain(' disabled=""')
  })
  it('permits only local withdrawal for a nonresolver author', () => {
    const p = props('commenter', false, false)
    const markup = renderToStaticMarkup(createElement(Panel, { ...p, suggestions: [{ ...suggestion, authorId: 'current-user' }] }))
    expect(buttonMarkup(markup, 'Reject')).toBeTruthy()
    expect(buttonMarkup(markup, 'Reject')).not.toContain(' disabled=""')
  })
  it('keeps acceptance disabled when source editing alone is off', () => {
    const markup = renderToStaticMarkup(createElement(Panel, props('owner', true, false)))
    expect(markup).toContain('id="suggestion-find"')
    expect(buttonMarkup(markup, 'Accept')).toContain(' disabled=""')
  })
  it('wires recovery reachability and live source admission checks in the editor', () => {
    const tabMap = page.split('const RIGHT_TAB_CAPABILITIES:')[1].split('\n}')[0]
    expect(tabMap).not.toContain("suggestions: 'f07'")
    expect(page).toContain("{editorMode === 'source' && visibleRightTab === 'suggestions' && (")
    expect(page).toContain('canResolve={suggestionRecovery.canAccept}')
    expect(page).toContain('canReject={suggestionRecovery.canReject}')
    expect(page).toContain('ownerId: sessionUserId, documentId: resumeId')
    expect(page).toContain('finishSuggestionDocumentLoad(suggestionLoad, true, loadedRole)')
    expect(page).toContain('resumeId, sessionData, sessionLoading, sessionRefetching, sessionError, sessionUserId, setPreviewBlob, setRightTab])')
    expect(page).toContain('!sessionLoading && !sessionRefetching && !sessionError')
    expect(page).toContain('if (sessionLoading || sessionRefetching) return')
    const hook = readFileSync(new URL('../hooks/useSuggestionRecovery.ts', import.meta.url), 'utf8')
    expect(hook).toContain('ticket.identity !== scope.current')
    expect(hook).toContain("current.current.can('f07') && current.current.can('c01')")
    expect(hook).toContain('Withdrawal is local ephemeral state')
  })
})


describe('BYOK provider claims', () => {
  it('keeps pricing aligned with the catalog and registered provider families', () => {
    const pricing = readFileSync(new URL('../app/pricing/page.tsx', import.meta.url), 'utf8')
    const catalog = JSON.parse(readFileSync(new URL('../../../backend/app/core/capability_catalog.json', import.meta.url), 'utf8')) as Array<{ key: string; description: string }>
    const byok = catalog.find((feature) => feature.key === 'd25')!
    expect(pricing).toContain('Bring your own OpenAI / Anthropic / OpenRouter key')
    expect(pricing).not.toContain('Bring your own OpenAI / Anthropic / Gemini key')
    expect(byok.description).toContain('supported BYOK provider families are OpenAI, Anthropic and OpenRouter')
    expect(byok.description).toContain('Gemini BYOK is not supported')
  })
})
