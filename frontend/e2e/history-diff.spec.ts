import { test, expect, type Page } from '@playwright/test'

// ------------------------------------------------------------------ //
//  Feature 12 — Compilation History Diff Viewer                      //
//  Tests:                                                             //
//    - DiffViewerModal: fullscreen toggle, restore confirmation,     //
//      Escape key behaviour                                           //
//    - VersionHistoryPanel on optimize page: collapsible section,    //
//      entry list, two-select → compare → DiffViewerModal           //
// ------------------------------------------------------------------ //

// ── Mock data ─────────────────────────────────────────────────────────

const RESUME_ID = 'resume-hist-0001'
const CP_A_ID   = 'cp-aaaa-0001'
const CP_B_ID   = 'cp-bbbb-0002'

const MOCK_RESUME = {
  id: RESUME_ID,
  user_id: 'user-1',
  title: 'History Test Resume',
  latex_content: [
    '\\documentclass{article}',
    '\\begin{document}',
    'Current version of resume.',
    '\\end{document}',
  ].join('\n'),
  parent_resume_id: null,
  created_at: '2026-03-01T10:00:00Z',
  updated_at: '2026-03-18T10:00:00Z',
}

const MOCK_CHECKPOINTS = [
  {
    id: CP_B_ID,
    created_at: '2026-03-17T10:00:00Z',
    checkpoint_label: 'After AI optimization',
    is_checkpoint: true,
    is_auto_save: false,
    optimization_level: 'balanced',
    ats_score: 82,
    changes_count: 5,
  },
  {
    id: CP_A_ID,
    created_at: '2026-03-16T10:00:00Z',
    checkpoint_label: 'Before optimization',
    is_checkpoint: true,
    is_auto_save: false,
    optimization_level: null,
    ats_score: 70,
    changes_count: 0,
  },
]

const MOCK_CONTENT_A = {
  original_latex: '\\documentclass{article}\\begin{document}Old version A\\end{document}',
  optimized_latex: '\\documentclass{article}\\begin{document}Optimized version A\\end{document}',
  checkpoint_label: 'Before optimization',
}

const MOCK_CONTENT_B = {
  original_latex: '\\documentclass{article}\\begin{document}Old version B\\end{document}',
  optimized_latex: '\\documentclass{article}\\begin{document}Optimized version B\\end{document}',
  checkpoint_label: 'After AI optimization',
}

const MOCK_SESSION = {
  session: { id: 'sess-1', userId: 'user-1', token: 'test-token' },
  user:    { id: 'user-1', email: 'test@example.com', name: 'Test User' },
}

// ── Shared setup helpers ──────────────────────────────────────────────

async function mockAuth(page: Page) {
  await page.route('**/api/auth/get-session', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_SESSION) })
  )
}

async function mockFeatureFlagsConfig(page: Page) {
  await page.route((url) => url.pathname === '/config/feature-flags', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ trial_limits: true, deep_analysis_trial: true, compile_timeouts: true, task_priority: true, billing: true, upgrade_ctas: true }),
    })
  )
}

async function mockCommon(page: Page) {
  await page.route((url) => url.pathname.startsWith('/analytics'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: '{"message":"ok"}' })
  )
  await page.route((url) => url.pathname === '/ats/quick-score', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ score: 75, grade: 'C', sections_found: [], missing_sections: [], keyword_match_percent: null }),
    })
  )
  await page.route((url) => url.pathname.startsWith('/format'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ supported: true, formats: ['pdf'] }) })
  )
  await page.route((url) => !!url.pathname.match(/\/jobs\/[^/]+\/state/), (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ status: 'queued', stage: '', percent: 0, last_updated: Date.now() / 1000 }),
    })
  )
  await page.route((url) => !!url.pathname.match(/\/download\/.+/), (route) =>
    route.fulfill({ status: 200, contentType: 'application/pdf', body: Buffer.from('%PDF-1.4 mock') })
  )
}

async function mockResume(page: Page) {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_RESUME) })
  )
}

