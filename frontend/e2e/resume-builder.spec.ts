import { expect, test, type Page } from '@playwright/test'

import type {
  BuilderResumeResponse,
  BuilderSeedUploadResponse,
  BuilderTemplateResponse,
  StructuredResume,
} from '../src/lib/api-client'

test.beforeEach(async ({ page }) => {
  await page.route('**/resumes/builder/capabilities', route => route.fulfill({ json: { guided_builder_version: 1 } }))
})


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
      bullet_ids: ['exp-1-bullet-1', 'exp-1-bullet-2'],
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
    ats_profile: overrides?.ats_profile ?? {
      identity: { given_name: 'Taylor', family_name: 'Builder' },
      contact: {
        email: 'taylor@example.com',
        phone: '+1-555-0102',
        city: 'Remote',
        region: '',
        country: '',
      },
      links: {
        linkedin: 'linkedin.com/in/taylor',
        personal_site: 'https://example.com',
      },
      work: [],
      education: [],
      skills: ['Python', 'Go', 'Distributed Systems'],
    },
  }
}

function onePagePdf() {
  const content = 'BT /F1 12 Tf 60 750 Td (Guided resume preview) Tj ET'
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>',
    `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}\nendstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  let pdf = '%PDF-1.4\n'
  const offsets = [0]
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf))
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xref = Buffer.byteLength(pdf)
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  pdf += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(pdf)
}

async function mockBuilderPdf(page: Page, expectedSource: () => string) {
  const jobId = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
  const requests = { compiled: 0, downloaded: 0 }
  await page.route('**/jobs/submit', async route => {
    const body = route.request().postDataJSON()
    expect(body.job_type).toBe('latex_compilation')
    expect(body.metadata.resume_id).toBe('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    expect(body.latex_content).toBe(expectedSource())
    requests.compiled += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: jobId }) })
  })
  await page.route(`**/jobs/${jobId}/state`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: jobId, status: 'completed' }),
  }))
  await page.route(`**/jobs/${jobId}/result`, route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: jobId, result: { pdf_job_id: jobId, latex_content: expectedSource() } }),
  }))
  await page.route(`**/download/${jobId}`, async route => {
    requests.downloaded += 1
    await route.fulfill({ status: 200, contentType: 'application/pdf', body: onePagePdf() })
  })
  return requests
}

async function mockSession(page: Page) {
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
      format: 'json_resume_v1',
      structured_content: SEEDED_STRUCTURED,
      metrics: {
        completeness_score: 82,
        page_estimate: 1,
        warnings: [],
        missing_sections: [],
      },
      interchange_warnings: ['1 non-LinkedIn/GitHub profile is not editable in the guided builder.'],
    }

    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(builderResponse()),
      }),
    )
    await page.route('**/resumes/builder/v1/seed-upload', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(seededResponse) }),
    )
    await page.route('**/resumes/builder/v1', async route => {
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
    await expect(page.getByRole('heading', { name: 'Create your résumé' })).toBeVisible()
    await expect(page.getByText('1. Start')).toBeVisible()
    await expect(page.getByRole('button', { name: /ATS-Safe ATS Guided/i })).toBeVisible()

    await page.locator('input[placeholder*="Senior Backend Engineer"]').fill('Taylor Core Resume')
    await page.locator('input[type="file"]').setInputFiles({
      name: 'resume.json',
      mimeType: 'application/json',
      buffer: Buffer.from('{"resume":"seed"}'),
    })

    await expect(page.getByText('Taylor Builder')).toBeVisible()
    await expect(page.getByText(/non-LinkedIn\/GitHub profile/)).toBeVisible()
    await page.getByRole('button', { name: 'Start my résumé' }).click()
    await expect(page).toHaveURL(/\/workspace\/builder\/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa$/)
  })

  test('builder editor autosaves structured changes and supports template swaps', async ({ page }) => {
    let currentTemplateId = BUILDER_TEMPLATES[0].id
    let currentName = SEEDED_STRUCTURED.basics.name

    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', async route => {
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
    await expect(page.getByText('Résumé completeness')).toBeVisible()
    await expect(page.getByRole('complementary').getByRole('button', { name: /^Certifications\b/ })).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible()

    await page.getByLabel('Full Name').fill('Taylor Builder Updated')
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await expect(page.getByText('Taylor Builder Updated')).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible({ timeout: 8000 })

    await page.getByRole('button', { name: 'Add certification' }).click()
    await page.getByLabel('Name', { exact: true }).fill('AWS Certified Developer')
    await expect(page.getByText('AWS Certified Developer')).toBeVisible()

    await page.getByLabel('Template').selectOption(BUILDER_TEMPLATES[1].id)
    await expect(page.getByText('Unsaved changes')).toBeVisible()
    await expect(page.getByText('All changes saved')).toBeVisible({ timeout: 8000 })
    await expect(page.getByLabel('Template')).toHaveValue(BUILDER_TEMPLATES[1].id)
    await expect(page.getByText('Executive', { exact: true })).toBeVisible()
  })

  test('builder fields keep line breaks and commas during ordinary typing', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse()) }),
    )
    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    const bullets = page.getByLabel('Impact Bullets', { exact: true }).first()
    await bullets.fill('Helped customers')
    await bullets.press('End')
    await bullets.press('Enter')
    await expect(bullets).toHaveValue('Helped customers\n')
    await bullets.pressSequentially('Improved service')
    await expect(bullets).toHaveValue('Helped customers\nImproved service')
    const skills = page.getByLabel('Keywords', { exact: true }).first()
    await skills.fill('Customer service')
    await skills.press('End')
    await skills.pressSequentially(', Teamwork')
    await expect(skills).toHaveValue('Customer service, Teamwork')
    await expect(page.getByRole('button', { name: 'Move Experience up', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Hide Experience', exact: true })).toBeVisible()
  })

  test('builder editor downloads its structured JSON Resume interchange document', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(builderResponse()) }),
    )
    await page.route('**/export/builder/v1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/json', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        headers: { 'content-disposition': 'attachment; filename="resume.json"' },
        body: JSON.stringify({
          $schema: 'https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json',
          basics: { name: 'Taylor Builder' },
          meta: { version: 'v1.0.0' },
        }),
      }),
    )

    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    await page.getByRole('button', { name: /Export/ }).click()
    const downloadPromise = page.waitForEvent('download')
    await page.getByRole('button', { name: /^JSON JSON Resume format/ }).click()
    const download = await downloadPromise

    expect(download.suggestedFilename()).toBe('resume.json')
    await expect(page.getByText('Downloaded as JSON')).toBeVisible()
  })

  test('saved resume SVG export has correct download and persistent retry', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    let current = builderResponse()
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', async route => {
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON()
        expect(body.expected_structured_version).toBe(current.resume.structured_version)
        current = { ...current, resume: { ...current.resume, structured_version: current.resume.structured_version! + 1, structured_content: body.structured_content,
          latex_content: `\\documentclass{article}\\begin{document}${body.structured_content.basics.name}\\end{document}` } }
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
    })
    const pdfRequests = await mockBuilderPdf(page, () => current.resume.latex_content)
    let attempts = 0
    await page.route('**/export/builder/v1/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/svg', async route => {
      expect(current.resume.latex_content).toContain('Taylor Latest SVG')
      expect(pdfRequests.downloaded).toBe(1)
      attempts += 1
      if (attempts === 1) return route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'renderer unavailable' }) })
      return route.fulfill({ status: 200, contentType: 'image/svg+xml', headers: { 'content-disposition': 'attachment; filename="resume.svg"' }, body: '<svg xmlns="http://www.w3.org/2000/svg"><text>Resume</text></svg>' })
    })

    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    await page.getByLabel('Full Name').fill('Taylor Latest SVG')
    await page.getByRole('button', { name: /Export/ }).click()
    await page.getByRole('button', { name: /^SVG / }).click()
    const exportError = page.getByRole('alert').filter({ hasText: 'renderer unavailable' })
    await expect(exportError).toBeVisible()
    await expect(page.getByTestId('builder-pdf-preview').locator('.react-pdf__Page__canvas')).toBeVisible()
    await expect(page.getByTestId('builder-pdf-preview').locator('.react-pdf__Page__textContent')).toContainText('Guided resume preview')
    const downloadPromise = page.waitForEvent('download')
    await exportError.getByRole('button', { name: 'Retry' }).click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe('resume.svg')
    expect(attempts).toBe(2)
    expect(pdfRequests).toEqual({ compiled: 1, downloaded: 1 })
  })

  test('compiled PDF email reports provider failure and keeps a retry action', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    let current = builderResponse()
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', async route => {
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON()
        expect(body.expected_structured_version).toBe(current.resume.structured_version)
        current = { ...current, resume: { ...current.resume, structured_version: current.resume.structured_version! + 1, structured_content: body.structured_content,
          latex_content: `\\documentclass{article}\\begin{document}${body.structured_content.basics.name}\\end{document}` } }
      }
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(current) })
    })
    const pdfRequests = await mockBuilderPdf(page, () => current.resume.latex_content)
    let attempts = 0
    await page.route('**/export/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/email', async route => {
      expect(current.resume.latex_content).toContain('Taylor Latest Email')
      expect(pdfRequests.downloaded).toBe(1)
      expect(route.request().method()).toBe('POST')
      expect(route.request().postDataJSON()).toEqual({})
      attempts += 1
      if (attempts === 1) {
        return route.fulfill({
          status: 503,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Email provider did not accept the document; please retry' }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'accepted',
          recipient: 'verified_account_email',
          retry_behavior: 'provider_idempotent',
        }),
      })
    })

    await page.goto('/workspace/builder/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
    await page.getByLabel('Full Name').fill('Taylor Latest Email')
    await page.getByRole('button', { name: /Export/ }).click()
    await page.getByRole('button', { name: /^Email me / }).click()
    const exportError = page.getByRole('alert').filter({ hasText: 'Email provider did not accept the PDF' })
    await expect(exportError).toBeVisible()
    await expect(page.getByTestId('builder-pdf-preview').locator('.react-pdf__Page__canvas')).toBeVisible()
    await exportError.getByRole('button', { name: 'Retry' }).click()
    await expect(page.getByText('PDF email accepted for your verified account email.')).toBeVisible()
    expect(attempts).toBe(2)
    expect(pdfRequests).toEqual({ compiled: 1, downloaded: 1 })
  })

  test('detached builder state exposes explicit reattach action', async ({ page }) => {
    await page.route('**/resumes/builder/templates', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(BUILDER_TEMPLATES) }),
    )
    await page.route('**/resumes/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/builder/v1', async route => {
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
    page.once('dialog', dialog => dialog.accept())
    await page.getByRole('button', { name: /Reattach Builder/ }).click()
    await expect(page.getByText('Builder detached')).not.toBeVisible()
  })
})
