import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import type { Locator } from '@playwright/test'
import { expect, test } from './quality-test'
import { fulfillQualityJson, QUALITY_FEATURES, qualityOrigins } from './mock-api'

const original = 'Worked with engineering to ship the checkout flow.'
const suggestion = 'Designed the checkout flow with research and engineering.'

// These samples are local UI state. Fail closed on backend calls so no test
// needs an account, AI provider, compilation service, or a real résumé.
test.beforeEach(async ({ page }) => {
    const { appOrigin, backendOrigin } = qualityOrigins()
    await page.route(url => url.origin === backendOrigin, route => {
        const path = new URL(route.request().url()).pathname
        const body = path === '/config/entitlements' ? { features: { ...QUALITY_FEATURES, b10: true } }
            : path === '/tenants/resolve-host' ? { tenant: null }
                : path === '/portfolio/resolve-domain' ? { profile: null } : {}
        return fulfillQualityJson(route, body)
    })
    await page.route(url => url.origin === appOrigin && url.pathname.startsWith('/api/auth/'), route =>
        fulfillQualityJson(route, null)
    )
    await page.goto('/', { waitUntil: 'networkidle' })
    await expect(page.getByTestId('review-desk')).toBeVisible()
})

test('hero review never replaces a saved custom contribution with the starter example', async ({ page }) => {
    const desk = page.getByTestId('review-desk')
    const custom = 'Led accessibility testing with six product teams.'
    await desk.getByRole('tab', { name: 'Write', exact: true }).click()
    await desk.getByLabel('Your role', { exact: true }).fill('Accessibility Designer')
    await desk.getByLabel('One contribution', { exact: true }).fill(custom)
    await desk.getByRole('button', { name: 'Update sample' }).click()
    await desk.getByRole('tab', { name: 'Review', exact: true }).click()
    await expect(desk.getByRole('button', { name: 'Use suggestion', exact: true })).toBeDisabled()
    await expect(desk.getByRole('tabpanel')).toContainText('Your contribution stays unchanged.')
    await desk.getByRole('button', { name: 'Keep original', exact: true }).click()
    await expect(desk.locator('.rd-highlight')).toHaveText(custom)
    await desk.getByRole('tab', { name: 'Write', exact: true }).click()
    await expect(desk.getByLabel('Your role', { exact: true })).toHaveValue('Accessibility Designer')
    await expect(desk.getByLabel('One contribution', { exact: true })).toHaveValue(custom)
})

for (const field of ['Your role', 'One contribution']) {
    test(`hero rejects a whitespace-only ${field.toLowerCase()} without changing the sample`, async ({ page }) => {
        const desk = page.getByTestId('review-desk')
        await desk.getByRole('tab', { name: 'Write', exact: true }).click()
        await desk.getByLabel(field, { exact: true }).fill('   ')
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(desk.getByRole('alert')).toHaveText(field === 'Your role'
            ? 'Enter a role before updating the sample.'
            : 'Enter a contribution before updating the sample.')
        await expect(desk.locator('.rd-highlight')).toHaveText(original)
        await expect(desk.locator('.rd-paper header')).toContainText('Product Designer')
        await desk.getByLabel(field, { exact: true }).fill(field === 'Your role' ? 'Researcher' : 'Interviewed users to improve onboarding.')
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(desk.getByRole('alert')).toHaveCount(0)
        await expect(desk.getByRole('status')).toContainText('Your wording is now in the sample résumé.')
    })
}

