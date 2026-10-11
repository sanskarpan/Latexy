import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const tracker = ts.createSourceFile('tracker.tsx', readFileSync(new URL('../app/tracker/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const addModal = ts.createSourceFile('add.tsx', readFileSync(new URL('../components/AddApplicationModal.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function component(source: ts.SourceFile, name: string) {
  const node = source.statements.find((item): item is ts.FunctionDeclaration => ts.isFunctionDeclaration(item) && item.name?.text === name)
  if (!node?.body) throw new Error(`Missing component ${name}`)
  return node.body
}

function handler(source: ts.SourceFile, owner: string, name: string, context: Record<string, unknown> = {}) {
  let expression: ts.Expression | undefined
  function visit(node: ts.Node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name) expression = node.initializer
    ts.forEachChild(node, visit)
  }
  visit(component(source, owner))
  if (!expression) throw new Error(`Missing handler ${owner}.${name}`)
  const deniedCan = vi.fn(() => false)
  const dependencies = { can: deniedCan, canRef: { current: deniedCan }, useCallback: (callback: unknown) => callback, rawEmail: '', boardData: {}, findColumn: vi.fn(), ...context }
  const output = ts.transpileModule(`const action = ${expression.getText(source)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText
  return new Function(...Object.keys(dependencies), `${output}\nreturn action`)(...Object.values(dependencies)) as (...args: unknown[]) => Promise<void> | void
}

function buttons(owner: string, source = tracker) {
  const result: ts.JsxElement[] = []
  function visit(node: ts.Node) {
    if (ts.isJsxElement(node) && node.openingElement.tagName.getText(source) === 'button') result.push(node)
    ts.forEachChild(node, visit)
  }
  visit(component(source, owner))
  return result
}

function button(owner: string, token: string, source = tracker) {
  const node = buttons(owner, source).find((item) => item.getText(source).includes(token))
  if (!node) throw new Error(`Missing button ${owner}: ${token}`)
  return node
}

function disabled(node: ts.JsxElement, source = tracker) {
  return node.openingElement.attributes.properties.find((property) => ts.isJsxAttribute(property) && property.name.getText(source) === 'disabled')?.getText(source) ?? ''
}

describe('tracker effective-capability controls', () => {
  it.each([
    ['SavedJobsPanel', 'save'], ['SavedJobsPanel', 'startEdit'], ['SavedJobsPanel', 'track'],
    ['AlertsPanel', 'save'], ['AlertsPanel', 'startEdit'],
    ['ContactsPanel', 'saveContact'], ['ContactsPanel', 'saveCompany'], ['ContactsPanel', 'editContact'], ['ContactsPanel', 'editCompany'],
    ['ApplicationWorkflowPanel', 'saveReminder'], ['ApplicationWorkflowPanel', 'saveInterview'], ['ApplicationWorkflowPanel', 'editReminder'], ['ApplicationWorkflowPanel', 'editInterview'],
    ['OutreachDraftPanel', 'generateDraft'], ['EmailStatusReviewPanel', 'parseEmail'],
    ['TrackerPage', 'handleDragStart'], ['TrackerPage', 'handleStatusChange'], ['EditApplicationModal', 'handleSubmit'],
  ])('blocks %s.%s before state changes or network calls when unavailable', async (owner, name) => {
    const action = handler(tracker, owner, name)
    await action({ preventDefault: vi.fn() })
  })

  it('blocks application submission from an already-open add modal', async () => {
    await handler(addModal, 'AddApplicationModal', 'handleSubmit')({ preventDefault: vi.fn() })
    expect(disabled(button('AddApplicationModal', "'Adding…'", addModal), addModal)).toContain("!can('e05')")
  })

  it.each(['handleDragOver', 'handleDragEnd'])('restores an optimistic drag if access is revoked before %s', async (name) => {
    const restoreCancelledDrag = vi.fn()
    await handler(tracker, 'TrackerPage', name, { restoreCancelledDrag })({})
    expect(restoreCancelledDrag).toHaveBeenCalledOnce()
  })

  it('reads the current capability when invoking an existing status callback', async () => {
    const canRef = { current: vi.fn(() => true) }
    const findColumn = vi.fn()
    const action = handler(tracker, 'TrackerPage', 'handleStatusChange', { canRef, findColumn })
    canRef.current = vi.fn(() => false)
    await action('app-id', 'offer')
    expect(canRef.current).toHaveBeenCalledWith('e05')
    expect(findColumn).not.toHaveBeenCalled()
  })

  it('requires both application and saved-job access to track a saved role', async () => {
    for (const denied of ['e05', 'e06']) {
      await handler(tracker, 'SavedJobsPanel', 'track', { can: (key: string) => key !== denied })({ id: 'saved' })
    }
    const control = button('SavedJobsPanel', 'void track(job)')
    expect(disabled(control)).toContain("!can('e05') || !can('e06')")
    expect(control.getText(tracker)).toContain("{(!can('e05') || !can('e06')) && <span")
  })

  it('allows pausing an existing alert while denying resume', async () => {
    const updateAlert = vi.fn().mockResolvedValue({ id: 'alert', active: false })
    const setAlerts = vi.fn()
    const action = handler(tracker, 'AlertsPanel', 'toggle', { apiClient: { updateAlert }, setAlerts })
    await action({ id: 'alert', active: false })
    expect(updateAlert).not.toHaveBeenCalled()
    await action({ id: 'alert', active: true })
    expect(updateAlert).toHaveBeenCalledWith('alert', { active: false })
    expect(disabled(button('AlertsPanel', 'void toggle(alert)'))).toContain("!alert.active && !can('e06')")
  })

  it.each([
    ['ApplicationCard', 'onEdit(app)', 'e05'], ['ApplicationCard', 'onOutreach(app)', 'e09'],
    ['SavedJobsPanel', "'Update job'", 'e06'], ['SavedJobsPanel', 'startEdit(job)', 'e06'],
    ['AlertsPanel', "'Update alert'", 'e06'], ['AlertsPanel', 'startEdit(alert)', 'e06'],
    ['ContactsPanel', "'Update contact'", 'e08'], ['ContactsPanel', "'Update company'", 'e08'],
    ['ContactsPanel', 'editContact(contact)', 'e08'], ['ContactsPanel', 'editCompany(company)', 'e08'],
    ['ApplicationWorkflowPanel', "'Reschedule reminder'", 'e07'], ['ApplicationWorkflowPanel', "'Update interview'", 'e07'],
    ['ApplicationWorkflowPanel', 'editReminder(item)', 'e07'], ['ApplicationWorkflowPanel', 'editInterview(item)', 'e07'],
    ['OutreachDraftPanel', "'Regenerate draft'", 'e09'], ['EmailStatusReviewPanel', "'Reviewing…'", 'e10'],
    ['EmailStatusReviewPanel', 'void parseEmail()', 'e10'], ['EditApplicationModal', "'Save Changes'", 'e05'],
    ['TrackerPage', 'setEmailStatusReviewOpen(true)', 'e10'], ['TrackerPage', 'Add Application', 'e05'],
    ['TrackerPage', 'Add your first application', 'e05'],
  ])('disables and explains unavailable %s %s', (owner, token, key) => {
    const control = button(owner, token)
    expect(disabled(control)).toContain(`!can('${key}')`)
    expect(control.getText(tracker)).toContain('Unavailable for your current plan or feature settings')
    expect(control.getText(tracker)).toContain('(Unavailable)')
  })

  it.each([
    ['ApplicationCard', 'onDelete(app.id)'], ['ApplicationCard', 'onWorkflow(app)'],
    ['SavedJobsPanel', 'void remove(job.id)'], ['SavedJobsPanel', 'void bulkRemove()'],
    ['AlertsPanel', 'void remove(alert.id)'], ['ContactsPanel', 'void removeCompany(company.id)'], ['ContactsPanel', 'void remove(contact.id)'],
    ['ApplicationWorkflowPanel', 'void removeReminder(item)'], ['ApplicationWorkflowPanel', 'void removeInterview(item)'], ['ApplicationWorkflowPanel', 'void download(item)'],
    ['OutreachDraftPanel', "copy(draft.subject, 'Subject')"], ['OutreachDraftPanel', "copy(draft.body, 'Body')"],
    ['TrackerPage', 'setActiveTab(value)'], ['EmailStatusReviewPanel', 'onClick={closePanel}'],
    ['EditApplicationModal', 'Cancel'],
  ])('preserves safe management control %s %s', (owner, token) => {
    expect(disabled(button(owner, token))).not.toContain('can(')
  })

  it('disables card dragging and status selection without hiding existing cards', () => {
    expect(component(tracker, 'ApplicationCard').getText(tracker)).toContain("useSortable({ id: app.id, disabled: !can('e05') })")
    expect(component(tracker, 'ApplicationCard').getText(tracker)).toMatch(/id=\{`status-\$\{app.id\}`\}\s+disabled=\{!can\('e05'\)\}/)
  })
})
