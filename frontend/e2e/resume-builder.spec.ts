import { expect, test } from '@playwright/test'

import type {
  BuilderResumeResponse,
  BuilderSeedUploadResponse,
  BuilderTemplateResponse,
  StructuredResume,
} from '../src/lib/api-client'

const BUILDER_TEMPLATES: BuilderTemplateResponse[] = [
  {
    id: '11111111-1111-1111-1111-111111111111',
    name: 'ATS Guided',
    description: 'ATS-safe single column template',
    category: 'ats_safe',
    category_label: 'ATS-Safe',
    sort_order: 0,
    thumbnail_url: null,
    pdf_url: null,
    template_family: 'ats',
  },
  {
    id: '22222222-2222-2222-2222-222222222222',
    name: 'Executive Guided',
    description: 'Executive-facing builder template',
    category: 'executive',
    category_label: 'Executive',
    sort_order: 100,
    thumbnail_url: null,
    pdf_url: null,
    template_family: 'executive',
  },
]

const SEEDED_STRUCTURED: StructuredResume = {
  basics: {
    name: 'Taylor Builder',
    label: 'Senior Backend Engineer',
    email: 'taylor@example.com',
    phone: '+1-555-0102',
    location: 'Remote',
    website: 'https://example.com',
    linkedin: 'linkedin.com/in/taylor',
    github: 'github.com/taylor',
    summary: 'Backend engineer focused on reliability, distributed systems, and observability.',
  },
  experience: [
    {
      id: 'exp-1',
      title: 'Senior Backend Engineer',
      company: 'Acme',
      location: 'Remote',
      start_date: '2022',
      end_date: '',
      current: true,
      summary: '',
      bullets: ['Reduced p95 latency by 40%', 'Led API platform migration'],
      technologies: ['Python', 'PostgreSQL'],
    },
  ],
  education: [
    {
      id: 'edu-1',
      institution: 'State University',
      degree: 'B.S. Computer Science',
      field: '',
      location: '',
      start_date: '',
      end_date: '2020',
      gpa: '',
      highlights: [],
    },
  ],
  projects: [],
  skills: [{ id: 'skill-1', name: 'Core Skills', keywords: ['Python', 'Go', 'Distributed Systems'] }],
  certifications: [],
  awards: [],
  languages: [],
  interests: [],
  section_order: ['summary', 'experience', 'education', 'skills', 'projects', 'certifications', 'awards', 'languages', 'interests'],
  hidden_sections: [],
}

function builderResponse(overrides?: Partial<BuilderResumeResponse>): BuilderResumeResponse {
  return {
    resume: {
      id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
      user_id: 'user-1',
      title: 'Builder Resume',
      latex_content: '\\documentclass{article}\\begin{document}Builder\\end{document}',
      is_template: false,
      parent_resume_id: null,
      variant_count: 0,
      selected_template_id: BUILDER_TEMPLATES[0].id,
      content_source: 'builder',
      builder_status: 'active',
      structured_content: SEEDED_STRUCTURED,
      structured_version: 1,
      created_at: '2026-05-29T00:00:00Z',
      updated_at: '2026-05-29T00:00:00Z',
      document_type: 'resume',
      metadata: {},
    },
    metrics: {
      completeness_score: 84,
      page_estimate: 1,
      warnings: [],
      missing_sections: [],
    },
    preview: {
      template_family: 'ats',
      sections: [
        { key: 'summary', title: 'Summary', items: [SEEDED_STRUCTURED.basics.summary] },
        {
          key: 'experience',
          title: 'Experience',
          items: [
            {
              title: 'Senior Backend Engineer — Acme',
              meta: 'Remote | 2022 - Present',
              bullets: ['Reduced p95 latency by 40%', 'Led API platform migration'],
            },
          ],
        },
      ],
    },
    template_family: 'ats',
    ...overrides,
  }
}

async function mockSession(page: Parameters<typeof test.beforeEach>[0]['page']) {
  await page.route('**/api/auth/get-session', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: { id: 'sess-1', userId: 'user-1', token: 'token', expiresAt: '2099-01-01T00:00:00Z' },
        user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
      }),
    }),
  )
}