for (const correctedFirst of ['Your role', 'One contribution']) {
    test(`hero retains the other field error after correcting ${correctedFirst.toLowerCase()}`, async ({ page }) => {
        const desk = page.getByTestId('review-desk')
        await desk.getByRole('tab', { name: 'Write', exact: true }).click()
        const role = desk.getByLabel('Your role', { exact: true })
        const contribution = desk.getByLabel('One contribution', { exact: true })
        await role.fill('   ')
        await contribution.fill('   ')
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(desk.getByRole('alert')).toHaveCount(2)
        await expect(role).toHaveAttribute('aria-invalid', 'true')
        await expect(contribution).toHaveAttribute('aria-invalid', 'true')
        const corrected = correctedFirst === 'Your role' ? role : contribution
        const remaining = correctedFirst === 'Your role' ? contribution : role
        await corrected.fill('    ')
        await expect(corrected).toHaveAttribute('aria-invalid', 'true')
        await expect(desk.getByRole('alert')).toHaveCount(2)
        await corrected.fill(correctedFirst === 'Your role' ? '  Researcher  ' : '  Interviewed users.  ')
        await expect(corrected).toHaveAttribute('aria-invalid', 'false')
        await expect(remaining).toHaveAttribute('aria-invalid', 'true')
        await expect(desk.getByRole('alert')).toHaveCount(1)
        await expect(remaining).toHaveAttribute('aria-describedby', correctedFirst === 'Your role'
            ? 'hero-contribution-error' : 'hero-role-error')
        // An invalid partial update must not commit either field.
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(desk.locator('.rd-highlight')).toHaveText(original)
        await expect(desk.locator('.rd-paper header')).toContainText('Product Designer')
        await remaining.fill(correctedFirst === 'Your role' ? '  Interviewed users.  ' : '  Researcher  ')
        await expect(desk.getByRole('alert')).toHaveCount(0)
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(role).toHaveValue('Researcher')
        await expect(contribution).toHaveValue('Interviewed users.')
        await expect(desk.locator('.rd-highlight')).toHaveText('Interviewed users.')
        await expect(desk.locator('.rd-paper header')).toContainText('Researcher')
    })
}

for (const custom of [false, true]) {
    test(`hero preserves ${custom ? 'custom contribution' : 'accepted suggestion'} through Tailor and Export`, async ({ page }) => {
        const desk = page.getByTestId('review-desk')
        const contribution = custom ? 'Led accessibility testing with six teams.' : suggestion
        if (custom) {
            await desk.getByRole('tab', { name: 'Write', exact: true }).click()
            await desk.getByLabel('Your role', { exact: true }).fill('  Staff Designer  ')
            await desk.getByLabel('One contribution', { exact: true }).fill(contribution)
            await desk.getByRole('button', { name: 'Update sample' }).click()
        } else {
            await desk.getByRole('button', { name: 'Use suggestion', exact: true }).click()
        }
        for (let round = 0; round < 2; round++) {
            await desk.getByRole('tab', { name: 'Tailor', exact: true }).click()
            await desk.getByLabel('Sample role', { exact: true }).selectOption('Design systems')
            await desk.getByRole('tab', { name: 'Export', exact: true }).click()
            await desk.getByRole('radio', { name: 'Modern', exact: true }).check()
            await expect(desk.locator('.rd-highlight')).toHaveText(contribution)
            await desk.getByRole('tab', { name: 'Review', exact: true }).click()
            const reviewAction = desk.getByRole('button', { name: custom ? 'Use suggestion' : 'Undo', exact: true })
            if (custom) await expect(reviewAction).toBeDisabled()
            else await expect(reviewAction).toBeEnabled()
            await desk.getByRole('tab', { name: 'Write', exact: true }).click()
            await expect(desk.getByLabel('One contribution', { exact: true })).toHaveValue(contribution)
            await expect(desk.getByLabel('Your role', { exact: true })).toHaveValue(custom ? 'Staff Designer' : 'Product Designer')
            await expect(desk.locator('.rd-sample-status')).toBeEmpty()
        }
    })
}

