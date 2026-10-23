import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test, type Page } from './quality-test'
import { fulfillQualityJson, QUALITY_FEATURES, qualityOrigins } from './mock-api'

test.use({ reducedMotion: 'reduce' })

async function mockPublicChrome(
    page: Page,
    state: 'enabled' | 'unavailable' | 'error' = 'enabled'
) {
    const { appOrigin, backendOrigin } = qualityOrigins()
    await page.route(
        url => url.origin === backendOrigin,
        route => {
            const pathname = new URL(route.request().url()).pathname
            if (pathname === '/config/entitlements') {
                return fulfillQualityJson(
                    route,
                    {
                        features: {
                            ...QUALITY_FEATURES,
                            a09: state === 'enabled',
                            c01: state === 'enabled',
                            b10: true,
                        },
                    },
                    state === 'error' ? 503 : 200
                )
            }
            return fulfillQualityJson(
                route,
                pathname === '/tenants/resolve-host'
                    ? { tenant: null }
                    : pathname === '/portfolio/resolve-domain'
                      ? { profile: null }
                      : {}
            )
        }
    )
    await page.route(
        url => url.origin === appOrigin && url.pathname.startsWith('/api/auth/'),
        route => fulfillQualityJson(route, null)
    )
}

async function expectFontsLoaded(page: Page) {
    // In Firefox's no-JS context, document.fonts.ready can remain pending.
    // Poll the same font-loading state from the test process so SSR coverage
    // still waits for fonts without depending on a page-side Promise callback.
    await expect.poll(() => page.evaluate(() => document.fonts.status)).toBe('loaded')
}

async function expectHeaderFits(page: Page, width: number) {
    const header = page.locator('header')
    await expect(header).toBeVisible()
    await expectFontsLoaded(page)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
        width
    )
    const sampleBounds = () => header
        .locator('a:visible, button:visible, select:visible')
        .evaluateAll(elements => {
            const bounds = []
            for (const element of elements) {
                const owner = element.closest('header')
                if (!element.isConnected || !owner?.isConnected) return null
                const { left, right, top, bottom, width, height } = element.getBoundingClientRect()
                const headerBottom = owner.getBoundingClientRect().bottom
                bounds.push({
                    left,
                    right,
                    top,
                    bottom,
                    width,
                    height,
                    headerBottom,
                    tag: element.tagName,
                })
            }
            return bounds
        })
    let bounds: NonNullable<Awaited<ReturnType<typeof sampleBounds>>> = []
    // A closing AnimatePresence menu can detach between the locator query and
    // evaluation. Resample the entire collection; never discard a control or
    // retry a failed geometry assertion below.
    await expect.poll(async () => {
        const sample = await sampleBounds()
        if (!sample?.length) return false
        bounds = sample
        return true
    }, {
        timeout: 5_000,
        message: 'Header controls must form a complete, connected, nonempty sample',
    }).toBe(true)
    expect(bounds.length).toBeGreaterThan(0)
    for (const box of bounds) {
        expect(box.left).toBeGreaterThanOrEqual(0)
        expect(box.right).toBeLessThanOrEqual(width)
        expect(box.top).toBeGreaterThanOrEqual(0)
        expect(box.bottom).toBeLessThanOrEqual(box.headerBottom)
        if (box.tag !== 'A') {
            // Preserve targets rather than shrinking controls to conceal overflow.
            expect(box.width).toBeGreaterThanOrEqual(24)
            expect(box.height).toBeGreaterThanOrEqual(24)
        }
    }
}

async function screenshot(page: Page, name: string, selector?: string) {
    const directory = process.env.RESPONSIVE_CHROME_SCREENSHOT_DIR
    if (!directory) return
    await mkdir(directory, { recursive: true })
    const options = { path: path.join(directory, `${name}.png`), animations: 'disabled' as const }
    if (selector) await page.locator(selector).screenshot(options)
    else await page.screenshot(options)
}

for (const javaScriptEnabled of [false, true]) {
    test.describe(javaScriptEnabled ? 'hydrated header' : 'server-rendered header', () => {
        test.use({ javaScriptEnabled, reducedMotion: 'reduce' })
        for (const width of [320, 375, 640, 767, 768, 1023, 1024, 1440]) {
            test(`all controls remain within the ${width}px viewport`, async ({ page }) => {
                await mockPublicChrome(page)
                await page.setViewportSize({ width, height: 1000 })
                await page.goto('/updates', { waitUntil: 'load' })
                if (javaScriptEnabled) {
                    await expect(
                        page
                            .locator('header')
                            .getByRole('button', { name: 'Toggle light or dark mode' })
                            .filter({ visible: true })
                    ).toBeEnabled()
                }
                await expectHeaderFits(page, width)
                await expect(page.locator('header select:visible option')).toHaveText([
                    'English',
                    'हिन्दी',
                    'मराठी',
                    'తెలుగు',
                    'ਪੰਜਾਬੀ',
                    'বাংলা',
                ])
                if (width < 1024)
                    await expect(
                        page.getByRole('button', { name: 'Open navigation menu' })
                    ).toBeVisible()
                await screenshot(
                    page,
                    `${width}-updates-${javaScriptEnabled ? 'hydrated' : 'nojs'}`
                )
            })
        }
    })
}

