import { expect, test, type Page } from './quality-test'
import { mockEngineAncillaryApi, mockPublicEngineDocument } from './engine-fixtures'
import { fulfillQualityJson, QUALITY_FEATURES, QUALITY_PLANS, qualityOrigins } from './mock-api'
import type { TestInfo } from '@playwright/test'

async function captureLandingEvidence(page: Page, testInfo: TestInfo, name: string, fullPage = false) {
    const path = testInfo.outputPath(`${name}.png`)
    await page.screenshot({ path, fullPage, animations: 'disabled' })
    await testInfo.attach(name, { path, contentType: 'image/png' })
}

const PUBLIC_ROUTES = [
    '/',
    '/platform',
    '/templates',
    '/pricing',
    '/resources',
    '/faq',
    '/login',
    '/signup',
    '/privacy',
    '/terms',
    '/updates',
    '/try',
]

// Resume-mode layout is an explicit opt-in; background generation stays closed.
const PUBLIC_ENGINE_FEATURES = { ...QUALITY_FEATURES, b10: true }

const diagnosticsByPage = new Map<Page, string[]>()

async function installPublicPageMocks(page: Page) {
    const { appOrigin, backendOrigin } = qualityOrigins()
    const unmocked: string[] = []
    diagnosticsByPage.set(page, unmocked)
    // Registered first so narrower mocks below take precedence. Missing fixtures
    // fail diagnostics instead of quietly reaching a live backend.
    await page.route(url => url.origin === backendOrigin, route => {
        unmocked.push(`${route.request().method()} ${route.request().url()}`)
        return fulfillQualityJson(route, { error: 'Unmocked quality API request' }, 501)
    })
    await mockEngineAncillaryApi(page, undefined, { b10: true })
    await mockPublicEngineDocument(page)
    await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/get-session', route =>
        fulfillQualityJson(route, null)
    )
    await page.route(url => url.origin === appOrigin && url.pathname === '/api/auth/providers', route =>
        fulfillQualityJson(route, { google: false, github: false, oidc: null })
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/feature-flags', route =>
        fulfillQualityJson(route, {})
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
        fulfillQualityJson(route, { features: PUBLIC_ENGINE_FEATURES })
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/subscription/plans', route =>
        fulfillQualityJson(route, QUALITY_PLANS)
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/tenants/resolve-host', route =>
        fulfillQualityJson(route, { tenant: null })
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/portfolio/resolve-domain', route =>
        fulfillQualityJson(route, { profile: null })
    )
    await page.route(url => url.origin === backendOrigin && url.pathname === '/telemetry/frontend', route =>
        fulfillQualityJson(route, null, 204)
    )
    await page.route(
        url => url.origin === backendOrigin && (url.pathname === '/templates' || url.pathname.startsWith('/templates/')),
        route => fulfillQualityJson(route, [])
    )
    await page.route(
        url => [appOrigin, backendOrigin].includes(url.origin) && (url.pathname === '/public/trial-status' || url.pathname === '/api/public/trial-status'),
        route => fulfillQualityJson(route, {
            usageCount: 0,
            remainingUses: 3,
            blocked: false,
            canUse: true,
            lastUsed: null,
            trialLimit: 3,
        })
    )
    await page.route('**/ws/**', route => route.abort())
}

test.beforeEach(async ({ page }) => {
    await installPublicPageMocks(page)
})

test.afterEach(async () => {
    try {
        for (const page of diagnosticsByPage.keys()) {
            if (!page.isClosed()) await page.unrouteAll({ behavior: 'wait' })
        }
        expect([...diagnosticsByPage.values()].flat(), 'All quality API requests need explicit fixtures').toEqual([])
    } finally {
        diagnosticsByPage.clear()
    }
})

test('public routes render without runtime errors in every engine', async ({ context }) => {
    test.setTimeout(180_000)
    const runtimeErrors: string[] = []

    for (const route of PUBLIC_ROUTES) {
        const routePage = await context.newPage()
        await installPublicPageMocks(routePage)
        routePage.on('pageerror', error => runtimeErrors.push(error.message))
        try {
            const response = await routePage.goto(route, { waitUntil: 'networkidle' })
            expect(response?.status(), `${route} returned an error response`).toBeLessThan(500)
            await expect(routePage.locator('#main-content')).toBeVisible()
        } finally {
            await routePage.unrouteAll({ behavior: 'wait' })
            await routePage.close()
        }
    }

    expect(runtimeErrors).toEqual([])
})