test('hero field errors and disabled hover remain readable in both themes', async ({ page, context }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'Canonical visual evidence uses Chromium; behavior runs in every project.')
    test.setTimeout(180_000)
    const directory = path.resolve(process.cwd(), '../docs/qa/reviewdesk-followup-2026-10-20')
    await mkdir(directory, { recursive: true })
    const desk = page.getByTestId('review-desk')
    for (const width of [320, 1440]) {
        await page.setViewportSize({ width, height: 1000 })
        for (const theme of ['light', 'dark']) for (const contrast of ['normal', 'high']) {
            await context.addCookies([
                { name: 'latexy-theme', value: theme, url: qualityOrigins().appOrigin },
                { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
            ])
            await page.reload({ waitUntil: 'networkidle' })
            await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
            await desk.getByRole('tab', { name: 'Write', exact: true }).click()
            await desk.getByLabel('Your role', { exact: true }).fill(' ')
            await desk.getByLabel('One contribution', { exact: true }).fill(' ')
            await desk.getByRole('button', { name: 'Update sample' }).click()
            await expect(desk.getByRole('alert')).toHaveCount(2)
            await expect(page.locator('html')).toHaveAttribute('data-contrast', contrast)
            await expect(desk.getByLabel('Your role', { exact: true })).toHaveAccessibleDescription('Enter a role before updating the sample.')
            await expect(desk.getByLabel('One contribution', { exact: true })).toHaveAccessibleDescription('Enter a contribution before updating the sample.')
            await page.evaluate(() => document.fonts.ready)
            const fields = await desk.locator('.rd-note[data-state="active"] input, .rd-note[data-state="active"] textarea, .rd-note[data-state="active"] .rd-field-error, .rd-note[data-state="active"] button').evaluateAll(elements =>
                elements.map(element => {
                    const box = element.getBoundingClientRect()
                    return { top: box.top, bottom: box.bottom, left: box.left, right: box.right }
                })
            )
            for (let index = 0; index < fields.length; index++) {
                expect(fields[index].left).toBeGreaterThanOrEqual(0)
                expect(fields[index].right).toBeLessThanOrEqual(width)
                if (index) expect(fields[index].top).toBeGreaterThanOrEqual(fields[index - 1].bottom)
            }
            await desk.screenshot({ path: path.join(directory, `${width}-${theme}-${contrast}-errors.png`), animations: 'disabled' })
            await desk.getByLabel('Your role', { exact: true }).fill('Designer')
            await desk.getByLabel('One contribution', { exact: true }).fill('Led accessible design research.')
            await desk.getByRole('button', { name: 'Update sample' }).click()
            await desk.getByRole('tab', { name: 'Review', exact: true }).click()
            const disabled = desk.getByRole('button', { name: 'Use suggestion', exact: true })
            await expect(disabled).toBeDisabled()
            await disabled.hover({ force: true })
            await expect(disabled).toHaveCSS('filter', 'none')
            await desk.screenshot({ path: path.join(directory, `${width}-${theme}-${contrast}-disabled-hover.png`), animations: 'disabled' })
            expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        }
    }
})

for (const action of ['Undo', 'Keep original']) {
    test(`hero ${action} restores the sample while preserving an unsaved contribution and role`, async ({ page }) => {
        const desk = page.getByTestId('review-desk')
        await desk.getByRole('button', { name: 'Use suggestion', exact: true }).click()
        await expect(desk.locator('.rd-highlight')).toHaveText(suggestion)
        await desk.getByRole('tab', { name: 'Write', exact: true }).click()
        const draft = 'My unfinished contribution must survive changing tabs.'
        await desk.getByLabel('One contribution', { exact: true }).fill(draft)
        await desk.getByLabel('Your role', { exact: true }).fill('Staff Designer')
        await desk.getByRole('tab', { name: 'Review', exact: true }).click()
        await desk.getByRole('button', { name: action, exact: true }).click()
        await expect(desk.locator('.rd-highlight')).toHaveText(original)
        // Applying and rejecting again must still not consume the draft.
        await desk.getByRole('button', { name: 'Use suggestion', exact: true }).click()
        await desk.getByRole('button', { name: action, exact: true }).click()
        await desk.getByRole('tab', { name: 'Write', exact: true }).click()
        await expect(desk.getByLabel('One contribution', { exact: true })).toHaveValue(draft)
        await expect(desk.getByLabel('Your role', { exact: true })).toHaveValue('Staff Designer')
        await desk.getByRole('button', { name: 'Update sample' }).click()
        await expect(desk.locator('.rd-highlight')).toHaveText(draft)
        await expect(desk.locator('.rd-paper header')).toContainText('Staff Designer')
    })
}

