import { test, expect } from '@playwright/test'
import { readFile, writeFile } from 'node:fs/promises'

// Opt-in causal probe only: keep the normal Chromium user agent unchanged in
// the regression suite, while allowing the identical bundle to be exercised
// with Next's blocking-metadata bot response. Page errors remain assertions.
if (process.env.HYDRATION_DIAGNOSTIC_USER_AGENT) {
  test.use({ userAgent: process.env.HYDRATION_DIAGNOSTIC_USER_AGENT })
}

// ------------------------------------------------------------------ //
//  Mock data                                                          //
// ------------------------------------------------------------------ //

const MOCK_RESUME = {
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  user_id: 'user-1',
  title: 'Test Resume',
  latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
  created_at: '2025-01-01T00:00:00Z',
  updated_at: '2025-01-01T00:00:00Z',
}

const MOCK_COVER_LETTERS = [
  {
    id: 'cl-111111-1111-1111-1111-111111111111',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Python developer needed',
    company_name: 'Acme Corp',
    role_title: 'Senior Engineer',
    tone: 'formal',
    length_preference: '3_paragraphs',
    latex_content: '\\documentclass{article}\\begin{document}Dear Hiring Manager\\end{document}',
    pdf_path: null,
    generation_job_id: 'job-1',
    created_at: '2025-06-15T10:00:00Z',
    updated_at: '2025-06-15T10:00:00Z',
    resume_title: 'Test Resume',
  },
  {
    id: 'cl-222222-2222-2222-2222-222222222222',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Frontend role at startup',
    company_name: 'StartupCo',
    role_title: 'Frontend Developer',
    tone: 'conversational',
    length_preference: '4_paragraphs',
    latex_content: '\\documentclass{article}\\begin{document}Hi there\\end{document}',
    pdf_path: null,
    generation_job_id: 'job-2',
    created_at: '2025-06-14T09:00:00Z',
    updated_at: '2025-06-14T09:00:00Z',
    resume_title: 'Test Resume',
  },
  {
    id: 'cl-333333-3333-3333-3333-333333333333',
    user_id: 'user-1',
    resume_id: MOCK_RESUME.id,
    job_description: 'Data science role',
    company_name: 'DataInc',
    role_title: 'Data Scientist',
    tone: 'enthusiastic',
    length_preference: 'detailed',
    latex_content: null,
    pdf_path: null,
    generation_job_id: 'job-3',
    created_at: '2025-06-13T08:00:00Z',
    updated_at: '2025-06-13T08:00:00Z',
    resume_title: 'Test Resume',
  },
]

const MOCK_PAGINATED_RESPONSE = {
  cover_letters: MOCK_COVER_LETTERS,
  total: 3,
  page: 1,
  limit: 20,
  pages: 1,
}

const MOCK_STATS = { total: 3 }

const MOCK_SESSION = {
  session: { token: 'mock-token' },
  user: { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

// Helper: mock the auth session API so pages think the user is logged in
async function mockAuth(page: import('@playwright/test').Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SESSION),
    })
  )
}

// ------------------------------------------------------------------ //
//  Cover Letters listing page — /workspace/cover-letters              //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing Page (/workspace/cover-letters)', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Mock cover-letters API
    await page.route((url) => {
      const path = url.pathname
      return path.startsWith('/cover-letters')
    }, async (route) => {
      const url = new URL(route.request().url())
      const path = url.pathname

      if (path === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_STATS),
        })
      }

      if ((path === '/cover-letters/' || path === '/cover-letters') && route.request().method() === 'GET') {
        const search = url.searchParams.get('search') || ''
        let filtered = [...MOCK_COVER_LETTERS]
        if (search) {
          const q = search.toLowerCase()
          filtered = filtered.filter(
            (cl) =>
              (cl.company_name || '').toLowerCase().includes(q) ||
              (cl.role_title || '').toLowerCase().includes(q)
          )
        }
        const page_ = parseInt(url.searchParams.get('page') || '1')
        const limit = parseInt(url.searchParams.get('limit') || '20')
        const total = filtered.length
        const pages = Math.max(1, Math.ceil(total / limit))
        const start = (page_ - 1) * limit
        const sliced = filtered.slice(start, start + limit)
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            cover_letters: sliced,
            total,
            page: page_,
            limit,
            pages,
          }),
        })
      }

      if (route.request().method() === 'DELETE') {
        return route.fulfill({ status: 204 })
      }

      return route.continue()
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  // ---- Basic rendering ----

  test('page loads with heading', async ({ page }) => {
    await expect(page.locator('h1')).toContainText('Cover Letter Library')
  })

  test('shows total count', async ({ page }) => {
    await expect(page.getByText('3 total')).toBeVisible()
  })

  test('renders cover letter cards in grid view', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'StartupCo' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'DataInc' })).toBeVisible()
  })

  test('cards show role title', async ({ page }) => {
    await expect(page.getByText('Senior Engineer')).toBeVisible()
    await expect(page.getByText('Frontend Developer')).toBeVisible()
  })

  test('cards show resume link', async ({ page }) => {
    const resumeLinks = page.locator(`a[href="/workspace/${MOCK_RESUME.id}/edit"]`)
    await expect(resumeLinks.first()).toBeVisible()
  })

  test('cards show tone badge', async ({ page }) => {
    await expect(page.getByText('formal').first()).toBeVisible()
    await expect(page.getByText('conversational')).toBeVisible()
    await expect(page.getByText('enthusiastic')).toBeVisible()
  })

  test('cards show date', async ({ page }) => {
    // At least one date should be rendered
    await expect(page.locator('article').first().getByText(/\d{1,2}\/\d{1,2}\/\d{4}/)).toBeVisible()
  })

  test('cards have View and Delete buttons', async ({ page }) => {
    const firstCard = page.locator('article').first()
    await expect(firstCard.getByText('View')).toBeVisible()
    await expect(firstCard.getByText('Delete')).toBeVisible()
  })

  test('View links to resume cover letter page', async ({ page }) => {
    const viewLink = page.locator('article').first().getByText('View')
    await expect(viewLink).toHaveAttribute(
      'href',
      `/workspace/${MOCK_RESUME.id}/cover-letter?cl=${MOCK_COVER_LETTERS[0].id}`
    )
  })

  // ---- Search ----

  test('search filters by company name', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('Acme')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'StartupCo' })).not.toBeVisible()
  })

  test('search filters by role title', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('Frontend')
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('heading', { name: 'StartupCo' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Acme Corp' })).not.toBeVisible()
  })

  test('search with no results shows empty state', async ({ page }) => {
    const searchInput = page.locator('input[placeholder*="Search by company"]')
    await searchInput.fill('nonexistent_xyz')
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('No cover letters yet')).toBeVisible()
  })

  // ---- View mode toggle ----

  test('grid mode is active by default', async ({ page }) => {
    // Grid layout has article cards
    await expect(page.locator('article').first()).toBeVisible()
  })

  test('switching to list mode shows table', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('table')).toBeVisible()
    await expect(page.locator('th', { hasText: 'Company / Role' })).toBeVisible()
    await expect(page.locator('th', { hasText: 'Resume' })).toBeVisible()
    await expect(page.locator('th', { hasText: 'Tone' })).toBeVisible()
  })

  test('list view shows all cover letters', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('tbody tr')).toHaveCount(3)
  })

  test('list view has View and Delete actions', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    const firstRow = page.locator('tbody tr').first()
    await expect(firstRow.getByText('View')).toBeVisible()
    await expect(firstRow.getByText('Delete')).toBeVisible()
  })

  test('switching back to grid from list', async ({ page }) => {
    await page.getByRole('button', { name: 'List' }).click()
    await expect(page.locator('table')).toBeVisible()
    await page.getByRole('button', { name: 'Grid' }).click()
    await expect(page.locator('article').first()).toBeVisible()
  })

  // ---- Delete ----

  test('delete removes card from grid', async ({ page }) => {
    await expect(page.locator('article')).toHaveCount(3)
    const firstCard = page.locator('article').first()
    await firstCard.getByText('Delete').click()
    await firstCard.getByRole('button', { name: /Confirm delete cover letter/ }).click()
    await expect(page.locator('article')).toHaveCount(2)
  })

  // ---- Navigation ----

  test('has Workspace link', async ({ page }) => {
    const link = page.getByRole('navigation').getByRole('link', { name: 'Workspace' })
    await expect(link).toHaveAttribute('href', '/workspace')
  })
})