test('public routes expose named controls and valid document structure', async ({ context }) => {
    test.setTimeout(180_000)
    for (const route of PUBLIC_ROUTES) {
        const routePage = await context.newPage()
        await installPublicPageMocks(routePage)
        await routePage.goto(route, { waitUntil: 'networkidle' })
        if (route === '/templates') {
            await expect(routePage.getByRole('heading', { level: 1, name: 'LaTeX templates, ready to use.' })).toBeVisible()
        }
        if (route === '/pricing') {
            await expect(routePage.getByRole('heading', { level: 1, name: "Start free. Pay only when it's working for you." })).toBeVisible()
            for (const plan of ['Free', 'Basic', 'Pro', 'Your AI key']) {
                await expect(routePage.getByRole('heading', { level: 2, name: plan, exact: true })).toBeVisible()
            }
            await expect(routePage.getByRole('link', { name: 'Try the résumé builder →' })).toHaveAttribute('href', '/try?mode=visual')
            await expect(routePage.getByRole('link', { name: 'Choose Basic', exact: true })).toHaveAttribute('href', '/billing')
        }

        const audit = await routePage.evaluate(() => {
            const isVisible = (element: HTMLElement) => {
                const style = window.getComputedStyle(element)
                const rect = element.getBoundingClientRect()
                return (
                    style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    rect.width > 0 &&
                    rect.height > 0
                )
            }
            const labelledByText = (element: Element) =>
                (element.getAttribute('aria-labelledby') ?? '')
                    .split(/\s+/)
                    .filter(Boolean)
                    .map(id => document.getElementById(id)?.textContent?.trim() ?? '')
                    .join(' ')
                    .trim()
            const controlName = (element: HTMLElement) => {
                const input = element as HTMLInputElement
                const labels = input.labels
                    ? Array.from(input.labels)
                          .map(label => label.textContent?.trim())
                          .join(' ')
                    : ''
                const imageAlt = element.querySelector('img')?.getAttribute('alt') ?? ''
                return [
                    element.getAttribute('aria-label'),
                    labelledByText(element),
                    labels,
                    element.textContent?.trim(),
                    element.getAttribute('title'),
                    imageAlt,
                ].some(value => Boolean(value?.trim()))
            }

            const controls = Array.from(
                document.querySelectorAll<HTMLElement>(
                    'button, a[href], input:not([type="hidden"]), textarea, select, [role="button"]'
                )
            ).filter(element => !element.closest('[aria-hidden="true"]') && isVisible(element))
            const unnamedControls = controls
                .filter(element => !controlName(element))
                .map(element => element.outerHTML.slice(0, 180))
            const ariaHiddenFocusable = Array.from(
                document.querySelectorAll<HTMLElement>(
                    '[aria-hidden="true"] button:not(:disabled), [aria-hidden="true"] a[href], [aria-hidden="true"] input:not(:disabled), [aria-hidden="true"] textarea:not(:disabled), [aria-hidden="true"] select:not(:disabled), [aria-hidden="true"] [tabindex]:not([tabindex="-1"])'
                )
            ).map(element => element.outerHTML.slice(0, 180))

            const duplicateIds = Object.entries(
                Array.from(document.querySelectorAll<HTMLElement>('[id]')).reduce<
                    Record<string, number>
                >((counts, element) => {
                    counts[element.id] = (counts[element.id] ?? 0) + 1
                    return counts
                }, {})
            )
                .filter(([, count]) => count > 1)
                .map(([id]) => id)

            const headingLevels = Array.from(
                document.querySelectorAll<HTMLElement>('h1, h2, h3, h4, h5, h6')
            )
                .filter(isVisible)
                .map(heading => Number.parseInt(heading.tagName.slice(1), 10))
            const skippedHeadingLevels = headingLevels.flatMap((level, index) => {
                const previousLevel = headingLevels[index - 1]
                return previousLevel !== undefined && level > previousLevel + 1
                    ? [`h${previousLevel} -> h${level}`]
                    : []
            })

            return {
                htmlLanguage: document.documentElement.lang,
                mainCount: document.querySelectorAll('main').length,
                h1Count: headingLevels.filter(level => level === 1).length,
                skippedHeadingLevels,
                duplicateIds,
                unnamedControls,
                ariaHiddenFocusable,
            }
        })

        expect(audit.htmlLanguage, `${route} must declare its document language`).toBe('en')
        expect(audit.mainCount, `${route} must expose exactly one main landmark`).toBe(1)
        expect(audit.h1Count, `${route} must expose exactly one visible h1`).toBe(1)
        expect(audit.skippedHeadingLevels, `${route} skips a heading level`).toEqual([])
        expect(audit.duplicateIds, `${route} contains duplicate element IDs`).toEqual([])
        expect(
            audit.ariaHiddenFocusable,
            `${route} contains focusable controls hidden from assistive technology`
        ).toEqual([])
        expect(
            audit.unnamedControls,
            `${route} contains controls without accessible names`
        ).toEqual([])
        await routePage.unrouteAll({ behavior: 'wait' })
        await routePage.close()
    }
})