test('feedback tabs preserve independent choices and support undo and keep original', async ({ page }) => {
    const review = page.locator('#resume-feedback')
    const cases = [
        ['Structure', original, suggestion],
        ['Keywords', 'Owned the design system and component library.', 'Maintained the design system and reusable interface components.'],
        ['Readability', 'Conducted user research and turned insights into product improvements.', 'Used research insights to improve the product.'],
    ] as const
    for (const [topic, before, after] of cases) {
        const tab = review.getByRole('tab', { name: topic, exact: true })
        await tab.click()
        await expect(tab).toHaveAttribute('aria-selected', 'true')
        const panel = review.getByRole('tabpanel')
        await expect(panel).toHaveAttribute('aria-labelledby', await tab.getAttribute('id') ?? '')
        await expect(panel.locator('.ts-line-selected')).toHaveText(before)
        await panel.getByRole('button', { name: 'Use suggestion', exact: true }).click()
        await expect(panel.locator('.ts-line-selected')).toHaveText(after)
        await expect(review.getByRole('status')).toContainText('Suggestion applied to this sample.')
    }
    for (const [topic, before, after] of cases) {
        await review.getByRole('tab', { name: topic, exact: true }).click()
        const panel = review.getByRole('tabpanel')
        await expect(panel.locator('.ts-line-selected')).toHaveText(after)
        await panel.getByRole('button', { name: 'Undo', exact: true }).click()
        await expect(panel.locator('.ts-line-selected')).toHaveText(before)
        await panel.getByRole('button', { name: 'Use suggestion', exact: true }).click()
        await panel.getByRole('button', { name: 'Keep original', exact: true }).click()
        await expect(panel.locator('.ts-line-selected')).toHaveText(before)
        await expect(review.getByRole('status')).toContainText('Original wording kept.')
    }
    await expect(review).toContainText('ATS feedback is guidance, not a hiring prediction.')
    await expect(review.getByRole('tabpanel')).toContainText('Illustrative sample. No AI is running here.')
})

test('version focus and layout controls update live HTML independently', async ({ page }) => {
    const versions = page.locator('#tailor-application')
    const general = versions.locator('figure').first().getByRole('article')
    const variant = versions.locator('figure').last().getByRole('article')
    const generalText = await general.innerText()
    await expect(variant).toHaveAccessibleName('Illustrative tailored résumé')
    await versions.getByLabel('Explore a sample focus').selectOption('general')
    await expect(variant).toHaveAccessibleName('Illustrative general résumé')
    await expect(variant).toHaveText(await general.textContent() ?? '')
    await versions.getByLabel('Explore a sample focus').selectOption('research')
    await expect(variant).toContainText('Conducted interviews to understand user needs')
    expect(await general.innerText()).toBe(generalText)

    const source = page.locator('#source-to-pdf')
    const preview = source.getByRole('article')
    const sourceText = await source.getByLabel('Illustrative LaTeX source').textContent()
    await source.getByRole('combobox', { name: 'Typeface', exact: true }).selectOption('sans')
    await source.getByRole('combobox', { name: 'Spacing', exact: true }).selectOption('relaxed')
    await expect(preview).toHaveClass(/ts-document-sans/)
    await expect(preview).toHaveClass(/ts-document-relaxed/)
    await source.getByRole('combobox', { name: 'Typeface', exact: true }).selectOption('serif')
    await expect(preview).not.toHaveClass(/ts-document-sans/)
    await expect(preview).toHaveClass(/ts-document-relaxed/)
    await source.getByRole('combobox', { name: 'Spacing', exact: true }).selectOption('normal')
    await expect(preview).not.toHaveClass(/ts-document-relaxed/)
    expect(await source.getByLabel('Illustrative LaTeX source').textContent()).toBe(sourceText)
    await expect(source).toContainText('PDF generation happens in the studio when compilation is enabled.')
    await expect(source.locator('img, canvas')).toHaveCount(0)
})

async function expectQualifiedExportCopy(panel: Locator, expectedCopy: string) {
    await expect(panel.locator('p').filter({ hasText: 'Preview a layout here.' }))
        .toHaveText(`Preview a layout here. ${expectedCopy}`)
    await expect(panel).not.toContainText(/create and export your own\s+PDF/i)
    // Assert the paragraph about PDF/compilation itself, rather than accepting
    // an unrelated availability status from the CTA as the qualification.
    const copy = (await panel.locator('p').allTextContents())
        .filter(text => /\bPDF\b|\bcompil/i.test(text)).join(' ')
    expect(copy, 'Export explains PDF/compilation availability').toMatch(/\bPDF\b|\bcompil/i)
    expect(copy, 'PDF copy is conditional or states verified availability').toMatch(/\b(when|if|depends|availability|available|unavailable|enabled|cannot)\b/i)
}

