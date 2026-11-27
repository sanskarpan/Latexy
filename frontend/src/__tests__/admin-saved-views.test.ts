import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin saved views and cohort builder', () => {
  const page = read('../app/admin/page.tsx')
  const component = read('../components/admin/AdminSavedViews.tsx')
  const analytics = read('../components/admin/AdminAnalytics.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('links saved views from the admin tabs and exposes a management tab', () => {
    expect(page).toContain(
      "import AdminSavedViews, { AdminSavedViewsBar } from '@/components/admin/AdminSavedViews'"
    )
    expect(page).toContain("{ id: 'views', label: 'Saved Views' }")
    expect(page).toContain('tab === \'views\' && <AdminSavedViews onApply={applySavedView} />')
    expect(page).toContain('<AdminSavedViewsBar')
    expect(page).toContain('onManage={() => setTab(\'views\')}')
    expect(component).toContain('Manage views & segments')
    expect(component).toContain('Per-admin and shared views')
  })

  it('restores the selected range and filters from the URL', () => {
    expect(page).toContain("params.get('days')")
    expect(page).toContain("params.get('view')")
    expect(page).toContain("key.startsWith('filter_')")
    expect(page).toContain("params.set('tab', view.scope)")
    expect(page).toContain("params.set('days', String(view.range_days))")
    expect(page).toContain('window.history.replaceState')
    expect(page).toContain('initialDays={analyticsDays}')
    expect(page).toContain('savedViewFilters={appliedView?.filters ?? {}}')
    expect(analytics).toContain('Saved view: {savedViewName}')
  })

  it('wires typed CRUD, preview and conflict-safe update methods', () => {
    expect(apiClient).toContain('/admin/saved-views')
    expect(apiClient).toContain('/admin/saved-views/catalog')
    expect(apiClient).toContain('/admin/segments/fields')
    expect(apiClient).toContain('/admin/segments/preview')
    expect(apiClient).toContain('getAdminSavedViews')
    expect(apiClient).toContain('createAdminSavedView')
    expect(apiClient).toContain('updateAdminSavedView')
    expect(apiClient).toContain('deleteAdminSavedView')
    expect(apiClient).toContain('previewAdminSegment')
    expect(apiClient).toContain('previewSavedAdminSegment')
    expect(apiClient).toContain('expected_version')
    expect(component).toContain('changed elsewhere. Reloading the latest version.')
    expect(component).toContain('concurrent edits return 409')
  })

  it('offers save, rename, share, default and audited delete actions', () => {
    expect(component).toContain('Save view')
    expect(component).toContain('Rename')
    expect(component).toContain('Share')
    expect(component).toContain('Make private')
    expect(component).toContain('Set default')
    expect(component).toContain('Reason for deleting')
    expect(component).toContain('soft-deleted and audited')
    expect(component).toContain('Every create, rename, share and delete is audited')
  })

  it('uses an allowlisted filter builder with no free-form SQL', () => {
    expect(component).toContain('Allowlisted filters')
    expect(component).toContain('No filters. The server accepts only the keys listed for this tab.')
    expect(component).toContain('every field and operator is compiled by the server')
    expect(component).toContain('Nothing here can execute SQL')
    expect(component).toContain('Segment condition')
    expect(component).toContain('Add condition')
    expect(component).toContain('Group preview by')
  })

  it('shows aggregate previews with five-user suppression', () => {
    expect(component).toContain('fewer than {preview.minimum_cohort} distinct users match')
    expect(component).toContain('The count is hidden')
    expect(component).toContain('hidden under the five-user rule')
    expect(component).toContain('aggregate-only')
    expect(component).toContain('No per-user rows')
    expect(component).toContain('suppressed_groups')
  })

  it('states the PII and document-content boundary', () => {
    expect(component).toContain('rejected when they look like PII, credentials or document content')
    expect(component).toContain('No per-user rows, emails, documents or provider payloads are returned.')
    expect(component).not.toContain('latex_content')
    expect(component).not.toContain('customer_email')
    expect(component).not.toContain('job_description')
    expect(component).not.toContain('user_agent')
  })
})