test('skip navigation and reduced-motion preferences are honored', async ({ page, browserName }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    // macOS WebKit follows Safari's default keyboard policy: Option-Tab
    // includes links, whereas Tab alone can skip them. Exercise actual keyboard
    // navigation rather than programmatically focusing the skip link or changing
    // the user's system settings. Other engines/platforms retain the Tab check.
    await page.keyboard.press(browserName === 'webkit' && process.platform === 'darwin' ? 'Alt+Tab' : 'Tab')
    const skipLink = page.getByRole('link', { name: 'Skip to content' })
    await expect(skipLink).toBeFocused()
    await page.keyboard.press('Enter')
    await expect(page.locator('#main-content')).toBeFocused()

    const motionAudit = await page.evaluate(async () => {
        await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
        const parseDuration = (value: string) =>
            Math.max(
                ...value.split(',').map(part => {
                    const duration = part.trim()
                    return duration.endsWith('ms')
                        ? Number.parseFloat(duration)
                        : Number.parseFloat(duration) * 1000
                })
            )
        const durations = Array.from(document.querySelectorAll<HTMLElement>('body *'))
            .filter(element => {
                const rect = element.getBoundingClientRect()
                return rect.width > 0 && rect.height > 0
            })
            .flatMap(element => {
                const style = getComputedStyle(element)
                return [
                    parseDuration(style.animationDuration),
                    parseDuration(style.transitionDuration),
                ]
            })
            .filter(Number.isFinite)

        return {
            longestDurationMs: Math.max(0, ...durations),
            runningAnimations: document
                .getAnimations()
                .filter(
                    animation =>
                        animation.playState === 'running' &&
                        Number(animation.effect?.getComputedTiming().duration ?? 0) > 0.001
                ).length,
        }
    })

    expect(motionAudit.longestDurationMs).toBeLessThanOrEqual(0.001)
    expect(motionAudit.runningAnimations).toBe(0)
})

test('landing review desk produces desktop and phone evidence in both themes', async ({ page }, testInfo) => {
    test.setTimeout(180_000)
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/', { waitUntil: 'networkidle' })
    await page.evaluate(() => document.fonts.ready)
    await expect(page.locator('.lp-hero-actions [data-marketing-action="primary"]')).toBeVisible()
    for (const width of [1440, 1101, 1024, 768, 430, 390, 360, 320]) {
        await page.setViewportSize({ width, height: 1000 })
        for (const theme of ['light', 'dark']) {
            if (await page.locator('html').getAttribute('data-mode') !== theme) {
                await page.getByRole('button', { name: 'Toggle light or dark mode' }).click()
            }
            await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
            await expect(page.getByRole('heading', { name: 'Different roles. Sharper résumés.', exact: true })).toBeVisible()
            await page.evaluate(() => scrollTo(0, 0))
            const bounds = await page.locator('.lp-hero-actions > a:visible').evaluateAll(items => items.map(item => {
                const { x, y, width, height } = item.getBoundingClientRect()
                return { x, y, width, height }
            }))
            expect(bounds).toHaveLength(2)
            // The editorial hero may wrap its secondary link on narrow screens.
            // Both actions must remain large enough and never overlap.
            const separateRows = bounds[1].y >= bounds[0].y + bounds[0].height
            const separateColumns = bounds[1].x >= bounds[0].x + bounds[0].width
            expect(separateRows || separateColumns).toBe(true)
            expect(bounds.every(box => box.height >= 44 && box.width >= 100)).toBe(true)
            expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width + 1)
            const workflow = page.locator('.ts-workflow ol a')
            await expect(workflow).toHaveCount(4)
            for (const link of await workflow.all()) {
                const box = await link.boundingBox()
                expect(box?.width).toBeGreaterThan(44)
                expect(box?.height).toBeGreaterThan(44)
            }
            await expect(page.locator('.rd-note').getByRole('button', { name: 'Use suggestion' })).toBeVisible()
            if (width === 1440 || width === 390 || width === 320) {
                await captureLandingEvidence(page, testInfo, `review-desk-${width}-${theme}`, true)
                await captureLandingEvidence(page, testInfo, `review-hero-${width}-${theme}`)
            }
        }
    }
    expect(errors).toEqual([])
})

