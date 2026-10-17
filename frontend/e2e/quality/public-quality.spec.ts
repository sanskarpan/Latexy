Warning: truncated output (original token count: 16908)
Total output lines: 1281

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

type HeadingCapture = { x: number; y: number; width: number; height: number; color: number[] }

async function expectPaintedSampleHeading(page: Page, screenshot: Buffer, heading: HeadingCapture) {
    const viewport = page.viewportSize()!
    expect(heading.y).toBeGreaterThanOrEqual(0)
    expect(heading.y + heading.height).toBeLessThanOrEqual(viewport.height)
    // DOM visibility alone missed a blank-paper compositor regression after
    // switching theme. Inspect the heading's actual pixels in the page capture.
    const paint = await page.evaluate(async ({ encoded, box, width }) => {
        const image = new Image()
        image.src = `data:image/png;base64,${encoded}`
        await image.decode()
        const scale = image.width / width
        const canvas = document.createElement('canvas')
        canvas.width = Math.ceil(box.width * scale)
        canvas.height = Math.ceil(box.height * scale)
        const context = canvas.getContext('2d')!
        context.drawImage(image, box.x * scale, box.y * scale, box.width * scale, box.height * scale, 0, 0, canvas.width, canvas.height)
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
        let ink = 0
        let paper = 0
        for (let index = 0; index < pixels.length; index += 4) {
            if (pixels[index + 3] < 200) continue
            if (box.color.every((channel, offset) => Math.abs(pixels[index + offset] - channel) < 35)) ink += 1
            if (pixels[index] > 225 && pixels[index + 1] > 225 && pixels[index + 2] > 210) paper += 1
        }
        return { ink, paperFraction: paper / (pixels.length / 4) }
    }, { encoded: screenshot.toString('base64'), box: heading, width: viewport.width })
    expect(paint.paperFraction, 'The inspected heading region must be on the light paper').toBeGreaterThan(0.55)
    expect(paint.ink, 'The selected sample heading must paint its actual text color').toBeGreaterThan(100)
    return paint
}

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
            await expect(routePage.getByRole('link', { name: 'Try the r�sum� builder ' })).toHaveAttribute('href', '/try?mode=visual')
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

test('updates copy stays visible without JavaScript for reduced-motion users at desktop and mobile widths', async ({ browser, baseURL }, testInfo) => {
    const context = await browser.newContext({
        baseURL,
        viewport: { width: 1280, height: 900 },
        reducedMotion: 'reduce',
        javaScriptEnabled: false,
        serviceWorkers: 'block',
        extraHTTPHeaders: { 'accept-language': 'hi-IN,hi;q=0.9,en;q=0.8' },
    })

    try {
        expect(await context.cookies()).toEqual([])
        const page = await context.newPage()
        await installPublicPageMocks(page)
        const response = await page.goto('/updates', { waitUntil: 'networkidle' })
        expect(response?.status()).toBe(200)
        expect(await response?.text()).toContain('Shipping log and')
        await expect(page.locator('html')).toHaveAttribute('lang', 'hi')

        const heading = page.locator('main h1')
        const article = page.locator('main article').first()
        await expect(heading).toContainText(/Shipping log and.*platform progress/)
        await expect(heading).toBeVisible()
        await expect(article).toBeVisible()

        for (const { name, width, height } of [
            { name: 'desktop-1280x900', width: 1280, height: 900 },
            { name: 'mobile-390x844', width: 390, height: 844 },
        ]) {
            await page.setViewportSize({ width, height })
            const motionStyles = await page.evaluate(() => {
                const main = document.querySelector('main')
                const title = main?.querySelector('h1')
                const firstArticle = main?.querySelector('article')
                const item = firstArticle?.parentElement
                const style = (element: Element | null | undefined) => {
                    if (!element) return null
                    const computed = getComputedStyle(element)
                    return { opacity: computed.opacity, transform: computed.transform }
                }

                return {
                    reveal: style(title?.parentElement),
                    stagger: style(item?.parentElement),
                    item: style(item),
                    viewportWidth: document.documentElement.scrollWidth,
                }
            })

            expect(motionStyles.reveal, name).toEqual({ opacity: '1', transform: 'none' })
            expect(motionStyles.stagger, name).toEqual({ opacity: '1', transform: 'none' })
            expect(motionStyles.item, name).toEqual({ opacity: '1', transform: 'none' })
            expect(motionStyles.viewportWidth, name).toBeLessThanOrEqual(width + 1)

            const screenshotPath = testInfo.outputPath(`updates-reduced-motion-${name}.png`)
            await page.screenshot({ path: screenshotPath, fullPage: true })
            await testInfo.attach(`updates-reduced-motion-${name}`, {
                path: screenshotPath,
                contentType: 'image/png',
            })
        }
    } finally {
        await context.close()
    }
})

