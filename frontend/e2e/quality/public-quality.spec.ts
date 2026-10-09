import { expect, test, type Page } from '@playwright/test'
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
        fulfillQualityJson(route, { features: QUALITY_FEATURES })
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
            await expect(routePage.getByRole('heading', { level: 2, name: 'Available plans' })).toBeVisible()
            await expect(routePage.getByRole('heading', { level: 3, name: 'Free', exact: true })).toBeVisible()
            await expect(routePage.getByRole('button', { name: 'Select Plan', exact: true })).toBeEnabled()
            await expect(routePage.getByRole('button', { name: 'Purchases disabled in this test', exact: true })).toBeDisabled()
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
    await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' })
    await page.goto('/', { waitUntil: 'networkidle' })
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const viewport = page.viewportSize()
    const mainBox = await page.locator('#main-content').boundingBox()
    expect(viewport).not.toBeNull()
    expect(mainBox).not.toBeNull()
    expect(mainBox!.width).toBeLessThanOrEqual(viewport!.width + 1)
    expect(mainBox!.height).toBeGreaterThan(300)

    const screenshot = await page.screenshot({
        fullPage: true,
        animations: 'disabled',
        caret: 'hide',
    })
    expect(screenshot.byteLength).toBeGreaterThan(20_000)
    await testInfo.attach('landing-page', { body: screenshot, contentType: 'image/png' })
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
    await expect(page.getByRole('button', { name: /Recompile/ })).toBeVisible()
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
        fulfillQualityJson(route, { features: { ...QUALITY_FEATURES, b04: false } })
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
        fulfillQualityJson(route, { features: { ...QUALITY_FEATURES, b06: false } })
    )
    await page.goto('/try', { waitUntil: 'networkidle' })
    await expect(page.getByRole('button', { name: /Recompile/ })).toBeVisible()
    const tools = page.getByRole('button', { name: 'Tools', exact: true })
    if (await tools.isVisible()) await tools.click()
    await expect(page.getByRole('button', { name: /Import file/ })).toHaveCount(0)
    await expect(page.getByRole('heading', { level: 1, name: 'Résumé Studio' })).toBeAttached()
})