async function captureExportEvidence(desk: Locator, projectName: string, state: string) {
    await desk.evaluate(async () => { await document.fonts.ready })
    const directory = path.resolve(process.cwd(), '../docs/qa/typeset-studio-2026-10-18')
    await mkdir(directory, { recursive: true })
    await desk.screenshot({
        path: path.join(directory, `typeset-${projectName}-hero-export-${state}.png`),
        animations: 'disabled',
    })
}

for (const compileAllowed of [false, true]) {
    test(`hero Export keeps editing independent of c05 ${compileAllowed ? 'ON' : 'OFF'} and respects visual/source access`, async ({ page }, testInfo) => {
        const { backendOrigin } = qualityOrigins()
        let visualAllowed = true
        const compileRequests: string[] = []
        page.on('request', request => {
            if (request.method() === 'POST' && /\/(compile|compilations)(?:[/?]|$)/.test(new URL(request.url()).pathname)) {
                compileRequests.push(request.url())
            }
        })
        await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
            fulfillQualityJson(route, { features: { ...QUALITY_FEATURES, a09: true, c01: true, b10: visualAllowed, c05: compileAllowed } })
        )
        for (const visual of [true, false]) {
            visualAllowed = visual
            await page.reload({ waitUntil: 'networkidle' })
            const desk = page.getByTestId('review-desk')
            await desk.getByRole('tab', { name: 'Export', exact: true }).click()
            const panel = desk.getByRole('tabpanel')
            await expectQualifiedExportCopy(panel, compileAllowed
                ? 'PDF export is available when studio access is enabled.'
                : 'PDF export is currently unavailable.')
            await panel.getByRole('radio', { name: 'Modern', exact: true }).check()
            await expect(desk.getByRole('article')).toHaveAttribute('data-layout', 'modern')
            await expect(panel.getByRole('link', { name: visual ? 'Open the studio' : 'Open the source editor', exact: true }))
                .toHaveAttribute('href', visual ? '/try?mode=visual' : '/try?mode=source')
            if (visual) await captureExportEvidence(desk, testInfo.project.name, compileAllowed ? 'c05-on' : 'c05-off')
        }
        expect(compileRequests).toEqual([])
    })
}

async function expectIntermediateAvailabilityLayout(page: import('@playwright/test').Page) {
    await page.setViewportSize({ width: 1101, height: 1000 })
    const layout = await page.locator('.rd-hero').evaluate(element => {
        const box = (selector: string) => element.querySelector(selector)!.getBoundingClientRect()
        const actions = box('.lp-hero-actions')
        const stages = box('.rd-stages')
        const status = element.querySelector('.rd-hero-copy [data-marketing-status]')?.getBoundingClientRect()
        const intersects = (a: DOMRect, b: DOMRect) => Math.min(a.right, b.right) > Math.max(a.left, b.left) + 1 && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top) + 1
        return { overlap: intersects(actions, stages) || (status ? intersects(status, stages) : false), overflow: document.documentElement.scrollWidth > innerWidth }
    })
    expect(layout).toEqual({ overlap: false, overflow: false })
}

test('hero Export remains a usable sample while compilation and studio availability are loading', async ({ page }, testInfo) => {
    const { backendOrigin } = qualityOrigins()
    const desk = page.getByTestId('review-desk')
    await desk.getByRole('tab', { name: 'Export', exact: true }).click()
    let release!: () => void
    const pending = new Promise<void>(resolve => { release = resolve })
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', async route => {
        await pending
        return fulfillQualityJson(route, { features: { ...QUALITY_FEATURES, a09: true, c01: true, b10: true, c05: true } })
    })
    try {
        // Explicit refresh invalidates previous verified grants while pending.
        await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
        const panel = desk.getByRole('tabpanel')
        await expect(panel.getByRole('status')).toContainText('Checking studio availability')
        await expect(panel.locator('[data-marketing-action="primary"]')).toHaveCount(0)
        await expectQualifiedExportCopy(panel, 'Checking PDF export availability.')
        await panel.getByRole('radio', { name: 'Minimal', exact: true }).check()
        await expect(desk.getByRole('article')).toHaveAttribute('data-layout', 'minimal')
        await captureExportEvidence(desk, testInfo.project.name, 'loading')
        await expectIntermediateAvailabilityLayout(page)
        release()
        await expect(panel.getByRole('link', { name: 'Open the studio', exact: true })).toHaveAttribute('href', '/try?mode=visual')
        await expectQualifiedExportCopy(panel, 'PDF export is available when studio access is enabled.')
    } finally {
        release()
    }
})

