import { expect, test } from '@playwright/test'

type Visibility = {
  hidden_sections: string[]
  hidden_entries: Record<string, string[]>
  hidden_list_items: Record<string, Record<string, Array<{ index: number; value: string }>>>
}

const initialVisibility: Visibility = { hidden_sections: [], hidden_entries: {}, hidden_list_items: {} }

const structured = {
  basics: {
    name: 'Taylor Example', label: 'Engineer', email: 'taylor@example.com', phone: '',
    location: '', website: '', linkedin: '', github: '', summary: 'Platform engineer',
  },
  experience: [{
    id: 'role-1', title: 'Engineer', company: 'Acme', location: '', start_date: '',
    end_date: '', current: true, summary: '',
    bullets: ['Repeated achievement', 'Repeated achievement'], technologies: [],
  }],
  education: [], projects: [], skills: [], certifications: [], awards: [], languages: [], interests: [],
  section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
  hidden_sections: [],
}

const resume = {
  id: 'variant-1', user_id: 'user-1', title: 'Backend Variant', latex_content: '\\documentclass{article}',
  is_template: false, tags: [], parent_resume_id: 'master-1', selected_template_id: 'template-1',
  content_source: 'builder_variant', builder_status: 'active', structured_content: null,
  structured_version: 1, variant_visibility: initialVisibility,
  created_at: '2026-09-12T00:00:00Z', updated_at: '2026-09-12T00:00:00Z',
}

function response(visibility: Visibility = resume.variant_visibility) {
  const hidden = visibility.hidden_list_items.experience?.['role-1'] ?? []
  const bullets = structured.experience[0].bullets.filter(
    (value, index) => !hidden.some((selector) => selector.index === index && selector.value === value),
  )
  const effective = { ...structured, experience: [{ ...structured.experience[0], bullets }] }
  return {
    resume: { ...resume, variant_visibility: visibility },
    source_resume_id: 'master-1', source_title: 'Master Resume', source_content: structured,
    effective_content: effective, visibility,
    metrics: { completeness_score: 80, page_estimate: 1, warnings: [] },
    preview: {
      template_family: 'minimal',
      sections: [{ key: 'experience', title: 'Experience', items: [{ title: 'Engineer — Acme', bullets }] }],
    },
    template_family: 'minimal',
  }
}

test('linked variant stores occurrence-safe visibility without copying master content', async ({ page }) => {
  let savedBody: { title?: string; visibility: Visibility } | null = null
  await page.addInitScript(() => localStorage.setItem('latexy_onboarding_completed', 'true'))
  await page.route('**/api/auth/get-session', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session: { id: 'session-1', userId: 'user-1', token: 'token-1' },
      user: { id: 'user-1', email: 'user@example.com', name: 'Taylor' },
    }),
  }))
  await page.route((url) => url.pathname === '/tenants/resolve-host', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"tenant":null}',
  }))
  await page.route((url) => ['/config/feature-flags', '/config/entitlements'].includes(url.pathname), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }))
  await page.route((url) => url.pathname === '/resumes/variant-1/variant-visibility', async (route) => {
    if (route.request().method() === 'PATCH') {
      savedBody = route.request().postDataJSON()
      await route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(response(savedBody!.visibility)),
      })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(response()) })
  })

  await page.goto('/workspace/variant/variant-1')
  await expect(page.getByRole('heading', { name: 'Choose what this variant includes' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Master Resume' })).toHaveAttribute('href', '/workspace/builder/master-1')

  const duplicateBullets = page.getByText('Repeated achievement', { exact: true })
  await expect(duplicateBullets).toHaveCount(4)
  const bulletLabels = page.locator('label').filter({ hasText: 'Repeated achievement' })
  await bulletLabels.nth(1).getByRole('checkbox').uncheck()
  await page.getByRole('button', { name: 'Save visibility' }).click()

  await expect.poll(() => savedBody).not.toBeNull()
  expect(savedBody!.visibility.hidden_list_items).toEqual({
    experience: { 'role-1': [{ index: 1, value: 'Repeated achievement' }] },
  })
  expect('structured_content' in savedBody!).toBe(false)
  await expect(page.getByText('Variant visibility saved')).toBeVisible()
  await expect(page.getByText('Preview reflects the last saved visibility.')).toBeVisible()
})