test('landing appearance keeps contrast inside the keyboard accessible menu', async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle' })
    for (const width of [390, 1280]) {
        await page.setViewportSize({ width, height: 900 })
        await expect(page.getByRole('button', { name: 'Toggle light or dark mode' })).toHaveCount(1)
        await expect(page.getByRole('button', { name: /Turn .* high contrast mode/ })).toHaveCount(0)
        const trigger = page.getByRole('button', { name: 'Open navigation menu' })
        await trigger.click()
        const contrast = page.getByRole('button', { name: 'Turn on high contrast mode' })
        await expect(contrast).toBeVisible()
        await contrast.click()
        await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
        await page.keyboard.press('Escape')
        await expect(trigger).toBeFocused()
        await expect(page.getByRole('button', { name: /Turn .* high contrast mode/ })).toHaveCount(0)
        await trigger.click()
        await page.getByRole('button', { name: 'Turn off high contrast mode' }).click()
        await expect(page.locator('html')).toHaveAttribute('data-contrast', 'normal')
        await page.keyboard.press('Escape')
    }
})

test('landing glass controls keep sound opt-in and preserve layout selection', async ({ page }, testInfo) => {
    const mediaRequests: string[] = []
    page.on('request', request => { if (request.resourceType() === 'media') mediaRequests.push(request.url()) })
    await page.addInitScript(() => {
        const scope = window as typeof window & { landingAudioCreates: number; landingAudioCloses: number }
        scope.landingAudioCreates = 0
        scope.landingAudioCloses = 0
        const NativeAudioContext = window.AudioContext
        if (NativeAudioContext) {
            window.AudioContext = class extends NativeAudioContext {
                constructor(options?: AudioContextOptions) {
                    super(options)
                    scope.landingAudioCreates++
                }
                close() { scope.landingAudioCloses++; return super.close() }
            }
        }
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    const audioCounts = () => page.evaluate(() => {
        const scope = window as typeof window & { landingAudioCreates: number; landingAudioCloses: number }
        return { created: scope.landingAudioCreates, closed: scope.landingAudioCloses }
    })
    await page.locator('#resume-feedback').scrollIntoViewIfNeeded()
    expect((await audioCounts()).created).toBe(0)
    await expect(page.getByRole('button', { name: 'Interface sounds', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    const sound = page.getByRole('button', { name: 'Interface sounds', exact: true })
    await expect(sound).toHaveAttribute('aria-pressed', 'false')
    await sound.click()
    await expect(sound).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(async () => (await audioCounts()).created).toBe(1)
    const menu = page.locator('#landing-navigation')
    await expect(menu).toHaveCSS('opacity', '1')
    await expect(menu).toHaveAttribute('style', /height:\s*auto/)
    await testInfo.attach('landing-glass-menu', { body: await page.screenshot(), contentType: 'image/png' })
    const soundBox = await sound.boundingBox()
    expect(soundBox?.height).toBeLessThanOrEqual(52)
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'Toggle light or dark mode', exact: true }).click()
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    await expect(sound).toHaveAttribute('aria-pressed', 'true')
    await expect(menu).toHaveCSS('opacity', '1')
    await expect(menu).toHaveAttribute('style', /height:\s*auto/)
    await testInfo.attach('landing-glass-menu-dark', { body: await page.screenshot(), contentType: 'image/png' })
    await page.keyboard.press('Escape')
    await page.getByRole('tab', { name: 'Export', exact: true }).click()
    await page.getByRole('radio', { name: 'Modern', exact: true }).check()
    await expect(page.getByRole('radio', { name: 'Modern', exact: true })).toBeChecked()
    await expect(page.locator('.rd-paper')).toHaveAttribute('data-layout', 'modern')
    expect((await audioCounts()).created).toBe(1)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    await sound.click()
    await expect(sound).toHaveAttribute('aria-pressed', 'false')
    await expect.poll(async () => (await audioCounts()).closed).toBe(1)
    await page.getByRole('button', { name: 'Turn on high contrast mode' }).click()
    await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
    await expect.poll(() => page.locator('.lp-header').evaluate(element => getComputedStyle(element).backdropFilter)).toBe('none')
    expect(mediaRequests).toEqual([])
    await page.keyboard.press('Escape')
})

test('landing pricing navigation follows the billing feature flag', async ({ page }, testInfo) => {
    const { backendOrigin } = qualityOrigins()
    const featureFlags = (billing: boolean) =>
        page.route(url => url.origin === backendOrigin && url.pathname === '/config/feature-flags', route =>
            fulfillQualityJson(route, { billing })
        )
    await featureFlags(false)
    await page.goto('/', { waitUntil: 'networkidle' })
    const headerPricing = page.locator('.lp-navigation a[href="/pricing"]')
    const footerPricing = page.locator('.lp-footer-links a[href="/pricing"]')
    await expect(headerPricing).toHaveCount(0)
    await expect(footerPricing).toHaveCount(0)
    if (testInfo.project.metadata.mobile) {
        await page.locator('.lp-menu-trigger').click()
        await expect(page.locator('.lp-mobile-navigation a[href="/pricing"]')).toHaveCount(0)
    }

    await featureFlags(true)
    await page.reload({ waitUntil: 'networkidle' })
    await expect(headerPricing).toHaveCount(1)
    await expect(footerPricing).toHaveCount(1)
    if (testInfo.project.metadata.mobile) {
        await page.locator('.lp-menu-trigger').click()
        await expect(page.locator('.lp-mobile-navigation a[href="/pricing"]')).toHaveCount(1)
    }
})

test('landing native hero preserves edits, supports review undo and changes layouts without WebGL', async ({ page }) => {
    await page.addInitScript(() => {
        const native = HTMLCanvasElement.prototype.getContext
        HTMLCanvasElement.prototype.getContext = function (this: HTMLCanvasElement, type: string, ...args: unknown[]) {
            if (type === 'webgl' || type === 'webgl2' || type === 'experimental-webgl') return null
            return Reflect.apply(native, this, [type, ...args])
        } as typeof native
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    const desk = page.getByTestId('review-desk')
    const paper = desk.locator('.rd-paper')
    await expect(desk.locator('img, canvas')).toHaveCount(0)
    await expect(paper.getByRole('heading', { name: 'Alex Morgan' })).toBeVisible()
    await expect(desk.getByRole('tab', { name: 'Review', exact: true })).toHaveAttribute('aria-selected', 'true')
    await desk.getByRole('button', { name: 'Use suggestion' }).click()
    await expect(paper).toContainText('Designed the checkout flow with research and engineering.')
    await desk.getByRole('button', { name: 'Undo', exact: true }).click()
    await expect(paper).toContainText('Worked with engineering to ship the checkout flow.')
    await desk.getByRole('tab', { name: 'Write', exact: true }).click()
    await page.getByLabel('Your role', { exact: true }).fill('W'.repeat(60))
    const contribution = 'Designed a clearer application flow with research and engineering.'
    await page.getByLabel('One contribution', { exact: true }).fill(contribution)
    await desk.getByRole('button', { name: 'Update sample' }).click()
    await expect(paper).toContainText(contribution)
    await desk.getByRole('tab', { name: 'Review', exact: true }).click()
    await expect(desk.getByRole('button', { name: 'Use suggestion' })).toBeDisabled()
    await desk.getByRole('button', { name: 'Keep original' }).click()
    await expect(paper).toContainText(contribution)
    await desk.getByRole('tab', { name: 'Write', exact: true }).click()
    const unfinished = 'An unfinished edit that must survive changing tabs.'
    await page.getByLabel('One contribution', { exact: true }).fill(unfinished)
    await desk.getByRole('tab', { name: 'Review', exact: true }).click()
    await desk.getByRole('button', { name: 'Keep original' }).click()
    await expect(paper).toContainText(contribution)
    await desk.getByRole('tab', { name: 'Write', exact: true }).click()
    await expect(page.getByLabel('One contribution', { exact: true })).toHaveValue(unfinished)
    await page.getByLabel('One contribution', { exact: true }).fill(contribution)
    await desk.getByRole('button', { name: 'Update sample' }).click()
    await desk.getByRole('tab', { name: 'Tailor', exact: true }).click()
    await page.getByLabel('Sample role', { exact: true }).selectOption('Design systems')
    await expect(desk.getByRole('tabpanel')).toContainText('accessible components')
    await desk.getByRole('tab', { name: 'Export', exact: true }).click()
    await expect(page.getByRole('radio', { name: 'Classic', exact: true })).toBeChecked()
    await expect(page.getByRole('radio').first()).toHaveAccessibleName('Classic')
    for (const layout of ['Modern', 'Minimal', 'Classic']) {
        await page.getByRole('radio', { name: layout, exact: true }).check()
        await expect(paper).toHaveAttribute('data-layout', layout.toLowerCase())
        await expect(paper).toContainText(contribution)
    }
    expect(await paper.evaluate(element => getComputedStyle(element).userSelect)).not.toBe('none')
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1)
    await page.reload({ waitUntil: 'networkidle' })
    await expect(paper).toContainText('Worked with engineering to ship the checkout flow.')
    await expect(paper).toContainText('Product Designer')
})

test('landing workflow and supporting tabs align focus, content and selection', async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle' })
    const tabs = page.getByRole('tablist', { name: 'Explore the résumé workflow' })
    await tabs.getByRole('tab', { name: 'Review', exact: true }).focus()
    for (const name of ['Tailor', 'Export', 'Write', 'Review']) {
        await page.keyboard.press('ArrowRight')
        const tab = tabs.getByRole('tab', { name, exact: true })
        await expect(tab).toBeFocused()
        await expect(tab).toHaveAttribute('aria-selected', 'true')
        const panel = page.getByTestId('review-desk').getByRole('tabpanel')
        await expect(panel).toHaveAttribute('aria-labelledby', await tab.getAttribute('id') ?? '')
    }
    await page.keyboard.press('Home')
    await expect(tabs.getByRole('tab', { name: 'Write', exact: true })).toBeFocused()
    await page.keyboard.press('End')
    await expect(tabs.getByRole('tab', { name: 'Export', exact: true })).toBeFocused()
    await page.getByRole('tab', { name: 'Keywords', exact: true }).click()
    await expect(page.locator('#resume-feedback').getByRole('tabpanel')).toContainText('Use relevant terms naturally')
    await page.getByLabel('Explore a sample focus').selectOption('general')
    await expect(page.locator('#tailor-application').getByRole('article', { name: 'Illustrative general résumé' })).toHaveCount(2)
    await page.getByRole('combobox', { name: 'Typeface', exact: true }).selectOption('sans')
    await expect(page.locator('#source-to-pdf article')).toHaveClass(/ts-document-sans/)
    await page.getByRole('combobox', { name: 'Spacing', exact: true }).selectOption('relaxed')
    await expect(page.locator('#source-to-pdf article')).toHaveClass(/ts-document-relaxed/)
})

test('landing phone stages retain edits and usable controls in both themes', async ({ page }, testInfo) => {
    test.skip(testInfo.project.metadata.mobile !== true, 'Touch composition contract')
    await page.goto('/', { waitUntil: 'networkidle' })
    for (const theme of ['light', 'dark']) {
        if (await page.locator('html').getAttribute('data-mode') !== theme) await page.getByRole('button', { name: 'Toggle light or dark mode' }).click()
        for (const stage of ['Write', 'Review', 'Tailor', 'Export']) {
            await page.getByRole('tab', { name: stage, exact: true }).click()
            const panel = page.getByTestId('review-desk').getByRole('tabpanel')
            await expect(panel).toBeVisible()
            if (stage === 'Write') {
                await page.getByLabel('One contribution', { exact: true }).fill('W'.repeat(240))
                await panel.getByRole('button', { name: 'Update sample' }).click()
            }
            await expect(page.locator('.rd-highlight')).toContainText('W'.repeat(240))
            expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width + 1)
            await testInfo.attach(`review-phone-${theme}-${stage.toLowerCase()}`, { body: await panel.screenshot(), contentType: 'image/png' })
        }
    }
})

test('landing sends native résumé content and matching FAQ data in the HTML response', async ({ request }) => {
    const response = await request.get('/')
    expect(response.ok()).toBe(true)
    const html = await response.text()
    expect(html).toContain('<h1 id="landing-title">A better résumé')
    expect(html).toContain('aria-label="Classic sample résumé"')
    expect(html).toContain('<h3>Make the contribution clear</h3>')
    const scripts = [...html.matchAll(/<script type="application\/ld\+json">([\s\S]*?)<\/script>/g)]
    const faq = scripts.map(match => JSON.parse(match[1])).find(schema => schema['@type'] === 'FAQPage')
    expect(faq.mainEntity).toHaveLength(5)
    for (const entry of faq.mainEntity) {
        expect(html).toContain(entry.name.replaceAll('&', '&amp;'))
        expect(entry.acceptedAnswer.text.length).toBeGreaterThan(40)
    }
})

test('landing keeps a public entry point when capabilities are unavailable', async ({ page }) => {
    const { backendOrigin } = qualityOrigins()
    await page.route(
        url => url.origin === backendOrigin && url.pathname === '/config/entitlements',
        route => fulfillQualityJson(route, { features: {} })
    )
    await page.goto('/', { waitUntil: 'networkidle' })
    const hero = page.locator('.lp-hero-actions')
    await expect(hero.locator('[data-marketing-action="primary"]')).toHaveCount(0)
    await expect(hero.getByRole('link', { name: 'Explore the sample' })).toBeVisible()
    await expect(hero.getByRole('link', { name: 'Explore the sample' })).toHaveAttribute(
        'href',
        '#resume-feedback'
    )
    await expect(hero.getByRole('link', { name: 'Explore templates' })).toHaveCount(0)
})

test('mobile studio keeps primary controls reachable without document overflow', async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.metadata.mobile !== true, 'Mobile-only contract')

    // The controls are server-rendered, but their state handlers attach during
    // hydration. Wait for the deterministic mocked page to settle before click.
    await page.goto('/try', { waitUntil: 'networkidle' })
    await expect(page.getByRole('button', { name: 'Editor', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'PDF', exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Update PDF preview', exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Tools', exact: true }).click()
    await expect(page.getByRole('button', { name: /Import file/ })).toBeVisible()

    const layout = await page.evaluate(() => ({
        viewportWidth: window.innerWidth,
        documentWidth: document.documentElement.scrollWidth,
    }))
    expect(layout.documentWidth).toBeLessThanOrEqual(layout.viewportWidth + 1)

    const screenshot = await page.screenshot({
        fullPage: false,
        animations: 'disabled',
        caret: 'hide',
    })
    await testInfo.attach('mobile-studio', { body: screenshot, contentType: 'image/png' })
})


test('disabled templates expose a named recovery page without mounting the catalog', async ({ page }) => {
    const { backendOrigin } = qualityOrigins()
    let catalogReads = 0
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
        fulfillQualityJson(route, { features: { ...PUBLIC_ENGINE_FEATURES, b04: false } })
    )
    await page.route(url => url.origin === backendOrigin && (url.pathname === '/templates' || url.pathname.startsWith('/templates/')), route => {
        catalogReads += 1
        return fulfillQualityJson(route, [])
    })
    await page.goto('/templates', { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { level: 1, name: 'Feature unavailable' })).toBeVisible()
    await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
    await expect(page.getByRole('link', { name: 'Back to workspace' })).toBeVisible()
    expect(catalogReads).toBe(0)
})

test('denied studio import preserves the baseline editor and manual compile', async ({ page }) => {
    const { backendOrigin } = qualityOrigins()
    await page.route(url => url.origin === backendOrigin && url.pathname === '/config/entitlements', route =>
        fulfillQualityJson(route, { features: { ...PUBLIC_ENGINE_FEATURES, a09: true, b01: true, c01: true, c05: true, b06: false } })
    )
    await page.goto('/try', { waitUntil: 'networkidle' })
    await expect(page.getByRole('button', { name: 'Update PDF preview', exact: true })).toBeVisible()
    const tools = page.getByRole('button', { name: 'Tools', exact: true })
    if (await tools.isVisible()) await tools.click()
    await expect(page.getByRole('button', { name: /Import file/ })).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1, name: 'Résumé Studio' })).toBeAttached()
})