// ------------------------------------------------------------------ //
//  Empty state                                                        //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing — empty state', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    await page.route((url) => url.pathname.startsWith('/cover-letters'), async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 0 }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: [],
          total: 0,
          page: 1,
          limit: 20,
          pages: 1,
        }),
      })
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  test('shows empty state message', async ({ page }) => {
    await expect(page.getByText('No cover letters yet')).toBeVisible()
  })

  test('shows CTA to workspace', async ({ page }) => {
    await expect(page.getByText('Go to Workspace')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Pagination                                                         //
// ------------------------------------------------------------------ //

test.describe('Cover Letters Listing — pagination', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Generate 5 mock CLs, serve with limit=2 to force multiple pages
    const allCLs = Array.from({ length: 5 }, (_, i) => ({
      id: `cl-page-${i}`,
      user_id: 'user-1',
      resume_id: MOCK_RESUME.id,
      job_description: `JD ${i}`,
      company_name: `Company ${i}`,
      role_title: `Role ${i}`,
      tone: 'formal',
      length_preference: '3_paragraphs',
      latex_content: null,
      pdf_path: null,
      generation_job_id: null,
      created_at: new Date(2025, 5, 15 - i).toISOString(),
      updated_at: new Date(2025, 5, 15 - i).toISOString(),
      resume_title: 'Test Resume',
    }))

    await page.route((url) => url.pathname.startsWith('/cover-letters'), async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === '/cover-letters/stats') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 5 }),
        })
      }
      // The page always requests with limit=20, but we override to simulate pagination
      // by returning subsets
      const pg = parseInt(url.searchParams.get('page') || '1')
      const lim = 2 // Force small page size for testing
      const start = (pg - 1) * lim
      const sliced = allCLs.slice(start, start + lim)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: sliced,
          total: 5,
          page: pg,
          limit: lim,
          pages: 3,
        }),
      })
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
  })

  test('shows pagination controls', async ({ page }) => {
    await expect(page.getByText('Page 1 of 3')).toBeVisible()
    await expect(page.getByRole('button', { name: 'Previous' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Next', exact: true })).toBeVisible()
  })

  test('Previous is disabled on first page', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  test('clicking Next navigates to page 2', async ({ page }) => {
    await page.getByRole('button', { name: 'Next', exact: true }).click()
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Page 2 of 3')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  GlobalHeader — Cover Letters NOT in main nav (accessible via       //
//  workspace cards instead)                                           //
// ------------------------------------------------------------------ //

test.describe('GlobalHeader — Cover Letters not in nav', () => {
  test('Cover Letters link not in main nav for authenticated users', async ({ page }) => {
    await mockAuth(page)
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
    const navLink = page.locator('nav a', { hasText: 'Cover Letters' })
    await expect(navLink).not.toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Dashboard — cover letter KPI card                                  //
// ------------------------------------------------------------------ //

test.describe('Dashboard — Cover Letter stat', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)

    // Mock all dashboard APIs
    await page.route((url) => url.pathname.startsWith('/analytics'), (route) => {
      const url = new URL(route.request().url())
      if (url.pathname.includes('/timeseries')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            user_id: 'user-1',
            period_days: 30,
            activity_series: [],
            compilation_series: [],
            optimization_series: [],
            feature_series: [],
            status_distribution: {},
          }),
        })
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user_id: 'user-1',
          period_days: 30,
          total_compilations: 10,
          successful_compilations: 8,
          success_rate: 80,
          total_optimizations: 5,
          avg_compilation_time: 2.5,
          feature_usage: {},
          daily_activity: { '2025-01-01': 5 },
          most_active_day: '2025-01-01',
        }),
      })
    })

    await page.route((url) => url.pathname === '/resumes/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          total_resumes: 3,
          total_templates: 1,
          last_updated: '2025-01-01T00:00:00Z',
        }),
      })
    )

    await page.route((url) => url.pathname === '/cover-letters/stats', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 7 }),
      })
    )

    await page.route((url) => url.pathname === '/jobs' || url.pathname === '/jobs/', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ jobs: [] }),
      })
    )

    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')
  })

  test('shows Cover Letters KPI card', async ({ page }) => {
    await expect(page.getByText('Cover Letters', { exact: true })).toBeVisible()
  })

  test('shows correct cover letter count', async ({ page }) => {
    // The KPI value "7" should appear on the page
    const kpiSection = page.locator('article', { hasText: 'Cover Letters' })
    await expect(kpiSection.locator('text=7')).toBeVisible()
  })

  test('shows cover letter description', async ({ page }) => {
    await expect(page.getByText('Generated cover letters')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Cover Letter Generation Page — /workspace/[resumeId]/cover-letter  //
// ------------------------------------------------------------------ //

test.describe('Cover Letter Generation Page', () => {
  const resumeId = MOCK_RESUME.id
  let mockedCoverLetters = MOCK_COVER_LETTERS.slice(0, 2)
  let mockedJobStates: Record<string, Record<string, unknown>> = {}

  test.beforeEach(async ({ page }) => {
    mockedCoverLetters = MOCK_COVER_LETTERS.slice(0, 2)
    mockedJobStates = {}
    await mockAuth(page)

    // Mock resume fetch
    await page.route((url) => url.pathname === `/resumes/${resumeId}`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_RESUME),
      })
    )

    // Mock existing cover letters for this resume
    await page.route(
      (url) => url.pathname === `/cover-letters/resume/${resumeId}`,
      (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockedCoverLetters),
      })
    )

    // Mock compile endpoint
    await page.route((url) => url.pathname === '/jobs/submit', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'compile-job-1',
          message: 'Compilation started',
        }),
      })
    )

    // Mock job state (for WebSocket fallback)
    await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) => {
      const jobId = new URL(route.request().url()).pathname.split('/')[2]
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockedJobStates[jobId] ?? {
          status: 'queued',
          stage: '',
          percent: 0,
          last_updated: Date.now() / 1000,
        }),
      })
    })

    // Mock analytics (fire-and-forget)
    await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
    )
  })

  // Note: this page has fullscreenPatterns match so GlobalHeader is hidden.
  // The page is an editor-style fullscreen layout.

  test('page loads without errors', async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    if (process.env.HYDRATION_ROUTER_DIAGNOSTICS === '1') {
      // Opt-in causal probe for the initial RSC/router hand-off. Record only
      // bounded structural metadata: never retain Flight payload text, URL
      // query values, cookies, headers, or rendered user content.
      await page.addInitScript(() => {
        type FlightEvent = {
          atMs: number
          kind: unknown
          payloadType: string
          payloadLength: number | null
          loadingMarkerCount: number | null
          boundaryMarkerCount: number | null
        }
        type RouterDiagnosticState = {
          flight: FlightEvent[]
          router: Array<{
            atMs: number
            initialFlightDataCount: number | null
            seedDataPresent: boolean
            seedDataLength: number | null
            seedRscPresent: boolean
            seedRscType: string | null
            seedLoadingPresent: boolean
            seedLoadingType: string | null
            cacheLoadingPresent: boolean
          }>
          snapshots: Array<{
            atMs: number
            label: string
            hiddenBoundaryCount: number
            boundaryCommentCount: number
            mainCount: number
            mainFirstNode: string | null
            mainFirstNodeType: number | null
          }>
          flightPushCount: number
          nextFInstalled: boolean
        }
        const state = window as Window & { __hydrationRouterDiagnostics?: RouterDiagnosticState }
        const diagnostic: RouterDiagnosticState = {
          flight: [], router: [], snapshots: [], flightPushCount: 0, nextFInstalled: false,
        }
        state.__hydrationRouterDiagnostics = diagnostic

        const inspectFlightEntry = (entry: unknown) => {
          diagnostic.flightPushCount += 1
          if (!Array.isArray(entry) || diagnostic.flight.length >= 128) return
          const payload = entry[1]
          const text = typeof payload === 'string' ? payload : null
          const count = (needle: string) => text === null ? null : (text.match(new RegExp(needle, 'g')) ?? []).length
          diagnostic.flight.push({
            atMs: Math.round(performance.now() * 100) / 100,
            kind: entry[0],
            payloadType: typeof payload,
            payloadLength: text === null ? null : Math.min(text.length, 1_000_000),
            loadingMarkerCount: count('loading'),
            boundaryMarkerCount: count('B:[0-9]+'),
          })
        }
        const wrapFlightPush = (candidate: unknown) => {
          if (!candidate || typeof candidate !== 'object') return
          const flight = candidate as { push?: (...entries: unknown[]) => unknown }
          if (typeof flight.push !== 'function') return
          const originalPush = flight.push.bind(candidate)
          flight.push = (...entries: unknown[]) => {
            for (const entry of entries) inspectFlightEntry(entry)
            return originalPush(...entries)
          }
          diagnostic.nextFInstalled = true
        }
        let nextFlight: unknown
        Object.defineProperty(window, '__next_f', {
          configurable: true,
          get: () => nextFlight,
          set: (value: unknown) => { nextFlight = value; wrapFlightPush(value) },
        })

        const recordSnapshot = (label: string) => {
          if (diagnostic.snapshots.length >= 16) return
          if (label === 'mutation' && diagnostic.snapshots.filter((snapshot) => snapshot.label === 'mutation').length >= 3) return
          const main = document.querySelector('main')
          const boundaryCommentCount = main
            ? Array.from(main.childNodes).filter((node) => node.nodeType === Node.COMMENT_NODE).length
            : 0
          diagnostic.snapshots.push({
            atMs: Math.round(performance.now() * 100) / 100,
            label,
            hiddenBoundaryCount: document.querySelectorAll('template[id^="B:"]').length,
            boundaryCommentCount,
            mainCount: document.querySelectorAll('main').length,
            mainFirstNode: main?.firstChild?.nodeName ?? null,
            mainFirstNodeType: main?.firstChild?.nodeType ?? null,
          })
        }
        document.addEventListener('DOMContentLoaded', () => recordSnapshot('DOMContentLoaded'), { once: true })
        let lastBoundarySignature = ''
        const observer = new MutationObserver(() => {
          const main = document.querySelector('main')
          const boundaryCommentCount = main
            ? Array.from(main.childNodes).filter((node) => node.nodeType === Node.COMMENT_NODE).length
            : 0
          const signature = `${document.querySelectorAll('template[id^="B:"]').length}:${boundaryCommentCount}`
          const label = signature === lastBoundarySignature ? 'mutation' : 'boundary'
          lastBoundarySignature = signature
          recordSnapshot(label)
        })
        observer.observe(document, { childList: true, subtree: true })
        window.setTimeout(() => observer.disconnect(), 15_000)
      })
      await page.route('**/_next/static/chunks/3949-*.js', async route => {
        const localProbeFile = process.env.HYDRATION_DIAGNOSTIC_ROUTER_FILE
        const response = localProbeFile ? undefined : await route.fetch()
        const original = localProbeFile ? await readFile(localProbeFile, 'utf8') : await response!.text()
        // This is the pinned Next client chunk's createInitialRouterState
        // implementation. The replacement captures seedData[3] and the
        // resulting cache.loading presence without serializing either value.
        const marker = ';let T=new Map'
        if (!original.includes(marker)) {
          await route.fulfill(localProbeFile
            ? { status: 200, contentType: 'application/javascript', body: original }
            : { response })
          return
        }
        const capture = ';window.__hydrationRouterDiagnostics=window.__hydrationRouterDiagnostics||{flight:[],router:[],snapshots:[],flightPushCount:0,nextFInstalled:false};window.__hydrationRouterDiagnostics.router.push({atMs:Math.round(performance.now()*100)/100,initialFlightDataCount:Array.isArray(f)?f.length:null,seedDataPresent:Array.isArray(R),seedDataLength:Array.isArray(R)?R.length:null,seedRscPresent:Array.isArray(R)&&R.length>1&&R[1]!==null&&R[1]!==void 0,seedRscType:Array.isArray(R)&&R.length>1&&R[1]!==null?typeof R[1]:null,seedLoadingPresent:Array.isArray(R)&&R.length>3&&R[3]!==null&&R[3]!==void 0,seedLoadingType:Array.isArray(R)&&R.length>3&&R[3]!==null?typeof R[3]:null,cacheLoadingPresent:P.loading!==null&&P.loading!==void 0})'
        await route.fulfill({ response, contentType: 'application/javascript', body: original.replace(marker, capture + marker) })
      })
    }
    if (process.env.HYDRATION_FIBER_DIAGNOSTICS === '1') {
      // Temporary probe for the pinned production React bundle only. Preserve
      // the original throw, but capture the rejected host element/candidate.
      // Never use this modified delivery as application acceptance evidence.
      await page.route('**/_next/static/chunks/a9f434d3-*.js', async route => {
        const localProbeFile = process.env.HYDRATION_DIAGNOSTIC_REACT_FILE
        const response = localProbeFile ? undefined : await route.fetch()
        const original = localProbeFile ? await readFile(localProbeFile, 'utf8') : await response!.text()
        const marker = 'function rD(e){'
        expect(original.split(marker)).toHaveLength(2)
        const capture = 'try{var chain=[],f=e;while(f&&chain.length<40){chain.push(typeof f.type==="string"?f.type:(f.type&&f.type.name)||f.tag);f=f.return}var d={atMs:Math.round(performance.now()*100)/100,chain:chain,expectedId:e.pendingProps&&e.pendingProps.id,candidate:rN&&rN.outerHTML,candidateText:rN&&rN.textContent,candidateType:rN&&rN.nodeType,next:rN&&rN.nextSibling&&rN.nextSibling.outerHTML,parent:rP&&rP.type,parentHTML:rP&&rP.stateNode&&rP.stateNode.outerHTML&&rP.stateNode.outerHTML.slice(0,6000),mainCount:document.querySelectorAll("main").length};window.__hydrationFiberDiagnostics=window.__hydrationFiberDiagnostics||[];window.__hydrationFiberDiagnostics.push(d)}catch(probeError){}'
        await route.fulfill({ response, contentType: 'application/javascript', body: original.replace(marker, marker + capture) })
      })
    }
    if (process.env.HYDRATION_DIAGNOSTICS === '1') {
      await page.addInitScript(() => {
        const history: Array<{ added: string[]; removed: string[] }> = []
        const state = window as Window & { __hydrationDiagnostics?: unknown[] }
        state.__hydrationDiagnostics = []
        const summarize = (nodes: NodeList) => Array.from(nodes).map(node => {
          if (node instanceof Element) {
            if (node.tagName === 'SCRIPT' || node.tagName === 'STYLE') return node.tagName
            return node.outerHTML.slice(0, 1600)
          }
          return node.textContent?.slice(0, 200) ?? ''
        })
        const observer = new MutationObserver(records => {
          for (const record of records) {
            if (record.type !== 'childList') continue
            history.push({ added: summarize(record.addedNodes), removed: summarize(record.removedNodes) })
          }
          if (history.length > 100) history.splice(0, history.length - 100)
        })
        observer.observe(document, { childList: true, subtree: true })
        window.addEventListener('error', event => {
          state.__hydrationDiagnostics?.push({
            atMs: Math.round(performance.now() * 100) / 100,
            message: event.message, stack: event.error?.stack,
            fiber: (window as Window & { __hydrationFiberDiagnostics?: unknown }).__hydrationFiberDiagnostics,
            main: document.querySelector('#main-content')?.innerHTML.slice(0, 4000),
            mutations: history.slice(),
          })
        })
        window.setTimeout(() => observer.disconnect(), 15_000)
      })
    }
    await page.goto(`/workspace/${resumeId}/cover-letter`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('textarea[placeholder*="Paste the job description"]')).toBeVisible()
    if (process.env.HYDRATION_ROUTER_DIAGNOSTICS === '1') {
      const diagnosticPath = testInfo.outputPath('hydration-router-diagnostic.json')
      const diagnostic = await page.evaluate(() => {
        const state = window as Window & { __hydrationRouterDiagnostics?: {
          snapshots?: Array<{
            atMs: number
            label: string
            hiddenBoundaryCount: number
            boundaryCommentCount: number
            mainCount: number
            mainFirstNode: string | null
            mainFirstNodeType: number | null
          }>
        } }
        const main = document.querySelector('main')
        state.__hydrationRouterDiagnostics?.snapshots?.push({
          atMs: Math.round(performance.now() * 100) / 100,
          label: 'post-visible',
          hiddenBoundaryCount: document.querySelectorAll('template[id^="B:"]').length,
          boundaryCommentCount: main
            ? Array.from(main.childNodes).filter((node) => node.nodeType === Node.COMMENT_NODE).length
            : 0,
          mainCount: document.querySelectorAll('main').length,
          mainFirstNode: main?.firstChild?.nodeName ?? null,
          mainFirstNodeType: main?.firstChild?.nodeType ?? null,
        })
        return state.__hydrationRouterDiagnostics
      })
      await writeFile(diagnosticPath, JSON.stringify(diagnostic, null, 2))
      await testInfo.attach('hydration-router-diagnostic', {
        path: diagnosticPath,
        contentType: 'application/json',
      })
    }
    if (errors.length && process.env.HYDRATION_DIAGNOSTICS === '1') {
      const diagnosticPath = testInfo.outputPath('hydration-dom-history.json')
      await writeFile(diagnosticPath, JSON.stringify(await page.evaluate(() => (window as Window & { __hydrationDiagnostics?: unknown[] }).__hydrationDiagnostics), null, 2))
      await testInfo.attach('hydration-dom-history', {
        path: diagnosticPath,
        contentType: 'application/json',
      })
    }
    expect(errors).toEqual([])
  })

  test('shows page heading', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('h1')).toContainText('AI Cover Letter Generator')
  })

  test('shows resume title in description', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText(MOCK_RESUME.title)).toBeVisible()
  })

  test('shows job description textarea', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const textarea = page.locator('textarea[placeholder*="Paste the job description"]')
    await expect(textarea).toBeVisible()
  })

  test('shows company name and role title inputs', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.locator('input[placeholder="Company name"]')).toBeVisible()
    await expect(page.locator('input[placeholder="Role title"]')).toBeVisible()
  })

  test('shows tone selection buttons', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: 'Formal' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Conversational' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Enthusiastic' })).toBeVisible()
  })

  test('shows length selection buttons', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByRole('button', { name: '3 Paragraphs' })).toBeVisible()
    await expect(page.getByRole('button', { name: '4 Paragraphs' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Detailed' })).toBeVisible()
  })

  test('generate button disabled when no job description', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('')
    const btn = page.getByRole('button', { name: /Generate Cover Letter/ })
    await expect(btn).toBeDisabled()
  })

  test('generate button enabled when job description entered', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const textarea = page.locator('textarea[placeholder*="Paste the job description"]')
    await textarea.fill('We are looking for a Python developer with 5 years of experience.')
    const btn = page.getByRole('button', { name: /Generate Cover Letter/ })
    await expect(btn).toBeEnabled()
  })

  test('shows existing cover letters in sidebar', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()
    await expect(page.getByText('Acme Corp').first()).toBeVisible()
    await expect(page.getByText('StartupCo')).toBeVisible()
  })

  test('loads most recent cover letter into editor on page load', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const activeCard = page.getByRole('button', { name: /Acme Corp/ })
    await expect(activeCard).toHaveAttribute('aria-pressed', 'true')
  })

  test('has Back to Editor link', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const link = page.getByText('Back to Editor')
    await expect(link).toBeVisible()
    await expect(link).toHaveAttribute('href', `/workspace/${resumeId}/edit`)
  })

  test('has Compile PDF button', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Compile PDF')).toBeVisible()
  })

  test('has auto-compile toggle', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Auto')).toBeVisible()
  })

  test('shows Live Logs section', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Live Logs')).toBeVisible()
  })

  test('shows Output Preview section', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Output Preview')).toBeVisible()
  })

  test('tone selection changes active state', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const conversational = page.getByRole('button', { name: 'Conversational' })
    await conversational.click()
    await expect(conversational).toHaveAttribute('aria-pressed', 'true')
  })

  test('length selection changes active state', async ({ page }) => {
    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    const detailed = page.getByRole('button', { name: 'Detailed' })
    await detailed.click()
    await expect(detailed).toHaveAttribute('aria-pressed', 'true')
  })

  test('generation request sends correct data', async ({ page }) => {
    let capturedBody: Record<string, unknown> | null = null

    await page.route((url) => url.pathname === '/cover-letters/generate', async (route) => {
      capturedBody = JSON.parse(route.request().postData() || '{}')
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'gen-job-1',
          cover_letter_id: 'new-cl-1',
          message: 'Started',
        }),
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')

    // Fill form
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a developer')
    await page.locator('input[placeholder="Company name"]').fill('TestCo')
    await page.locator('input[placeholder="Role title"]').fill('SWE')
    await page.getByRole('button', { name: 'Conversational' }).click()
    await page.getByRole('button', { name: '4 Paragraphs' }).click()

    // Submit
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()

    // Verify captured request
    await page.waitForTimeout(500)
    expect(capturedBody).not.toBeNull()
    expect(capturedBody!.resume_id).toBe(resumeId)
    expect(capturedBody!.job_description).toBe('Need a developer')
    expect(capturedBody!.company_name).toBe('TestCo')
    expect(capturedBody!.role_title).toBe('SWE')
    expect(capturedBody!.tone).toBe('conversational')
    expect(capturedBody!.length_preference).toBe('4_paragraphs')
  })

  test('generation adds new entry to sidebar', async ({ page }) => {
    await page.route((url) => url.pathname === '/cover-letters/generate', async (route) => {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: 'gen-job-2',
          cover_letter_id: 'new-cl-2',
          message: 'Started',
        }),
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')

    // Initially 2 existing CLs
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()

    // Fill JD and submit
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a dev')
    await page.locator('input[placeholder="Company name"]').fill('NewCo')
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()

    // Should now show 3
    await expect(page.getByText('Previous Cover Letters (3)')).toBeVisible()
    await expect(page.getByText('NewCo')).toBeVisible()
  })

  test('recovers missed LaTeX/deep ATS data after WS completion and compiles exactly once', async ({ page }) => {
    const generationJobId = 'generation-recovery-job'
    const compileJobId = 'recovery-compile-job'
    const recoveredLatex = '\\documentclass{article}\\begin{document}REST recovery letter\\end{document}'
    const compileBodies: string[] = []
    mockedCoverLetters = []
    mockedJobStates[generationJobId] = {
      status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000,
    }

    await page.route((url) => url.pathname === '/ws/ticket', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ticket: 'playwright-ticket', expires_in: 60 }) }))
    await page.route((url) => url.pathname === '/cover-letters/generate', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: generationJobId, cover_letter_id: 'recovery-cover-letter', message: 'Started' }),
      }))
    await page.route((url) => url.pathname === `/jobs/${generationJobId}/result`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: generationJobId,
          result: {
            success: true,
            job_id: generationJobId,
            pdf_job_id: null,
            cover_letter_latex: recoveredLatex,
            tokens_used: 44,
            deep_analysis: {
              overall_score: 91,
              overall_feedback: 'Strong match',
              sections: [{ name: 'Experience', score: 88, strengths: ['Clear ownership'], improvements: ['Add dates'] }],
              ats_compatibility: { score: 90, issues: [], keyword_gaps: [] },
              job_match: null,
              tokens_used: 44,
              analysis_time: 1.2,
              multi_dim_scores: { grammar: 92 },
              industry_key: 'tech_saas',
              industry_label: 'Technology / SaaS',
            },
          },
        }),
      }))
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      compileBodies.push(route.request().postDataJSON().latex_content)
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: compileJobId, message: 'Started' }),
      })
    })

    // Deliver the terminal WS event first, with no LLM output. The later REST
    // replay must hydrate the editor and trigger the sole generated-letter compile.
    await page.routeWebSocket(/\/ws\/jobs/, (ws) => {
      ws.onMessage((message) => {
        const frame = JSON.parse(String(message)) as { type?: string; job_id?: string }
        if (frame.type !== 'subscribe' || frame.job_id !== generationJobId) return
        ws.send(JSON.stringify({
          type: 'event',
          stream_id: '1-0',
          event: {
            event_id: 'ws-completed-recovery',
            job_id: generationJobId,
            timestamp: Date.now() / 1000,
            sequence: 1,
            type: 'job.completed',
            pdf_job_id: null,
            ats_score: null,
            ats_details: null,
            changes_made: [],
            compilation_time: 0,
            optimization_time: 0,
            tokens_used: 44,
          },
        }))
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a senior engineer')
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()

    await expect.poll(() => compileBodies.length, { timeout: 25_000 }).toBe(1)
    expect(compileBodies[0]).toBe(recoveredLatex)
    await expect.poll(async () => page.evaluate(() => {
      const editor = (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor
      return editor?.getValue() ?? ''
    }), { timeout: 10_000 }).toContain('REST recovery letter')
  })

  test('drops a late generation compile when the mounted cover-letter identity changes', async ({ page }) => {
    const generationJobId = 'switch-generation-job'
    const recoveredLatex = '\\documentclass{article}\\begin{document}Old owner letter\\end{document}'
    let releaseCompile!: () => void
    let compileBodies: string[] = []
    let lateCompileStateReads = 0
    let lateCompileSubscriptions = 0
    let lateCompileArtifactReads = 0
    const compileGate = new Promise<void>((resolve) => { releaseCompile = resolve })
    mockedCoverLetters = []
    mockedJobStates[generationJobId] = {
      status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000,
    }

    await page.route((url) => url.pathname === '/ws/ticket', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ticket: 'switch-ticket', expires_in: 60 }) }))
    await page.route((url) => url.pathname === '/cover-letters/generate', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: generationJobId, cover_letter_id: 'switch-cover-letter', message: 'Started' }),
      }))
    await page.route((url) => url.pathname === `/jobs/${generationJobId}/result`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: true,
          job_id: generationJobId,
          result: { success: true, job_id: generationJobId, pdf_job_id: null, cover_letter_latex: recoveredLatex },
        }),
      }))
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      compileBodies.push(route.request().postDataJSON().latex_content)
      await compileGate
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ success: true, job_id: 'late-old-compile', message: 'Started' }),
      })
    })
    await page.route((url) => url.pathname === '/jobs/late-old-compile/state', (route) => {
      lateCompileStateReads += 1
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
      })
    })
    await page.route((url) => url.pathname === '/jobs/late-old-compile/result' || url.pathname === '/download/late-old-compile', (route) => {
      lateCompileArtifactReads += 1
      return route.fulfill({ status: 404, body: '' })
    })
    await page.routeWebSocket(/\/ws\/jobs/, (ws) => {
      ws.onMessage((message) => {
        const frame = JSON.parse(String(message)) as { type?: string; job_id?: string }
        if (frame.type === 'subscribe' && frame.job_id === 'late-old-compile') lateCompileSubscriptions += 1
        if (frame.type !== 'subscribe' || frame.job_id !== generationJobId) return
        ws.send(JSON.stringify({
          type: 'event', stream_id: '1-0', event: {
            event_id: 'switch-completed', job_id: generationJobId, timestamp: Date.now() / 1000,
            sequence: 1, type: 'job.completed', pdf_job_id: null, ats_score: null,
            ats_details: null, changes_made: [], compilation_time: 0, optimization_time: 0, tokens_used: 1,
          },
        }))
      })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`, { waitUntil: 'domcontentloaded' })
    await expect(page.locator('textarea[placeholder*="Paste the job description"]')).toBeVisible()
    await page.locator('textarea[placeholder*="Paste the job description"]').fill('Need a senior engineer')
    await page.getByRole('button', { name: /Generate Cover Letter/ }).click()
    await expect.poll(() => compileBodies.length, { timeout: 25_000 }).toBe(1)

    // Switch the mounted page to a different cover-letter identity while the
    // old generation's compile response is still deferred. The new letter has
    // no generated content, so it cannot enqueue its own compile.
    mockedCoverLetters = [{ ...MOCK_COVER_LETTERS[1], latex_content: null }]
    const documentMarker = `same-document-${Date.now()}`
    await page.evaluate(({ url, marker }) => {
      ;(window as Window & { __coverRecoveryDocumentMarker?: string }).__coverRecoveryDocumentMarker = marker
      // Next's patched history API updates useSearchParams without destroying
      // the mounted component or the old request's JavaScript realm.
      window.history.pushState(null, '', url)
    }, { url: `/workspace/${resumeId}/cover-letter?cl=${MOCK_COVER_LETTERS[1].id}`, marker: documentMarker })
    await expect(page.locator('input[placeholder="Company name"]')).toHaveValue('StartupCo')
    expect(await page.evaluate(() => (window as Window & { __coverRecoveryDocumentMarker?: string }).__coverRecoveryDocumentMarker)).toBe(documentMarker)
    const lateResponse = page.waitForResponse((response) => response.url().endsWith('/jobs/submit'))
    releaseCompile()
    await (await lateResponse).finished()
    // Drain response handling and the hook's polling window; a stale accepted
    // job may subscribe immediately or only show up on its REST fallback.
    await page.waitForTimeout(3_000)
    expect(compileBodies).toHaveLength(1)
    expect(lateCompileStateReads).toBe(0)
    expect(lateCompileSubscriptions).toBe(0)
    expect(lateCompileArtifactReads).toBe(0)
    await expect(page.locator('input[placeholder="Company name"]')).toHaveValue('StartupCo')
    await expect.poll(async () => page.evaluate(() => {
      const editor = (window as typeof window & { __latexyMonacoEditor?: { getValue(): string } }).__latexyMonacoEditor
      return editor?.getValue() ?? ''
    })).not.toContain('Old owner letter')
  })

  test('typed signature is escaped, persisted, and compiled', async ({ page }) => {
    let savedLatex = ''
    let compiledLatex = ''
    const letter = MOCK_COVER_LETTERS[0]
    await page.route((url) => url.pathname === `/cover-letters/${letter.id}`, async (route) => {
      savedLatex = route.request().postDataJSON().latex_content
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...letter, latex_content: savedLatex }),
      })
    })
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      compiledLatex = route.request().postDataJSON().latex_content
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'signature-compile', message: 'Started' }) })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.getByLabel('Printed name').fill('Ada & Co.')
    await page.getByRole('button', { name: 'Add signature' }).click()

    await expect.poll(() => savedLatex).toContain('LATEXY_SIGNATURE_START')
    expect(savedLatex).toContain('Ada \\& Co.')
    await expect.poll(() => compiledLatex).toBe(savedLatex)
  })

  test('does not toast signature success after a deferred save fails on a letter switch', async ({ page }) => {
    const first = MOCK_COVER_LETTERS[0]
    mockedJobStates['compile-job-1'] = { status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000 }
    await page.route((url) => url.pathname === '/jobs/compile-job-1/result', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'compile-job-1', result: { success: true, job_id: 'compile-job-1', pdf_job_id: null } }),
    }))
    let releaseSave!: () => void
    let saveRequests = 0
    const saveGate = new Promise<void>((resolve) => { releaseSave = resolve })
    await page.route((url) => url.pathname === `/cover-letters/${first.id}`, async (route) => {
      saveRequests += 1
      await saveGate
      return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'save rejected' }) })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByLabel('Printed name')).toBeVisible()
    await page.getByLabel('Printed name').fill('Late Owner')
    await page.getByRole('button', { name: 'Add signature' }).click()
    await expect.poll(() => saveRequests).toBe(1)

    mockedCoverLetters = [{ ...MOCK_COVER_LETTERS[1], latex_content: null }]
    await page.evaluate((coverLetterId) => {
      window.history.pushState(null, '', `${location.pathname}?cl=${coverLetterId}`)
    }, MOCK_COVER_LETTERS[1].id)
    await expect(page.locator('input[placeholder="Company name"]')).toHaveValue('StartupCo')
    releaseSave()
    await page.waitForTimeout(1_000)
    await expect(page.getByText('Signature saved and added to the cover letter')).toHaveCount(0)
  })

  test('does not toast signature success after persistence when a late compile crosses a letter switch', async ({ page }) => {
    const first = MOCK_COVER_LETTERS[0]
    let releaseCompile!: () => void
    let signatureCompileRequests = 0
    let staleStateReads = 0
    const compileGate = new Promise<void>((resolve) => { releaseCompile = resolve })
    mockedJobStates['compile-job-1'] = { status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000 }
    await page.route((url) => url.pathname === '/jobs/compile-job-1/result', (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'compile-job-1', result: { success: true, job_id: 'compile-job-1', pdf_job_id: null } }),
    }))
    await page.route((url) => url.pathname === `/cover-letters/${first.id}`, (route) => route.fulfill({
      status: 200, contentType: 'application/json', body: JSON.stringify({ ...first, latex_content: route.request().postDataJSON().latex_content }),
    }))
    await page.route((url) => url.pathname === '/jobs/submit', async (route) => {
      if (String(route.request().postDataJSON().latex_content).includes('LATEXY_SIGNATURE_START')) {
        signatureCompileRequests += 1
        await compileGate
        return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'stale-signature-compile', message: 'Started' }) })
      }
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ success: true, job_id: 'compile-job-1', message: 'Started' }) })
    })
    await page.route((url) => url.pathname === '/jobs/stale-signature-compile/state', (route) => {
      staleStateReads += 1
      return route.fulfill({ status: 404, body: '' })
    })
    await page.goto(`/workspace/${resumeId}/cover-letter`, { waitUntil: 'domcontentloaded' })
    await page.getByLabel('Printed name').fill('Persisted Before Switch')
    await page.getByRole('button', { name: 'Add signature' }).click()
    await expect.poll(() => signatureCompileRequests).toBe(1)
    mockedCoverLetters = [{ ...MOCK_COVER_LETTERS[1], latex_content: null }]
    await page.evaluate((coverLetterId) => window.history.pushState(null, '', `${location.pathname}?cl=${coverLetterId}`), MOCK_COVER_LETTERS[1].id)
    await expect(page.locator('input[placeholder="Company name"]')).toHaveValue('StartupCo')
    const lateResponse = page.waitForResponse((response) => response.url().endsWith('/jobs/submit'))
    releaseCompile()
    await (await lateResponse).finished()
    await page.waitForTimeout(3_000)
    expect(staleStateReads).toBe(0)
    await expect(page.getByText('Signature saved and added to the cover letter')).toHaveCount(0)
  })

  test('drawn signature is embedded as a bounded compiler asset', async ({ page }) => {
    let savedLatex = ''
    const letter = MOCK_COVER_LETTERS[0]
    await page.route((url) => url.pathname === `/cover-letters/${letter.id}`, async (route) => {
      savedLatex = route.request().postDataJSON().latex_content
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...letter, latex_content: savedLatex }) })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.getByRole('tab', { name: 'Draw' }).click()
    const canvas = page.getByLabel('Draw signature')
    const box = await canvas.boundingBox()
    expect(box).not.toBeNull()
    await page.mouse.move(box!.x + 25, box!.y + 55)
    await page.mouse.down()
    await page.mouse.move(box!.x + 95, box!.y + 25, { steps: 8 })
    await page.mouse.move(box!.x + 160, box!.y + 65, { steps: 8 })
    await page.mouse.up()
    await page.getByRole('button', { name: 'Add signature' }).click()

    await expect.poll(() => savedLatex).toContain('LATEXY_SIGNATURE_DATA:')
    expect(savedLatex).toContain('includegraphics[height=1.4cm,width=5cm,keepaspectratio]{latexy-signature.png}')
  })

  test('uploaded signature can be added and then removed', async ({ page }) => {
    let savedLatex = ''
    const letter = MOCK_COVER_LETTERS[0]
    await page.route((url) => url.pathname === `/cover-letters/${letter.id}`, async (route) => {
      savedLatex = route.request().postDataJSON().latex_content
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ...letter, latex_content: savedLatex }) })
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.getByRole('tab', { name: 'Upload' }).click()
    await page.locator('#signature-upload').setInputFiles({
      name: 'signature.png',
      mimeType: 'image/png',
      buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAgAAAAECAYAAACzzX7wAAAAFUlEQVR4nGPkEpH7z4AHMOGTpI4CAKB4AUOyWpd9AAAAAElFTkSuQmCC', 'base64'),
    })
    await expect(page.getByText('Image ready')).toBeVisible()
    await page.getByRole('button', { name: 'Add signature' }).click()
    await expect.poll(() => savedLatex).toContain('LATEXY_SIGNATURE_DATA:')
    await page.getByRole('button', { name: 'Remove' }).click()
    await expect.poll(() => savedLatex).not.toContain('LATEXY_SIGNATURE_START')
    expect(savedLatex).not.toContain('LATEXY_SIGNATURE_PACKAGE_START')
  })

  test('dark PDF preview filters only the rendered page and persists the preference', async ({ page }) => {
    const blankPdf = Buffer.from(
      'JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2JqCjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2JqCjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCAyMDAgMjAwXSAvQ29udGVudHMgNCAwIFIgPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCAwID4+CnN0cmVhbQoKZW5kc3RyZWFtCmVuZG9iagp4cmVmCjAgNQowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMDkgMDAwMDAgbiAKMDAwMDAwMDA1OCAwMDAwMCBuIAowMDAwMDAwMTE1IDAwMDAwIG4gCjAwMDAwMDAyMDIgMDAwMDAgbiAKdHJhaWxlcgo8PCAvU2l6ZSA1IC9Sb290IDEgMCBSID4+CnN0YXJ0eHJlZgoyNTEKJSVFT0YK',
      'base64',
    )
    await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'completed', stage: '', percent: 100, last_updated: Date.now() / 1000 }),
    }))
    await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/result/), (route) => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: 'compile-job-1', result: { pdf_job_id: 'compile-job-1', page_count: 1 } }),
    }))
    await page.route((url) => url.pathname === '/download/compile-job-1', (route) => route.fulfill({
      status: 200, contentType: 'application/pdf', body: blankPdf,
    }))

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    const canvas = page.locator('.react-pdf__Page canvas').first()
    await expect(canvas).toBeVisible({ timeout: 15_000 })
    await page.getByRole('button', { name: 'Dark PDF preview' }).click()
    await expect(page.getByRole('button', { name: 'Light PDF preview' })).toBeVisible()
    await expect.poll(() => canvas.evaluate((element) => element.parentElement?.parentElement?.style.filter)).toBe('invert(1) hue-rotate(180deg)')
    expect(await page.evaluate(() => localStorage.getItem('latexy_pdf_dark'))).toBe('1')
    await page.reload()
    await expect(page.getByRole('button', { name: 'Light PDF preview' })).toBeVisible({ timeout: 15_000 })
  })

  test('delete cover letter from sidebar', async ({ page }) => {
    await page.route((url) => {
      return !!url.pathname.match(/\/cover-letters\/cl-/) && !url.pathname.includes('/resume/')
    }, async (route) => {
      if (route.request().method() === 'DELETE') {
        return route.fulfill({ status: 204 })
      }
      return route.continue()
    })

    await page.goto(`/workspace/${resumeId}/cover-letter`)
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Previous Cover Letters (2)')).toBeVisible()

    // Click delete on first CL
    const deleteButtons = page.locator('button', { hasText: 'Delete' })
    // There might be multiple Delete buttons (sidebar items)
    const sidebarDeletes = page.locator('.max-h-48 button:has-text("Delete")')
    await sidebarDeletes.first().click()
    await page.getByRole('button', { name: /Confirm delete cover letter/ }).click()

    await expect(page.getByText('Previous Cover Letters (1)')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  Page accessibility / navigation                                    //
// ------------------------------------------------------------------ //

test.describe('Page navigation — cover letters', () => {
  test('/workspace/cover-letters is accessible', async ({ page }) => {
    const response = await page.goto('/workspace/cover-letters')
    expect(response?.status()).toBe(200)
  })

  test('no runtime errors on cover letters page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.route('**/ws/**', route => route.abort())
    await page.goto('/workspace/cover-letters', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('load')
    expect(errors.filter((e) => !e.includes('Warning:'))).toEqual([])
  })
})

// ------------------------------------------------------------------ //
//  API Client runtime validation                                      //
// ------------------------------------------------------------------ //

test.describe('API Client — cover letter methods exist', () => {
  test('no "is not a function" errors on cover letters page', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))

    await mockAuth(page)
    await page.route((url) => url.pathname.startsWith('/cover-letters'), (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          cover_letters: [],
          total: 0,
          page: 1,
          limit: 20,
          pages: 1,
        }),
      })
    )

    await page.goto('/workspace/cover-letters', { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    const hasNotAFunctionError = errors.some((e) => e.includes('is not a function'))
    expect(hasNotAFunctionError).toBe(false)
  })

  test('cover-letters API calls made on listing page load', async ({ page }) => {
    const apiCalls: string[] = []
    await mockAuth(page)
    await page.route('**/*', async (route) => {
      const url = route.request().url()
      if (url.includes('/cover-letters')) {
        apiCalls.push(url)
      }
      if (url.includes('/cover-letters/stats')) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ total: 0 }),
        })
      }
      if (url.match(/\/cover-letters\/(\?|$)/)) {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            cover_letters: [],
            total: 0,
            page: 1,
            limit: 20,
            pages: 1,
          }),
        })
      }
      // Let the more specific auth-session mock registered above handle its
      // request; `continue()` would bypass all earlier Playwright handlers.
      await route.fallback()
    })

    await page.goto('/workspace/cover-letters')
    await page.waitForLoadState('networkidle')
    expect(apiCalls.some((u) => u.includes('/cover-letters/'))).toBe(true)
  })
})