test.describe('Guided Resume Builder', () => {
  test.beforeEach(async ({ page }) => {
    await mockSession(page)
    await page.route('**/ws/**', route => route.abort())
  })

  test('workspace/new promotes the guided builder entry', async ({ page }) => {
    await page.goto('/workspace/new')
    await expect(page.getByRole('heading', { name: 'Guided Builder' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Open Guided Builder' })).toHaveAttribute('href', '/workspace/builder/new')
  })

  test('builder new flow loads templates, seeds upload, and creates a draft', async ({ page }) => {
    const seededResponse: BuilderSeedUploadResponse = {
      success: true,
      filename: 'resume.json',
      format: 'json',
      structured_content: SEEDED_STRUCTURED,
      metrics: {
        completeness_score: 82,
        page_estimate: 1,
        warnings: [],
        missing_sections: [],
      },
    }

    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(builderResponse()),
      }),
    )
    await page.route('**/resumes/builder/seed-upload', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(seededResponse) }),
    )
    await page.route('**/resumes/builder', async route => {
      if (route.request().method() !== 'POST') return route.fallback()
      const body = await route.request().postDataJSON()
      expect(body.title).toBe('Taylor Core Resume')
      expect(body.template_id).toBe(BUILDER_TEMPLATES[0].id)
      expect(body.structured_content.basics.name).toBe('Taylor Builder')
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify(builderResponse()),
      })
    })

    await page.goto('/workspace/builder/new')
    await expect(page.getByRole('heading', { name: 'Build from structured content' })).toBeVisible()
    await expect(page.getByText('1. Seed')).toBeVisible()
    await expect(page.getByRole('button', { name: /ATS-Safe ATS Guided/i })).toBeVisible()

    await page.locator('input[placeholder*="Senior Backend Engineer"]').fill('Taylor Core Resume')
    await page.locator('input[type="file"]').setInputFiles({
      name: 'resume.json',
      mimeType: 'application/json',
      buffer: Buffer.from('{"resume":"seed"}'),
    })

    await expect(page.getByText('Taylor Builder')).toBeVisible()
    await page.getByRole('button', { name: 'Start Guided Builder' }).click()
    await expect(page).toHaveURL(/\/workspace\/builder\/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa$/)
  })

  test('builder editor autosaves structured changes and supports template swaps', async ({ page }) => {
    let currentTemplateId = BUILDER_TEMPLATES[0].id
    let currentName = SEEDED_STRUCTURED.basics.name

    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder', async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(builderResponse()),
        })
      }
      if (route.request().method() === 'PATCH') {
        const body = await route.request().postDataJSON()
        currentTemplateId = body.template_id ?? currentTemplateId
        currentName = body.structured_content?.basics?.name ?? currentName
        const selectedTemplate = BUILDER_TEMPLATES.find(template => template.id === currentTemplateId) ?? BUILDER_TEMPLATES[0]
        const response = builderResponse({
          resume: {
            ...builderResponse().resume,
            selected_template_id: currentTemplateId,
            structured_version: 2,
            structured_content: {
              ...SEEDED_STRUCTURED,
              basics: { ...SEEDED_STRUCTURED.basics, name: currentName },
            },
          },
          template_family: selectedTemplate.template_family,
          preview: {
            ...builderResponse().preview,
            template_family: selectedTemplate.template_family,
          },
        })
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(response),
        })
      }
      return route.fallback()
    })

    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    await expect(page.getByRole('heading', { name: 'Builder Resume' })).toBeVisible()
    await expect(page.getByText('Resume Health')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Certifications' })).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible()

    await page.getByLabel('Full Name').fill('Taylor Builder Updated')
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await expect(page.getByText('Taylor Builder Updated')).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible({ timeout: 8000 })

    await page.getByRole('button', { name: 'Add certification' }).click()
    const certificationCard = page
      .getByRole('button', { name: 'Remove certification' })
      .locator('xpath=ancestor::div[contains(@class, "rounded-2xl")][1]')
    await certificationCard.locator('input').nth(0).fill('AWS Certified Developer')
    await expect(page.getByText('AWS Certified Developer')).toBeVisible()

    await page.locator('select').selectOption(BUILDER_TEMPLATES[1].id)
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible({ timeout: 8000 })
    await expect(page.getByLabel('Template')).toHaveValue(BUILDER_TEMPLATES[1].id)
    await expect(page.getByText('Family: executive · Executive')).toBeVisible()
  })

  test('detached builder state exposes explicit reattach action', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder', async route => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(builderResponse({
            resume: {
              ...builderResponse().resume,
              builder_status: 'detached',
            },
          })),
        })
      }
      if (route.request().method() === 'PATCH') {
        const body = await route.request().postDataJSON()
        expect(body.force_reattach).toBe(true)
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(builderResponse()),
        })
      }
      return route.fallback()
    })

    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    await expect(page.getByText('Builder detached')).toBeVisible()
    await page.getByRole('button', { name: /Reattach Builder/ }).click()
    await expect(page.getByText('Builder detached')).not.toBeVisible()
  })
})
