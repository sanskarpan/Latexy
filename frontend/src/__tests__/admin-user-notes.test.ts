import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin internal user notes, tags and support timeline', () => {
  const component = read('../components/admin/AdminUserNotes.tsx')
  const userDetail = read('../components/admin/AdminUserDetail.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('is wired into User 360 for both admin and support viewers', () => {
    expect(userDetail).toContain("import AdminUserNotes from './AdminUserNotes'")
    expect(userDetail).toContain('<AdminUserNotes userId={userId} canAdmin={canAdmin} />')
    expect(component).toContain('Internal notes, tags and support timeline')
    expect(component).toContain('Support can edit only its own internal notes')
  })

  it('wires note, tag and merged timeline CRUD endpoints', () => {
    expect(apiClient).toContain('/admin/users/${encodeURIComponent(id)}/notes')
    expect(apiClient).toContain('/admin/users/${encodeURIComponent(id)}/tags')
    expect(apiClient).toContain('/admin/users/${encodeURIComponent(id)}/support-timeline')
    expect(apiClient).toContain('getAdminUserNotes')
    expect(apiClient).toContain('createAdminUserNote')
    expect(apiClient).toContain('updateAdminUserNote')
    expect(apiClient).toContain('deleteAdminUserNote')
    expect(apiClient).toContain('getAdminUserTags')
    expect(apiClient).toContain('createAdminUserTag')
    expect(apiClient).toContain('removeAdminUserTag')
    expect(apiClient).toContain('getAdminUserSupportTimeline')
  })

  it('requires reasons, confirmations and optimistic concurrency', () => {
    expect(component).toContain('Reason for this note/tag session')
    expect(component).toContain('Enter a reason of at least 3 characters')
    expect(component).toContain('window.confirm')
    expect(component).toContain('expected_version: note.version')
    expect(component).toContain('confirm: true')
    expect(component).toContain('soft-delete')
    expect(component).toContain('Note bodies never enter the audit log')
  })

  it('offers note filters, tag filters and timeline pagination', () => {
    expect(component).toContain('Filter notes by tag')
    expect(component).toContain('Filter support timeline')
    expect(component).toContain('Merged support timeline')
    expect(component).toContain('Page {notePage}')
    expect(component).toContain('Page {timelinePage}')
    expect(component).toContain('Newer')
    expect(component).toContain('Older')
    expect(component).toContain('timeline?.next_offset')
  })

  it('renders note text as escaped React children, never HTML', () => {
    expect(component).toContain('{note.body}')
    expect(component).toContain('{item.summary')
    expect(component).not.toContain('dangerouslySetInnerHTML')
    expect(component).not.toContain('innerHTML')
    expect(userDetail).not.toContain('dangerouslySetInnerHTML')
    expect(component).not.toContain('eval(')
    expect(component).toContain('whitespace-pre-wrap')
  })

  it('keeps admin-only notes, approvals and PII reveals behind the admin flag', () => {
    expect(component).toContain("visibility === 'admin_only'")
    expect(component).toContain('ADMIN_ONLY_TIMELINE_KINDS')
    expect(component).toContain("['approval', 'pii_reveal']")
    expect(component).toContain('Restricted for support')
    expect(apiClient).toContain('include_deleted')
    expect(apiClient).toContain('include_removed')
  })

  it('states the retention and no-PII boundary', () => {
    expect(component).toContain('support-notes retention policy')
    expect(component).toContain('no worker deletes them automatically')
    expect(component).toContain('never appear on customer APIs')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('document_body')
    expect(component).not.toContain('user_agent')
  })
})