test('updates motion hydrates cleanly and stays visible across preference changes and navigation', async ({ page }, testInfo) => {
    const consoleErrors: string[] = []
    const hydrationWarnings: string[] = []
    const pageErrors: string[] = []
    const hydrationPattern = /hydration|hydrated|server rendered HTML|did not match/i

    page.on('console', message => {
        const text = message.text()
        if (message.type() === 'error') consoleErrors.push(text)
        if (hydrationPattern.test(text)) hydrationWarnings.push(`${message.type()}: ${text}`)
    })
    page.on('pageerror', error => pageErrors.push(error.message))

    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.setViewportSize({ width: 1280, height: 900 })

    // Confirm the server emits the same motion-wrapper shape used for the
    // first hydration pass, before the browser preference snapshot is applied.
    const serverResponse = await page.request.get('/updates')
    expect(serverResponse.status()).toBe(200)
    expect(await serverResponse.text()).toContain('data-marketing-motion')

    const readMotionState = () => page.evaluate(() => {
        const heading = document.querySelector('main h1')
        const article = document.querySelector('main article')
        const measure = (element: Element | null) => {
            if (!element) return null
            const style = getComputedStyle(element)
            const rect = element.getBoundingClientRect()
            return { opacity: style.opacity, transform: style.transf…6908 tokens truncated…    await expect(neutral).toBeFocused()

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
    const controls = gallery.getByRole('group', { name: 'Sample r�sum� layouts' })
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
        const paper = gallery.getByRole('article', { name: `${layout} sample r�sum�` })
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

test('landing workbench updates a real r�sum� sample and resets on a new visit', async ({ page }) => {
    await page.goto('/', { waitUntil: 'networkidle' })
    const gallery = page.locator('.lp-gallery')
    await gallery.getByRole('textbox', { name: 'Sample name' }).fill('Jordan Lee')
    await gallery.getByRole('textbox', { name: 'Sample role' }).fill('Product Designer')
    const selected = gallery.locator('.lp-document-card[data-slot="center"]')
    await expect(selected.getByRole('heading', { name: 'Jordan Lee' })).toBeVisible()
    await expect(selected).toContainText('Product Designer')
    await gallery.getByRole('group', { name: 'Sample r�sum� layouts' })
        .getByRole('button', { name: /Modern/ }).click()
    await expect(gallery.locator('[data-template="Modern"]')).toHaveAttribute('data-slot', 'center')
    await expect(gallery.locator('.lp-document-card[data-slot="center"]'))
        .toContainText('Jordan Lee')
    await gallery.getByRole('textbox', { name: 'Sample name' }).fill('W'.repeat(38))
    await gallery.getByRole('textbox', { name: 'Sample role' }).fill('W'.repeat(48))
    const paper = gallery.locator('.lp-document-card[data-slot="center"] .lp-hero-paper')
    await expect.poll(() => paper.evaluate(element => {
        const bounds = element.getBoundingClientRect()
        const scene = element.closest('.lp-document-scene')!.getBoundingClientRect()
        return Math.max(scene.left - bounds.left, bounds.right - scene.right, bounds.bottom - scene.bottom)
    })).toBeLessThanOrEqual(1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth))
        .toBeLessThanOrEqual(page.viewportSize()!.width + 1)
    await page.reload({ waitUntil: 'networkidle' })
    await expect(gallery.getByRole('textbox', { name: 'Sample name' })).toHaveValue('Alex Morgan')
    await expect(gallery.getByRole('textbox', { name: 'Sample role' }))
        .toHaveValue('Senior Software Engineer')
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
            for (const input of await gallery.getByRole('textbox').all()) {
                expect(await input.evaluate(element => Number.parseFloat(getComputedStyle(element).fontSize)))
                    .toBeGreaterThanOrEqual(16)
            }
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
            await page.evaluate(() => {
                scrollTo({ top: 0, left: 0, behavior: 'instant' })
                return new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
            })
            // Record the text region before capture; a later protocol query can
            // observe different geometry after screenshot scroll restoration.
            const heading = width === 390 ? await page.locator('.lp-document-card[data-slot="center"] .lp-hero-paper h2').evaluate(element => {
                const range = document.createRange()
                range.selectNodeContents(element)
                const { x, y, width, height } = range.getBoundingClientRect()
                const color = getComputedStyle(element).color.match(/\d+/g)!.slice(0, 3).map(Number)
                return { x, y, width, height, color }
            }) : null
            const firstScreen = await page.screenshot({ animations: 'disabled' })
            if (heading) {
                const paint = await expectPaintedSampleHeading(page, firstScreen, heading)
                await testInfo.attach(`mobile-${width}-${theme}-heading-paint`, {
                    body: Buffer.from(JSON.stringify({ heading, paint })),
                    contentType: 'application/json',
                })
            }
            await testInfo.attach(`mobile-${width}-${theme}-first-screen`, {
                body: firstScreen,
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
    await builder.getByRole('button', { name: 'Preview r�sum�', exact: true }).click()
    await expect(builder.locator('.lp-builder-fields')).toBeHidden()
    await expect(
        builder.getByRole('article', { name: 'Live sample r�sum� preview' })
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
    await expect(hero.getByRole('link', { name: 'Try the studio' })).toHaveCount(0)
    await expect(hero.getByRole('link', { name: 'Explore Latexy' })).toBeVisible()
    await expect(hero.getByRole('link', { name: 'Explore Latexy' })).toHaveAttribute(
        'href',
        '/platform'
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
    await expect(page.getByRole('heading', { level: 1, name: 'R�sum� Studio' })).toBeAttached()
})