test('hero Export makes no PDF promise after an availability error and keeps layout controls available', async ({ page }, testInfo) => {
    const { backendOrigin } = qualityOrigins()
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
        fulfillQualityJson(route, { detail: 'Synthetic availability failure' }, 503)
    )
    await page.reload({ waitUntil: 'networkidle' })
    const desk = page.getByTestId('review-desk')
    await desk.getByRole('tab', { name: 'Export', exact: true }).click()
    const panel = desk.getByRole('tabpanel')
    await expect(panel.getByRole('alert')).toContainText('Studio availability could not be verified.')
    await expect(panel.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
    await expect(panel.locator('[data-marketing-action="primary"]')).toHaveCount(0)
    await expectQualifiedExportCopy(panel, 'PDF export availability could not be verified.')
    await panel.getByRole('radio', { name: 'Modern', exact: true }).check()
    await expect(desk.getByRole('article')).toHaveAttribute('data-layout', 'modern')
    await captureExportEvidence(desk, testInfo.project.name, 'error')
    await expectIntermediateAvailabilityLayout(page)
})

// Evidence is deliberately separate from assertions: files are for human pixel
// review and do not establish visual acceptance by themselves.
test('typeset screenshot evidence covers initial samples at four widths in both themes', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'desktop-chromium', 'One canonical evidence set')
    test.setTimeout(180_000)
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.evaluate(() => document.fonts.ready)
    const directory = path.resolve(process.cwd(), '../docs/qa/typeset-studio-2026-10-18')
    await mkdir(directory, { recursive: true })
    const stationery = page.locator('.ts-still-life img')
    await expect(stationery).toHaveAttribute('src', /typeset-still-life-printed/)
    await expect.poll(() => stationery.evaluate(image => {
        const asset = image as HTMLImageElement
        return asset.complete && asset.naturalHeight > 0 ? asset.naturalWidth / asset.naturalHeight : 0
    })).toBeGreaterThan(2.9)
    for (const width of [320, 390, 768, 1440]) {
        await page.setViewportSize({ width, height: 1000 })
        for (const theme of ['light', 'dark']) {
            if (await page.locator('html').getAttribute('data-mode') !== theme) {
                await page.getByRole('button', { name: 'Toggle light or dark mode' }).click()
            }
            await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
            await expect(page.getByTestId('review-desk').locator('.rd-highlight')).toHaveText(original)
            await page.evaluate(() => scrollTo(0, 0))
            if (width === 320) {
                // Root overflow can be clipped by CSS, so inspect the actual
                // critical child boxes against the 20px phone gutters too.
                const boxes = await page.locator('.rd-hero-copy, .rd-hero-copy h1, .rd-hero-copy .lp-hero-actions, .rd-hero-copy .lp-hero-actions > a, .rd-desk, .rd-paper, .rd-annotation, .rd-stages, .rd-stage').evaluateAll(elements =>
                    elements.map(element => {
                        const box = element.getBoundingClientRect()
                        return { name: element.className, left: box.left, right: box.right, width: box.width }
                    })
                )
                for (const box of boxes) {
                    expect(box.width, `${box.name} has a visible width`).toBeGreaterThan(0)
                    expect(box.left, `${box.name} respects the left phone gutter`).toBeGreaterThanOrEqual(19)
                    expect(box.right, `${box.name} respects the right phone gutter`).toBeLessThanOrEqual(301)
                }
            }
            if (width <= 390) {
                const primary = await page.locator('.lp-footer-message [data-marketing-action]').boundingBox()
                const secondary = await page.locator('.ts-closing-secondary').boundingBox()
                expect(primary).not.toBeNull()
                expect(secondary).not.toBeNull()
                expect(secondary!.y - (primary!.y + primary!.height)).toBeGreaterThanOrEqual(11)
                expect(secondary!.height).toBeGreaterThanOrEqual(44)
            }
            const prefix = `typeset-${width}-${theme}`
            await page.screenshot({ path: path.join(directory, `${prefix}-full.png`), fullPage: true, animations: 'disabled', style: 'nextjs-portal { visibility: hidden !important; }' })
            for (const [name, selector] of [['hero', '.rd-hero'], ['workflow', '.ts-workflow'], ['review', '#resume-feedback'], ['versions', '#tailor-application'], ['source', '#source-to-pdf'], ['footer', '.lp-footer']] as const) {
                await page.locator(selector).screenshot({ path: path.join(directory, `${prefix}-${name}.png`), animations: 'disabled', style: 'nextjs-portal { visibility: hidden !important; }' })
            }
            if (width === 768 || width === 1440) {
                const desk = page.getByTestId('review-desk')
                for (const stage of ['Write', 'Review', 'Tailor', 'Export']) {
                    await desk.getByRole('tab', { name: stage, exact: true }).click()
                    await expect(desk.getByRole('tabpanel')).toBeVisible()
                    const geometry = await desk.evaluate(element => {
                        const paper = element.querySelector('.rd-paper')!
                        const note = element.querySelector('.rd-annotation')!
                        const sheet = paper.getBoundingClientRect()
                        const annotation = note.getBoundingClientRect()
                        const intersects = (a: DOMRect, b: DOMRect) =>
                            Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
                            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1
                        const coveredText: string[] = []
                        const walker = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT)
                        while (walker.nextNode()) {
                            const node = walker.currentNode
                            if (!node.textContent?.trim()) continue
                            const range = document.createRange()
                            range.selectNodeContents(node)
                            if (Array.from(range.getClientRects()).some(rect => rect.width > 0 && rect.height > 0 && intersects(rect, annotation))) {
                                coveredText.push(node.textContent.trim())
                            }
                        }
                        return { paperIntersectsAnnotation: intersects(sheet, annotation), coveredText }
                    })
                    if (width === 768) {
                        expect(geometry.paperIntersectsAnnotation, `${prefix} ${stage}: tablet annotation stays outside the paper`).toBe(false)
                    }
                    expect(geometry.coveredText, `${prefix} ${stage}: annotation must not cover résumé text, roles, or dates`).toEqual([])
                    await page.locator('.rd-hero').screenshot({ path: path.join(directory, `${prefix}-hero-${stage.toLowerCase()}.png`), animations: 'disabled', style: 'nextjs-portal { visibility: hidden !important; }' })
                }
                await desk.getByRole('tab', { name: 'Review', exact: true }).click()
            }
        }
    }
})

