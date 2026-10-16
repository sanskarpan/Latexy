import { expect, test, type Page } from './quality-test'
import { mockEngineAncillaryApi, mockPublicEngineDocument } from './engine-fixtures'
import { fulfillQualityJson, QUALITY_FEATURES, QUALITY_PLANS, qualityOrigins } from './mock-api'

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

test('representative public surface produces non-empty visual evidence', async ({
    page,
}, testInfo) => {
    const hydrationErrors: string[] = []
    page.on('console', message => {
        if (message.type() === 'error' && /hydration|hydrated|server rendered HTML|Minified React error/i.test(message.text())) {
            hydrationErrors.push(message.text())
        }
    })
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' })
    if (!testInfo.project.metadata.mobile) await page.setViewportSize({ width: 1440, height: 1000 })
    const { backendOrigin } = qualityOrigins()
    // This visual specimen uses allowed marketing entry points, independently
    // of the denied-capability tests below. No live services are contacted.
    await page.route(
        url => url.origin === backendOrigin && url.pathname === '/config/entitlements',
        route => fulfillQualityJson(route, { features: { ...PUBLIC_ENGINE_FEATURES, b08: true } })
    )
    await page.goto('/', { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    expect(hydrationErrors, 'The landing page must hydrate without attribute drift').toEqual([])

    const layouts = page.getByRole('group', { name: 'Sample résumé layouts' })
    await expect(layouts.getByRole('button').first()).toHaveAttribute('aria-pressed', 'true')
    await expect(layouts.getByRole('button').first()).toContainText('Classic')
    const expectHeroCardsInsideScene = async () => {
        await expect.poll(() => page.locator('.lp-document-card').evaluateAll(cards => {
            const visible = cards.filter(card => card.getBoundingClientRect().width > 0)
            if (!visible.length) return Infinity
            return Math.max(...visible.map(card => {
                const bounds = card.getBoundingClientRect()
                const scene = card.closest('.lp-document-scene')!.getBoundingClientRect()
                return Math.max(scene.left - bounds.left, bounds.right - scene.right, scene.top - bounds.top, bounds.bottom - scene.bottom)
            }))
        })).toBeLessThanOrEqual(1)
    }
    await expectHeroCardsInsideScene()
    const utilityBorders = await page.locator('.lp-header-control').evaluateAll(elements =>
        elements.map(element => getComputedStyle(element).borderTopWidth)
    )
    expect(utilityBorders.every(border => border === '0px')).toBe(true)
    if (testInfo.project.metadata.mobile) {
        const actions = await page.locator('.lp-hero-actions > a:visible').all()
        const primary = await actions[0].boundingBox()
        const secondary = await actions[1].boundingBox()
        expect(primary).not.toBeNull()
        expect(secondary).not.toBeNull()
        expect(Math.abs(primary!.y - secondary!.y)).toBeLessThan(1)
        expect(secondary!.x).toBeGreaterThanOrEqual(primary!.x + primary!.width)
    }

    const viewport = page.viewportSize()
    const mainBox = await page.locator('#main-content').boundingBox()
    expect(viewport).not.toBeNull()
    expect(mainBox).not.toBeNull()
    expect(mainBox!.width).toBeLessThanOrEqual(viewport!.width + 1)
    expect(mainBox!.height).toBeGreaterThan(300)

    const sections = [
        '.lp-hero',
        '.lp-gallery',
        '.lp-builder-section',
        '.lp-analysis-section',
        '.lp-tailoring-section',
        '.lp-applications-section',
        '.lp-latex-section',
        '.lp-faq',
        '.lp-closing',
        '.lp-footer',
    ]
    const settle = async () => {
        await page.evaluate(() => document.fonts.ready)
        await page.waitForFunction(() =>
            [...document.images]
                .filter(image => {
                    const rect = image.getBoundingClientRect()
                    return rect.width > 0 && rect.bottom > 0 && rect.top < window.innerHeight
                })
                .every(image => image.complete && image.naturalWidth > 0)
        )
        await page.evaluate(
            () =>
                new Promise<void>(resolve =>
                    requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
                )
        )
    }
    for (const theme of ['light', 'dark'] as const) {
        if ((await page.locator('html').getAttribute('data-mode')) !== theme) {
            await page.getByRole('button', { name: 'Toggle light or dark mode' }).click()
        }
        await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
        await settle()
        const geometry: Record<string, unknown> = { viewport: page.viewportSize(), theme }
        for (const selector of sections) {
            const section = page.locator(selector)
            await section.scrollIntoViewIfNeeded()
            await settle()
            const box = await section.boundingBox()
            geometry[selector] = box
                ? { ...box, y: box.y + (await page.evaluate(() => window.scrollY)) }
                : null
            await testInfo.attach(`landing-${theme}-${selector.slice(1)}`, {
                body: await section.screenshot({ animations: 'disabled', caret: 'hide' }),
                contentType: 'image/png',
            })
        }
        await page.evaluate(() => scrollTo(0, 0))
        await settle()
        const screenshot = await page.screenshot({
            fullPage: true,
            animations: 'disabled',
            caret: 'hide',
        })
        expect(screenshot.byteLength).toBeGreaterThan(20_000)
        await testInfo.attach(theme === 'light' ? 'landing-page' : 'landing-page-dark', {
            body: screenshot,
            contentType: 'image/png',
        })
        await testInfo.attach(`landing-layout-${theme}`, {
            body: Buffer.from(JSON.stringify(geometry, null, 2)),
            contentType: 'application/json',
        })
        const currentViewport = page.viewportSize()!
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
            currentViewport.width + 1
        )
    }
    await page.getByRole('button', { name: 'Keywords', exact: true }).click()
    await expect(page.locator('.lp-radar-insight')).toContainText('Keywords · 61/100')
    await testInfo.attach('landing-analysis-selected', {
        body: await page.locator('.lp-analysis-section').screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
    })
    // Exercise long sample content and disclosure states without changing any
    // product data. These states must not push persistent controls off-screen.
    await page
        .locator('.lp-builder-fields details')
        .filter({ has: page.locator('summary', { hasText: 'Personal details' }) })
        .locator('summary')
        .click()
    await page.getByLabel('Name', { exact: true }).fill('W'.repeat(50))
    await page.getByLabel('Role', { exact: true }).fill('W'.repeat(70))
    await page.getByLabel('What did you do?', { exact: true }).fill('W'.repeat(300))
    await page.getByRole('tab', { name: 'LaTeX source', exact: true }).click()
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await page.locator('.lp-faq summary').first().click()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        page.viewportSize()!.width + 1
    )
    await testInfo.attach('landing-long-content', {
        body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
        contentType: 'image/png',
    })
    if (!testInfo.project.metadata.mobile) {
        await page.getByRole('tab', { name: 'Guided builder', exact: true }).click()
        for (const width of [768, 1024, 1101]) {
            await page.setViewportSize({ width, height: 1000 })
            await expectHeroCardsInsideScene()
            for (const view of ['Source', 'PDF']) {
                await page.getByRole('tab', { name: view, exact: true }).click()
                await settle()
                expect(
                    await page.evaluate(() => document.documentElement.scrollWidth)
                ).toBeLessThanOrEqual(width + 1)
                const actionBox = await page.locator('.lp-compile-action').boundingBox()
                expect(actionBox).not.toBeNull()
                expect(actionBox!.x + actionBox!.width).toBeLessThanOrEqual(width + 1)
                if (view === 'Source') {
                    const equation = await page
                        .locator('.lp-latex-preview .lp-equation')
                        .evaluate(element => ({
                            width: element.clientWidth,
                            contentWidth: element.scrollWidth,
                        }))
                    expect(equation.contentWidth).toBeLessThanOrEqual(equation.width + 1)
                    await testInfo.attach(`landing-tablet-${width}-source`, {
                        body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
                        contentType: 'image/png',
                    })
                }
            }
            await testInfo.attach(`landing-tablet-${width}`, {
                body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
                contentType: 'image/png',
            })
        }
        await page.setViewportSize({ width: 320, height: 900 })
        const actionBoxes = await Promise.all(
            (await page.locator('.lp-hero-actions > a:visible').all()).map(action => action.boundingBox())
        )
        expect(actionBoxes).toHaveLength(2)
        expect(actionBoxes.every(Boolean)).toBe(true)
        expect(Math.abs(actionBoxes[0]!.y - actionBoxes[1]!.y)).toBeLessThan(1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(321)
        await testInfo.attach('landing-narrow-mobile', {
            body: await page.screenshot({ fullPage: true, animations: 'disabled' }),
            contentType: 'image/png',
        })
    }
    // Restore the device size after tablet/narrow inspection. Both compositions
    // show the paper illustration; phones also reveal the brand signature.
    await page.setViewportSize(viewport!)
    await page.emulateMedia({ reducedMotion: 'no-preference' })
    const footer = page.locator('.lp-footer')
    await footer.scrollIntoViewIfNeeded()
    await expect(footer).toHaveAttribute('data-inview', 'true')
    const artwork = page.locator('.lp-footer-art img')
    const motionTarget = testInfo.project.metadata.mobile
        ? page.locator('.lp-footer-signature > span')
        : artwork
    // Scrolling an animated element waits for its geometry to become stable,
    // consuming the finite desktop float before the running-state assertion.
    // The static footer is already in view; only the phone signature needs focus.
    if (testInfo.project.metadata.mobile) await motionTarget.scrollIntoViewIfNeeded()
    await expect(motionTarget).toBeVisible()
    await expect(artwork).toBeVisible()
    await expect.poll(() => artwork.evaluate(element =>
        (element as HTMLImageElement).naturalWidth
    )).toBeGreaterThan(0)
    if (testInfo.project.metadata.mobile) {
        await expect.poll(() => motionTarget.evaluate(element =>
            getComputedStyle(element).animationName
        )).toBe('lp-section-enter')
        await expect.poll(() => motionTarget.evaluate(element =>
            element.getAnimations().length
        )).toBeGreaterThan(0)
    } else {
        await expect.poll(() => motionTarget.evaluate(element =>
            element.getAnimations().some(animation => animation.playState === 'running')
        )).toBe(true)
    }
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await expect.poll(() => motionTarget.evaluate(element => element.getAnimations().length)).toBe(0)
    await expect.poll(() => artwork.evaluate(element => element.getAnimations().length)).toBe(0)
    expect(hydrationErrors, 'The landing page must hydrate without attribute drift').toEqual([])
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
    await page.locator('.lp-analysis-section').scrollIntoViewIfNeeded()
    expect((await audioCounts()).created).toBe(0)
    await expect(page.getByRole('button', { name: 'Interface sounds', exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: 'Open navigation menu' }).click()
    const sound = page.getByRole('button', { name: 'Interface sounds', exact: true })
    await expect(sound).toHaveAttribute('aria-pressed', 'false')
    await sound.click()
    await expect(sound).toHaveAttribute('aria-pressed', 'true')
    await expect.poll(async () => (await audioCounts()).created).toBe(1)
    await testInfo.attach('landing-glass-menu', { body: await page.screenshot(), contentType: 'image/png' })
    await page.keyboard.press('Escape')
    const layouts = page.getByRole('group', { name: 'Sample résumé layouts' })
    await layouts.getByRole('button', { name: /Modern/ }).click()
    await expect(layouts.getByRole('button', { name: /Modern/ })).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.lp-document-card[data-slot="center"]')).toHaveAttribute('data-template', 'Modern')
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

test('landing sample controls change their visible state by keyboard and pointer', async ({ page }, testInfo) => {
    test.skip(testInfo.project.metadata.mobile === true, 'Desktop keyboard demo contract')
    await page.goto('/', { waitUntil: 'networkidle' })

    const gallery = page.getByRole('group', { name: 'Sample résumé layouts' })
    const modern = gallery.getByRole('button', { name: /Modern/ })
    const minimal = gallery.getByRole('button', { name: /Minimal/ })
    await modern.focus()
    await page.keyboard.press('Enter')
    await expect(modern).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.lp-gallery-art')).toHaveAttribute('data-layout', 'Modern')
    await minimal.focus()
    await page.keyboard.press('Space')
    await expect(minimal).toHaveAttribute('aria-pressed', 'true')
    await expect(page.locator('.lp-gallery-art')).toHaveAttribute('data-layout', 'Minimal')

    const authoring = page.getByRole('tablist', { name: 'Explore authoring modes' })
    const guided = authoring.getByRole('tab', { name: 'Guided builder' })
    const source = authoring.getByRole('tab', { name: 'LaTeX source' })
    await guided.focus()
    await page.keyboard.press('ArrowRight')
    await expect(source).toBeFocused()
    await expect(source).toHaveAttribute('aria-selected', 'true')
    await expect(page.locator('.lp-builder-workspace')).toHaveAttribute('data-mode', 'source')
    await page.keyboard.press('Home')
    await expect(guided).toBeFocused()
    await expect(guided).toHaveAttribute('aria-selected', 'true')

    const tailoring = page.locator('.lp-tailor-demo')
    const revisedBullet = 'Built accessible Python tools for a cross-functional team.'
    await tailoring.getByRole('button', { name: 'Edit', exact: true }).click()
    await tailoring.getByRole('textbox', { name: 'Edit suggested rewrite' }).fill(revisedBullet)
    await tailoring.getByRole('button', { name: 'Accept', exact: true }).click()
    await expect(tailoring.locator('.lp-matching-experience')).toContainText(revisedBullet)
    await expect(tailoring).toContainText('Sample updated with your approved wording.')
    await tailoring.getByRole('button', { name: 'Keep original' }).click()
    await expect(tailoring.locator('.lp-matching-experience')).toContainText(
        'Built and maintained user-facing products in Python with a focus on performance.'
    )
    await expect(tailoring).toContainText('Original wording kept. You decide what changes.')

    const board = page.locator('.lp-application-demo')
    const manage = board.getByRole('button', { name: 'Manage Senior Software Engineer at Acme' })
    await manage.click()
    await page.getByRole('menuitemradio', { name: 'Applied' }).click()
    await expect(board.locator('.lp-board-column').nth(0)).not.toContainText('Acme')
    await expect(board.locator('.lp-board-column').nth(1)).toContainText('Acme')
    await expect(manage).toBeFocused()
})

test('landing sample tabs align selection and focus for repeated keyboard navigation', async ({ page }, testInfo) => {
    test.skip(testInfo.project.metadata.mobile === true, 'Desktop keyboard demo contract')
    await page.goto('/', { waitUntil: 'networkidle' })

    const neutral = page.getByRole('group', { name: 'Sample résumé layouts' })
        .getByRole('button', { name: /Modern/ })
    const authoring = page.getByRole('tablist', { name: 'Explore authoring modes' })
    const guided = authoring.getByRole('tab', { name: 'Guided builder' })
    const source = authoring.getByRole('tab', { name: 'LaTeX source' })
    const studio = authoring.getByRole('tab', { name: 'Visual studio' })
    const workspace = page.locator('.lp-builder-workspace')

    await expect(guided).toHaveAttribute('aria-selected', 'true')
    await expect(guided).not.toBeFocused()
    await studio.click()
    await expect(studio).toHaveAttribute('aria-selected', 'true')
    await neutral.focus()
    await source.evaluate(button => (button as HTMLButtonElement).click())
    await expect(source).toHaveAttribute('aria-selected', 'true')
    await expect(neutral).toBeFocused()

    await guided.focus()
    for (const { key, tab, mode } of [
        { key: 'Home', tab: guided, mode: 'guided' },
        { key: 'ArrowRight', tab: source, mode: 'source' },
        { key: 'ArrowRight', tab: studio, mode: 'studio' },
        { key: 'ArrowRight', tab: guided, mode: 'guided' },
        { key: 'ArrowLeft', tab: studio, mode: 'studio' },
        { key: 'Home', tab: guided, mode: 'guided' },
        { key: 'Home', tab: guided, mode: 'guided' },
        { key: 'End', tab: studio, mode: 'studio' },
        { key: 'End', tab: studio, mode: 'studio' },
        { key: 'ArrowLeft', tab: source, mode: 'source' },
    ]) {
        await page.keyboard.press(key)
        await expect(tab).toBeFocused()
        await expect(tab).toHaveAttribute('aria-selected', 'true')
        await expect(workspace).toHaveAttribute('data-mode', mode)
        await expect(workspace).toHaveAttribute('aria-labelledby', (await tab.getAttribute('id'))!)
        await expect(tab).toHaveAttribute('aria-controls', (await workspace.getAttribute('id'))!)
    }

    const latexTabs = page.getByRole('tablist', { name: 'Explore the LaTeX sample' })
    const latexSource = latexTabs.getByRole('tab', { name: 'Source' })
    const pdf = latexTabs.getByRole('tab', { name: 'PDF' })
    const latexDemo = page.locator('.lp-latex-demo')
    await expect(latexSource).toHaveAttribute('aria-selected', 'true')
    await expect(latexSource).not.toBeFocused()
    await pdf.click()
    await expect(pdf).toHaveAttribute('aria-selected', 'true')
    await neutral.focus()
    await latexSource.evaluate(button => (button as HTMLButtonElement).click())
    await expect(latexSource).toHaveAttribute('aria-selected', 'true')
    await expect(neutral).toBeFocused()

    await latexSource.focus()
    for (const { key, tab, view } of [
        { key: 'Home', tab: latexSource, view: 'source' },
        { key: 'ArrowRight', tab: pdf, view: 'pdf' },
        { key: 'ArrowRight', tab: latexSource, view: 'source' },
        { key: 'ArrowLeft', tab: pdf, view: 'pdf' },
        { key: 'Home', tab: latexSource, view: 'source' },
        { key: 'Home', tab: latexSource, view: 'source' },
        { key: 'End', tab: pdf, view: 'pdf' },
        { key: 'End', tab: pdf, view: 'pdf' },
        { key: 'ArrowLeft', tab: latexSource, view: 'source' },
    ]) {
        await page.keyboard.press(key)
        await expect(tab).toBeFocused()
        await expect(tab).toHaveAttribute('aria-selected', 'true')
        await expect(latexDemo).toHaveAttribute('data-view', view)
        const panel = latexDemo.getByRole('tabpanel')
        await expect(panel).toHaveAttribute('aria-labelledby', (await tab.getAttribute('id'))!)
        await expect(tab).toHaveAttribute('aria-controls', (await panel.getAttribute('id'))!)
    }
})

test('hero documents stay readable and selectable without WebGL', async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => {
        const original = HTMLCanvasElement.prototype.getContext
        HTMLCanvasElement.prototype.getContext = function (
            this: HTMLCanvasElement,
            type: string,
            options?: unknown
        ) {
            if (['webgl', 'webgl2', 'experimental-webgl'].includes(type)) return null
            return Reflect.apply(original, this, [type, options])
        } as typeof original
    })
    await page.goto('/', { waitUntil: 'networkidle' })
    const gallery = page.locator('.lp-gallery')
    await expect(gallery.locator('img')).toHaveCount(0)
    await expect(gallery.locator('canvas')).toHaveCount(0)
    const controls = gallery.getByRole('group', { name: 'Sample résumé layouts' })
    await controls.getByRole('button', { name: /Classic/ }).focus()
    await page.keyboard.press('ArrowRight')
    await expect(controls.getByRole('button', { name: /Modern/ })).toBeFocused()
    await expect(controls.getByRole('button', { name: /Modern/ })).toHaveAttribute(
        'aria-pressed',
        'true'
    )
    await expect(gallery.locator('[data-template="Modern"]')).toHaveAttribute('data-slot', 'center')
    await page.setViewportSize({ width: 320, height: 900 })
    for (const layout of ['Classic', 'Modern', 'Minimal']) {
        await controls.getByRole('button', { name: new RegExp(layout) }).click()
        const paper = gallery.getByRole('article', { name: `${layout} sample résumé` })
        await expect(paper).toBeVisible()
        await expect(paper.getByRole('heading', { name: 'Alex Morgan' })).toBeVisible()
        await expect(paper.getByRole('heading', { name: 'Skills', exact: true })).toBeVisible()
        await expect.poll(() => paper.evaluate(element => {
            const paperBounds = element.getBoundingClientRect()
            const sceneBounds = element.closest('.lp-document-scene')!.getBoundingClientRect()
            return Math.max(sceneBounds.left - paperBounds.left, paperBounds.right - sceneBounds.right, paperBounds.bottom - sceneBounds.bottom)
        })).toBeLessThanOrEqual(1)
        expect(
            await paper.evaluate(element => element.scrollHeight - element.clientHeight)
        ).toBeLessThanOrEqual(1)
        expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
            321
        )
        await testInfo.attach(`hero-no-webgl-${layout.toLowerCase()}`, {
            body: await gallery.screenshot({ animations: 'disabled', caret: 'hide' }),
            contentType: 'image/png',
        })
    }
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await expect(gallery.locator('.lp-document-scene')).toHaveAttribute(
        'data-reduced-motion',
        'true'
    )
    expect(errors).toEqual([])
})

test('mobile landing presents focused demos in both themes and preserves edits', async ({
    page,
}, testInfo) => {
    test.skip(testInfo.project.metadata.mobile !== true, 'Phone composition contract')
    await page.goto('/', { waitUntil: 'networkidle' })
    for (const width of [320, 390, 430]) {
        await page.setViewportSize({ width, height: 844 })
        for (const theme of ['light', 'dark']) {
            if ((await page.locator('html').getAttribute('data-mode')) !== theme) {
                await page.getByRole('button', { name: 'Toggle light or dark mode' }).click()
            }
            await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
            const brand = (await page.locator('.lp-header > a').boundingBox())!
            const utilities = (await page.locator('.lp-header-actions').boundingBox())!
            expect(Math.abs(brand.y + brand.height / 2 - utilities.y - utilities.height / 2)).toBeLessThan(1)
            expect(brand.height).toBeGreaterThanOrEqual(44)
            for (const control of await page.locator('.lp-header-control:visible').all()) {
                expect((await control.boundingBox())!.height).toBeGreaterThanOrEqual(44)
            }
            const gallery = page.locator('.lp-gallery')
            await expect(gallery.locator('[data-slot="center"] figcaption')).toBeHidden()
            expect((await gallery.boundingBox())!.height).toBeLessThan(550)
            const actions = page.locator('.lp-hero-actions > a:visible')
            await expect(actions).toHaveCount(2)
            for (const action of await actions.all()) {
                expect((await action.boundingBox())!.height).toBeGreaterThanOrEqual(44)
            }
            const undersized = await page.locator('.lp-page button, .lp-page a, .lp-page input, .lp-page select, .lp-page summary').evaluateAll(elements =>
                elements.filter(element => {
                    const box = element.getBoundingClientRect()
                    return box.width > 0 && box.height > 0 && box.height < 43.9
                }).map(element => element.getAttribute('aria-label') || element.textContent?.trim())
            )
            expect(undersized).toEqual([])
            expect(
                await page.evaluate(() => document.documentElement.scrollWidth)
            ).toBeLessThanOrEqual(width + 1)
            await page.evaluate(() => scrollTo(0, 0))
            await testInfo.attach(`mobile-${width}-${theme}-first-screen`, {
                body: await page.screenshot({ animations: 'disabled' }),
                contentType: 'image/png',
            })
        }
    }
    await page.setViewportSize({ width: 390, height: 844 })
    const gallery = page.locator('.lp-gallery')
    await gallery.getByRole('button', { name: 'Read the full sample' }).click()
    await expect(
        gallery
            .locator('[data-slot="center"]')
            .getByRole('heading', { name: 'Profile', exact: true })
    ).toBeVisible()
    await expect(
        gallery.locator('[data-slot="center"]').getByText('Northwind', { exact: true })
    ).toBeVisible()
    await gallery.getByRole('button', { name: 'Show compact preview' }).click()
    await expect(
        gallery
            .locator('[data-slot="center"]')
            .getByRole('heading', { name: 'Profile', exact: true })
    ).toBeHidden()
    const builder = page.locator('.lp-builder-demo')
    await expect(builder.locator('.lp-builder-preview')).toBeHidden()
    await builder
        .getByLabel('What did you do?', { exact: true })
        .fill('Built accessible document tools with the design team.')
    await builder.getByRole('button', { name: 'Preview résumé', exact: true }).click()
    await expect(builder.locator('.lp-builder-fields')).toBeHidden()
    await expect(
        builder.getByRole('article', { name: 'Live sample résumé preview' })
    ).toContainText('Built accessible document tools with the design team.')
    await testInfo.attach('mobile-builder-preview', {
        body: await builder.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
    })
    await builder.getByRole('button', { name: 'Edit content', exact: true }).click()
    await expect(builder.getByLabel('What did you do?', { exact: true })).toHaveValue(
        'Built accessible document tools with the design team.'
    )
    await builder.getByRole('tab', { name: 'LaTeX source', exact: true }).click()
    await expect(builder.locator('.lp-builder-fields')).toContainText(
        'Built accessible document tools'
    )
    const analysis = page.locator('.lp-analysis-demo')
    await analysis.getByRole('button', { name: 'Keyword report', exact: true }).click()
    await expect(analysis.locator('.lp-radar-panel')).toBeHidden()
    await analysis.getByRole('button', { name: /^Present/ }).click()
    await expect(analysis.locator('.lp-keyword-result')).toContainText('Python')
    await testInfo.attach('mobile-keyword-report', {
        body: await analysis.screenshot({ animations: 'disabled' }),
        contentType: 'image/png',
    })
    const board = page.getByRole('region', { name: 'Sample application stages' })
    expect(await board.evaluate(n => n.scrollWidth)).toBeGreaterThan(
        (await board.boundingBox())!.width
    )
    await page
        .getByRole('button', { name: 'Manage Senior Software Engineer at Notion', exact: true })
        .click()
    await expect(page.getByRole('menu')).toBeVisible()
    await page.keyboard.press('Escape')
    const tailoring = page.locator('.lp-tailor-demo')
    await tailoring.getByRole('button', { name: 'Edit', exact: true }).click()
    const rewrite = tailoring.getByRole('textbox', { name: 'Edit suggested rewrite' })
    expect(await rewrite.evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16)
    await rewrite.fill('Built clear, accessible document workflows.')
    await tailoring.getByRole('button', { name: 'Accept', exact: true }).click()
    await expect(tailoring.locator('.lp-matching-experience')).toContainText('Built clear, accessible document workflows.')
    await page.getByRole('tab', { name: 'PDF', exact: true }).click()
    await expect(
        page.locator('.lp-latex-source').getByRole('heading', { name: 'A Simple Equation' })
    ).toBeVisible()
})

test('landing keeps a public entry point when capabilities are unavailable', async ({ page }) => {
    const { backendOrigin } = qualityOrigins()
    await page.route(
        url => url.origin === backendOrigin && url.pathname === '/config/entitlements',
        route => fulfillQualityJson(route, { features: {} })
    )
    await page.goto('/', { waitUntil: 'networkidle' })
    const hero = page.locator('.lp-hero-actions')
    await expect(hero.getByRole('link', { name: 'Build my résumé' })).toHaveCount(0)
    await expect(hero.getByRole('link', { name: 'Explore Latexy' })).toBeVisible()
    await expect(hero.getByRole('link', { name: 'Explore Latexy' })).toHaveAttribute(
        'href',
        '/platform'
    )
    await expect(hero.getByRole('link', { name: 'See it in action' })).toBeVisible()
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