async function mockCheckpoints(page: Page, entries = MOCK_CHECKPOINTS) {
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/checkpoints` && !url.pathname.includes('/content'), (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(entries) })
  )
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/checkpoints/${CP_A_ID}/content`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CONTENT_A) })
  )
  await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/checkpoints/${CP_B_ID}/content`, (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MOCK_CONTENT_B) })
  )
}

async function mockJobSubmit(page: Page, jobId = 'job-hist-001') {
  await page.route((url) => url.pathname === '/jobs/submit', (route) =>
    route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ success: true, job_id: jobId }),
    })
  )
}

async function mockWebSocketIdle(page: Page) {
  await page.routeWebSocket('**/ws/jobs', (ws) => {
    ws.onMessage((data) => {
      try {
        const msg = JSON.parse(data as string)
        if (msg.type === 'ping') ws.send(JSON.stringify({ type: 'pong', server_time: Date.now() / 1000 }))
        if (msg.type === 'subscribe') ws.send(JSON.stringify({ type: 'subscribed', job_id: msg.job_id, replayed_count: 0 }))
      } catch { /* ignore */ }
    })
  })
}

// ------------------------------------------------------------------ //
//  1. Optimize page — Version History section                        //
// ------------------------------------------------------------------ //

test.describe('Optimize page — Version History panel', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockCommon(page)
    await mockResume(page)
    await mockCheckpoints(page)
    await mockJobSubmit(page)
    await mockWebSocketIdle(page)
  })

  test('page loads without JS errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })

  test('Version History section is present in aside', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await expect(page.getByText('Version History')).toBeVisible()
  })

  test('Version History panel is collapsed by default', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    // Checkpoint labels should not be visible yet (panel collapsed)
    await expect(page.getByText('After AI optimization')).not.toBeVisible()
  })

  test('clicking "Version History" header expands the panel', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await expect(page.getByText('Before optimization')).toBeVisible()
  })

  test('clicking header again collapses the panel', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).not.toBeVisible()
  })

  test('expanded panel shows "Show"/"Hide" toggle label', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await expect(page.getByText('Show')).toBeVisible()
    await page.getByText('Version History').click()
    await page.waitForTimeout(300)
    await expect(page.getByText('Hide')).toBeVisible()
  })

  test('empty history shows "No version history yet" message', async ({ page }) => {
    await page.route((url) => url.pathname === `/resumes/${RESUME_ID}/checkpoints` && !url.pathname.includes('/content'), (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    )
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText(/No version history yet/i)).toBeVisible({ timeout: 8_000 })
  })

  test('checkpoint entries show label and type badge', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    // Type badge should be visible
    await expect(page.getByText('Checkpoint').first()).toBeVisible()
  })

  test('checkpoint entries have Restore button', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByRole('button', { name: 'Restore' }).first()).toBeVisible({ timeout: 8_000 })
  })
})

// ------------------------------------------------------------------ //
//  2. Optimize page — Compare two checkpoints → DiffViewerModal      //
// ------------------------------------------------------------------ //

test.describe('Optimize page — checkpoint compare flow', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockCommon(page)
    await mockResume(page)
    await mockCheckpoints(page)
    await mockJobSubmit(page)
    await mockWebSocketIdle(page)
  })

  test('selecting two checkpoints shows "Compare Selected" button', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })

    // Click on both checkpoint cards to select
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()

    await expect(page.getByRole('button', { name: 'Compare Selected' })).toBeVisible()
  })

  test('clicking "Compare Selected" opens DiffViewerModal', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })

    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()

    await page.getByRole('button', { name: 'Compare Selected' }).click()

    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })
  })

  test('DiffViewerModal shows checkpoint label as column header', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')

    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })

    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()

    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })
    // Column labels section (label bar below header) should show checkpoint name
    const labelBar = page.locator('.fixed.inset-0').last().locator('[class*="grid grid-cols-2"]')
    await expect(labelBar).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  3. DiffViewerModal — fullscreen toggle                            //
// ------------------------------------------------------------------ //

test.describe('DiffViewerModal — fullscreen toggle', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockCommon(page)
    await mockResume(page)
    await mockCheckpoints(page)
    await mockJobSubmit(page)
    await mockWebSocketIdle(page)
  })

  async function openDiffModal(page: Page) {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()
    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })
  }

  test('modal has fullscreen toggle button', async ({ page }) => {
    await openDiffModal(page)
    const fsBtn = page.getByTitle(/Fullscreen|Exit fullscreen/i)
    await expect(fsBtn).toBeVisible()
  })

  test('clicking fullscreen button changes modal to full-screen', async ({ page }) => {
    await openDiffModal(page)

    const fsBtn = page.getByTitle('Fullscreen')
    await fsBtn.click()

    // After fullscreen, modal container should be h-screen w-screen
    const modal = page.locator('.fixed.inset-0').last().locator('> div').first()
    const cls = await modal.getAttribute('class')
    expect(cls).toContain('h-screen')
    expect(cls).toContain('w-screen')
  })

  test('clicking fullscreen button again exits fullscreen', async ({ page }) => {
    await openDiffModal(page)

    await page.getByTitle('Fullscreen').click()
    await page.getByTitle('Exit fullscreen').click()

    // Back to normal: should have rounded-2xl
    const modal = page.locator('.fixed.inset-0').last().locator('> div').first()
    const cls = await modal.getAttribute('class')
    expect(cls).toContain('rounded-2xl')
  })

  test('fullscreen button title toggles between "Fullscreen" and "Exit fullscreen"', async ({ page }) => {
    await openDiffModal(page)

    await expect(page.getByTitle('Fullscreen')).toBeVisible()
    await page.getByTitle('Fullscreen').click()
    await expect(page.getByTitle('Exit fullscreen')).toBeVisible()
    await page.getByTitle('Exit fullscreen').click()
    await expect(page.getByTitle('Fullscreen')).toBeVisible()
  })
})

// ------------------------------------------------------------------ //
//  4. DiffViewerModal — restore confirmation dialog                  //
// ------------------------------------------------------------------ //

test.describe('DiffViewerModal — restore confirmation', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockCommon(page)
    await mockResume(page)
    await mockCheckpoints(page)
    await mockJobSubmit(page)
    await mockWebSocketIdle(page)
  })

  async function openDiffModal(page: Page) {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()
    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })
  }

  test('clicking "Restore Left" shows confirmation dialog', async ({ page }) => {
    await openDiffModal(page)

    await page.getByRole('button', { name: 'Restore Left' }).click()

    await expect(page.getByText('Restore this version?')).toBeVisible()
    await expect(page.getByText(/This will replace your current editor content/)).toBeVisible()
  })

  test('confirmation dialog has Cancel and Restore buttons', async ({ page }) => {
    await openDiffModal(page)
    await page.getByRole('button', { name: 'Restore Left' }).click()

    const confirmDialog = page.locator('.absolute.inset-0.z-10')
    await expect(confirmDialog.getByRole('button', { name: 'Cancel' })).toBeVisible()
    await expect(confirmDialog.getByRole('button', { name: 'Restore' })).toBeVisible()
  })

  test('clicking Cancel dismisses confirmation without restoring', async ({ page }) => {
    await openDiffModal(page)
    await page.getByRole('button', { name: 'Restore Left' }).click()
    await expect(page.getByText('Restore this version?')).toBeVisible()

    await page.getByRole('button', { name: 'Cancel' }).click()

    await expect(page.getByText('Restore this version?')).not.toBeVisible()
    // Modal should still be open
    await expect(page.getByText('Compare Versions')).toBeVisible()
  })

  test('Escape dismisses confirmation dialog but keeps modal open', async ({ page }) => {
    await openDiffModal(page)
    await page.getByRole('button', { name: 'Restore Left' }).click()
    await expect(page.getByText('Restore this version?')).toBeVisible()

    await page.keyboard.press('Escape')

    await expect(page.getByText('Restore this version?')).not.toBeVisible()
    // Modal itself still open
    await expect(page.getByText('Compare Versions')).toBeVisible()
  })

  test('Escape on modal (no confirmation open) closes the modal', async ({ page }) => {
    await openDiffModal(page)
    await expect(page.getByText('Restore this version?')).not.toBeVisible()

    await page.keyboard.press('Escape')

    await expect(page.getByText('Compare Versions')).not.toBeVisible()
  })

  test('clicking Restore in confirmation calls onRestore and closes modal', async ({ page }) => {
    await openDiffModal(page)

    await page.getByRole('button', { name: 'Restore Left' }).click()
    await expect(page.getByText('Restore this version?')).toBeVisible()

    await page.locator('.absolute.inset-0.z-10').getByRole('button', { name: 'Restore' }).click()

    await page.waitForTimeout(500)
    // Confirmation and modal should both close
    await expect(page.getByText('Restore this version?')).not.toBeVisible()
    await expect(page.getByText('Compare Versions')).not.toBeVisible()
  })

  test('"Restore Right" also triggers confirmation', async ({ page }) => {
    await openDiffModal(page)

    await page.getByRole('button', { name: 'Restore Right' }).click()

    await expect(page.getByText('Restore this version?')).toBeVisible()
  })

  test('modal renders without JS errors', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await openDiffModal(page)
    await page.waitForTimeout(1_000)
    expect(errors.filter((e) => !e.toLowerCase().includes('warning'))).toHaveLength(0)
  })
})

// ------------------------------------------------------------------ //
//  5. DiffViewerModal — header stats section                         //
// ------------------------------------------------------------------ //

test.describe('DiffViewerModal — header structure', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page)
    await mockFeatureFlagsConfig(page)
    await mockCommon(page)
    await mockResume(page)
    await mockCheckpoints(page)
    await mockJobSubmit(page)
    await mockWebSocketIdle(page)
  })

  test('modal header contains "Compare Versions" title', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()

    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })
  })

  test('modal has Restore Left button', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()

    await expect(page.getByRole('button', { name: 'Restore Left' })).toBeVisible({ timeout: 8_000 })
    await expect(page.getByRole('button', { name: 'Restore Right' })).toBeVisible()
  })

  test('X button closes the modal', async ({ page }) => {
    await page.goto(`/workspace/${RESUME_ID}/optimize`, { waitUntil: 'domcontentloaded' })
    await page.waitForLoadState('networkidle')
    await page.getByText('Version History').click()
    await expect(page.getByText('After AI optimization')).toBeVisible({ timeout: 8_000 })
    await page.getByText('After AI optimization').click()
    await page.getByText('Before optimization').click()
    await page.getByRole('button', { name: 'Compare Selected' }).click()
    await expect(page.getByText('Compare Versions')).toBeVisible({ timeout: 8_000 })

    // Close via X button (last svg button in modal header)
    await page.locator('.fixed.inset-0 button[class*="rounded-lg p-1.5"]').last().click()
    await expect(page.getByText('Compare Versions')).not.toBeVisible()
  })
})