test('hero controls and résumé text stay clear at intermediate desktop widths', async ({ page }) => {
    for (const width of [1101, 1180, 1280]) {
        await page.setViewportSize({ width, height: 1000 })
        const desk = page.getByTestId('review-desk')
        for (const stage of ['Write', 'Review', 'Tailor', 'Export']) {
            await desk.getByRole('tab', { name: stage, exact: true }).click()
            const result = await desk.evaluate(element => {
                const rect = (selector: string) => element.closest('.rd-hero')!.querySelector(selector)!.getBoundingClientRect()
                const note = rect('.rd-annotation')
                const intersects = (a: DOMRect, b: DOMRect) => Math.min(a.right, b.right) > Math.max(a.left, b.left) + 1 && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top) + 1
                const walker = document.createTreeWalker(element.querySelector('.rd-paper')!, NodeFilter.SHOW_TEXT)
                const covered: string[] = []
                while (walker.nextNode()) {
                    if (!walker.currentNode.textContent?.trim()) continue
                    const range = document.createRange()
                    range.selectNodeContents(walker.currentNode)
                    if (Array.from(range.getClientRects()).some(box => intersects(box, note))) covered.push(walker.currentNode.textContent.trim())
                }
                return { covered, controlsOverlap: intersects(rect('.lp-hero-actions'), rect('.rd-stages')), overflow: document.documentElement.scrollWidth > innerWidth }
            })
            expect(result, `${width}px ${stage}`).toEqual({ covered: [], controlsOverlap: false, overflow: false })
        }
    }
})