test('320px header preserves locale, theme, contrast and repeated menu dismissal', async ({
    page,
}) => {
    await mockPublicChrome(page)
    await page.setViewportSize({ width: 320, height: 1000 })
    await page.goto('/updates')
    const header = page.locator('header')
    const mode = header
        .getByRole('button', { name: 'Toggle light or dark mode' })
        .filter({ visible: true })
    const contrast = header
        .getByRole('button', { name: /high contrast mode/ })
        .filter({ visible: true })
    await expect(mode).toBeEnabled()
    const locale = header.locator('select:visible')
    for (const code of ['hi', 'mr', 'te', 'pa', 'bn', 'en']) {
        await locale.selectOption(code)
        await expect(page.locator('html')).toHaveAttribute('lang', code)
        const menu = header.locator('button[aria-expanded]:visible')
        await menu.click()
        await expect(menu).toHaveAttribute('aria-expanded', 'true')
        await expectHeaderFits(page, 320)
        await menu.click()
        await expect(menu).toHaveAttribute('aria-expanded', 'false')
        await expectHeaderFits(page, 320)
    }
    const menu = header.getByRole('button', { name: 'Open navigation menu' })
    await menu.click()
    await page.keyboard.press('Escape')
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
    await expect(menu).toBeFocused()
    for (const theme of ['dark', 'light']) {
        if ((await page.locator('html').getAttribute('data-mode')) !== theme) await mode.click()
        await expect(page.locator('html')).toHaveAttribute('data-mode', theme)
        await contrast.click()
        await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
        await expectHeaderFits(page, 320)
        await screenshot(page, `320-updates-${theme}-high`)
        await contrast.click()
        await expect(page.locator('html')).toHaveAttribute('data-contrast', 'normal')
    }
})

for (const state of ['enabled', 'unavailable', 'error', 'loading'] as const) {
    for (const mode of ['light', 'dark']) {
        test.describe(`footer ${state} ${mode}`, () => {
            test.use({ javaScriptEnabled: state !== 'loading', reducedMotion: 'reduce' })
            for (const width of [320, 1440]) {
                test(`primary status or action is separated from examples at ${width}px`, async ({
                    page,
                    context,
                }) => {
                    await context.addCookies([
                        { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                    ])
                    await mockPublicChrome(page, state === 'loading' ? 'enabled' : state)
                    await page.setViewportSize({ width, height: 1000 })
                    await page.goto('/', { waitUntil: 'load' })
                    const primary = page.locator(
                        `.lp-footer-message [data-marketing-${state === 'enabled' ? 'action' : 'status'}]`
                    )
                    if (state === 'unavailable')
                        await expect(primary).toContainText(
                            'Studio editing is currently unavailable.'
                        )
                    if (state === 'error')
                        await expect(primary).toContainText(
                            'Studio availability could not be verified.'
                        )
                    if (state === 'loading')
                        await expect(primary).toContainText('Checking studio availability')
                    await expect(primary).toBeVisible()
                    const secondary = page.locator('.ts-closing-secondary')
                    await expect(secondary).toHaveAttribute('href', '/#resume-feedback')
                    await expectFontsLoaded(page)
                    const first = (await primary.boundingBox())!
                    const second = (await secondary.boundingBox())!
                    const sameRow =
                        second.y < first.y + first.height && first.y < second.y + second.height
                    const gap = sameRow
                        ? second.x - (first.x + first.width)
                        : second.y - (first.y + first.height)
                    expect(gap).toBeGreaterThanOrEqual(width === 320 ? 11 : 12)
                    expect(second.height).toBeGreaterThanOrEqual(44)
                    expect(
                        await page.evaluate(() => document.documentElement.scrollWidth)
                    ).toBeLessThanOrEqual(width)
                    await screenshot(page, `${width}-footer-${state}-${mode}`, '.lp-footer')
                })
            }
        })
    }
}

for (const authenticated of [false, true]) {
    test(`320px short-screen ${authenticated ? 'account' : 'guest'} navigation keeps its end and close control reachable`, async ({
        page,
    }) => {
        await mockPublicChrome(page)
        if (authenticated) {
            await page.route('**/api/auth/get-session', route =>
                fulfillQualityJson(route, {
                    user: { id: 'header-owner', name: 'Header Owner', email: 'header@example.com' },
                    session: {
                        id: 'header-session',
                        userId: 'header-owner',
                        token: 'header-fixture',
                    },
                })
            )
        }
        await page.setViewportSize({ width: 320, height: 568 })
        await page.goto('/updates')
        await expect(
            page
                .locator('header')
                .getByRole('button', { name: 'Toggle light or dark mode' })
                .filter({ visible: true })
        ).toBeEnabled()
        const menu = page.locator('header button[aria-expanded]:visible')
        await menu.click()
        const last = authenticated
            ? page.locator('header').getByRole('button', { name: 'Sign Out', exact: true })
            : page.locator('header').getByRole('link', { name: 'Try Free', exact: true })
        await expect(last).toBeVisible()
        await last.scrollIntoViewIfNeeded()
        const end = (await last.boundingBox())!
        expect(end.y).toBeGreaterThanOrEqual(0)
        expect(end.y + end.height).toBeLessThanOrEqual(568)
        const close = (await menu.boundingBox())!
        expect(close.y).toBeGreaterThanOrEqual(0)
        expect(close.y + close.height).toBeLessThanOrEqual(568)
        await screenshot(page, `320-short-menu-${authenticated ? 'account' : 'guest'}`)
        await menu.click()
        await expect(menu).toHaveAttribute('aria-expanded', 'false')
        await expectHeaderFits(page, 320)
    })
}
