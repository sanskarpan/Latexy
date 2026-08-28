import { expect, test, type Page } from '@playwright/test'

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

async function installPublicPageMocks(page: Page) {
    const jsonHeaders = {
        'access-control-allow-origin': '*',
        'content-type': 'application/json',
    }
    await page.route('**/api/auth/get-session', route =>
        route.fulfill({ status: 200, headers: jsonHeaders, body: 'null' })
    )
    await page.route('**/config/feature-flags', route =>
        route.fulfill({ status: 200, headers: jsonHeaders, body: '{}' })
    )
    await page.route('**/tenants/current-context', route =>
        route.fulfill({ status: 200, headers: jsonHeaders, body: '{"tenant":null}' })
    )
    await page.route('http://localhost:8030/templates/**', route =>
        route.fulfill({ status: 200, headers: jsonHeaders, body: '[]' })
    )
    await page.route('http://localhost:8030/public/trial-status?*', route =>
        route.fulfill({
            status: 200,
            headers: jsonHeaders,
            body: JSON.stringify({
                usageCount: 0,
                remainingUses: 3,
                blocked: false,
                canUse: true,
                lastUsed: null,
                trialLimit: 3,
            }),
        })
    )
    await page.route('**/ws/**', route => route.abort())
}

test.beforeEach(async ({ page }) => {
    await installPublicPageMocks(page)
})

test('public routes render without runtime errors in every engine', async ({ context }) => {
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
            await routePage.close()
        }
    }

    expect(runtimeErrors).toEqual([])
})

test('public routes expose named controls and valid document structure', async ({ context }) => {
    for (const route of PUBLIC_ROUTES) {
        const routePage = await context.newPage()
        await installPublicPageMocks(routePage)
        await routePage.goto(route, { waitUntil: 'networkidle' })

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
        await routePage.close()
    }
})

test('skip navigation and reduced-motion preferences are honored', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await page.goto('/', { waitUntil: 'domcontentloaded' })

    await page.keyboard.press('Tab')
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
