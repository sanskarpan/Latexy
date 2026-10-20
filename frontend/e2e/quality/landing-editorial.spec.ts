import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test } from './quality-test'
import { fulfillQualityJson, QUALITY_FEATURES, qualityOrigins } from './mock-api'

const artifacts = process.env.LANDING_SCREENSHOT_DIR
const widths = [320, 375, 390, 430, 768, 1100, 1101, 1180, 1440]
const contribution = 'Designed accessible application journeys with research and engineering. '
    .repeat(4)
    .slice(0, 240)

test.beforeEach(async ({ page }) => {
    const { appOrigin, backendOrigin } = qualityOrigins()
    await page.route(
        url => url.origin === backendOrigin,
        route => {
            const pathname = new URL(route.request().url()).pathname
            return fulfillQualityJson(
                route,
                pathname === '/config/entitlements'
                    ? { features: { ...QUALITY_FEATURES, b10: true } }
                    : pathname === '/tenants/resolve-host'
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
})

for (const mode of ['dark', 'light']) {
    for (const contrast of ['normal', 'high']) {
        for (const width of widths) {
            test(`editorial ${mode} ${contrast} ${width}: tabs, long copy, errors, navigation and preview`, async ({
                page,
                context,
            }) => {
                await page.setViewportSize({ width, height: 960 })
                await context.addCookies([
                    { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                    { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
                ])
                await page.goto('/', { waitUntil: 'networkidle' })
                await page.evaluate(() => document.fonts.ready)
                await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' })
                await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
                await expect(page.locator('html')).toHaveAttribute('data-contrast', contrast)
                const desk = page.getByTestId('review-desk')
                await expect(desk).toBeVisible()
                await expect(page.locator('.rd-hero [data-marketing-action]')).toHaveAttribute(
                    'href',
                    '/try?mode=visual'
                )
                const prefix = `${mode}-${contrast}-${width}`
                async function capture(name: string, fullPage = false) {
                    if (!artifacts) return
                    await mkdir(artifacts, { recursive: true })
                    if (fullPage)
                        await page.screenshot({
                            path: path.join(artifacts, `${prefix}-${name}.png`),
                            fullPage: true,
                            animations: 'disabled',
                        })
                    else
                        await page.locator('.rd-hero').screenshot({
                            path: path.join(artifacts, `${prefix}-${name}.png`),
                            animations: 'disabled',
                        })
                }
                const assertFlow = async () => {
                    const geometry = await desk.evaluate(element => {
                        const paper = element.querySelector('.rd-paper')!.getBoundingClientRect()
                        const note = element
                            .querySelector('.rd-annotation')!
                            .getBoundingClientRect()
                        const controls = element.querySelector('.rd-stages')!
                        return {
                            separated:
                                note.top >= paper.bottom + 12 || note.left >= paper.right + 12,
                            paperWidth: paper.width,
                            position: getComputedStyle(controls).position,
                            overflow: document.documentElement.scrollWidth > innerWidth + 1,
                        }
                    })
                    expect(geometry.separated).toBe(true)
                    expect(geometry.paperWidth).toBeGreaterThan(235)
                    expect(geometry.position).toBe('static')
                    expect(geometry.overflow).toBe(false)
                }
                await capture('page', true)
                for (const tab of ['Review', 'Write', 'Tailor', 'Export']) {
                    await desk.getByRole('tab', { name: tab, exact: true }).click()
                    await expect(desk.getByRole('tab', { name: tab, exact: true })).toHaveAttribute(
                        'aria-selected',
                        'true'
                    )
                    await expect(desk.getByRole('tabpanel')).toBeVisible()
                    await assertFlow()
                    await capture(tab.toLowerCase())
                }
                const radio = desk.getByLabel('Modern', { exact: true })
                await radio.check()
                const radioBox = await radio.boundingBox()
                expect(radioBox!.width).toBeLessThanOrEqual(20)
                expect(radioBox!.height).toBeLessThanOrEqual(20)
                await expect(desk.locator('.rd-paper')).toHaveAttribute('data-layout', 'modern')
                await desk.getByRole('tab', { name: 'Write', exact: true }).click()
                await desk.getByLabel('Your role', { exact: true }).fill('W'.repeat(60))
                await desk.getByLabel('One contribution', { exact: true }).fill(contribution)
                await desk.getByRole('button', { name: 'Update sample' }).click()
                await expect(desk.locator('.rd-highlight')).toHaveText(contribution.trim())
                await expect(desk.getByRole('status')).toContainText('Your wording is now')
                await assertFlow()
                await capture('long-text')
                await desk.getByLabel('Your role', { exact: true }).fill(' ')
                await desk.getByRole('button', { name: 'Update sample' }).click()
                await expect(desk.getByRole('alert')).toBeVisible()
                const errorContrast = await desk.getByRole('alert').evaluate(element => {
                    const style = getComputedStyle(element)
                    const luminance = (color: string) => {
                        const rgb = color
                            .match(/[\d.]+/g)!
                            .slice(0, 3)
                            .map(Number)
                            .map(v => {
                                const channel = v / 255
                                return channel <= 0.04045
                                    ? channel / 12.92
                                    : ((channel + 0.055) / 1.055) ** 2.4
                            })
                        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
                    }
                    const foreground = luminance(style.color)
                    const background = luminance(style.backgroundColor)
                    return (
                        (Math.max(foreground, background) + 0.05) /
                        (Math.min(foreground, background) + 0.05)
                    )
                })
                expect(errorContrast).toBeGreaterThanOrEqual(contrast === 'high' ? 7 : 4.5)

                await expect(desk.locator('.rd-sample-status')).toHaveText('')
                await expect(desk.getByLabel('Your role', { exact: true })).toHaveAttribute(
                    'aria-invalid',
                    'true'
                )
                await capture('error')
                await desk.getByRole('tab', { name: 'Review', exact: true }).click()
                await expect(
                    desk.getByRole('button', { name: 'Use suggestion', exact: true })
                ).toBeDisabled()
                await expect(desk.locator('.rd-highlight')).toHaveText(contribution.trim())
                const menu = page.locator('.lp-menu-trigger')
                await menu.click()
                await expect(menu).toHaveAttribute('aria-expanded', 'true')
                await expect(page.locator('#landing-navigation')).toBeVisible()
                if (artifacts)
                    await page.screenshot({
                        path: path.join(artifacts, `${prefix}-menu.png`),
                        animations: 'disabled',
                    })
                await page.keyboard.press('Escape')
                await expect(menu).toHaveAttribute('aria-expanded', 'false')
                await expect(menu).toBeFocused()
                const question = page.locator('.lp-faq summary').first()
                await question.click()
                await expect(page.locator('.lp-faq details').first()).toHaveAttribute('open', '')
                const source = page.locator('#source-to-pdf')
                await source
                    .getByRole('combobox', { name: 'Typeface', exact: true })
                    .selectOption('sans')
                await source
                    .getByRole('combobox', { name: 'Spacing', exact: true })
                    .selectOption('relaxed')
                const scroll = page.getByRole('region', { name: 'Scrollable layout preview' })
                await scroll.focus()
                await expect(scroll).toBeFocused()
                await expect(scroll.getByRole('article')).toHaveClass(/ts-document-sans/)
                if (artifacts)
                    await source.screenshot({
                        path: path.join(artifacts, `${prefix}-source.png`),
                        animations: 'disabled',
                    })
                expect(
                    await page.evaluate(
                        () => document.documentElement.scrollWidth <= innerWidth + 1
                    )
                ).toBe(true)
            })
        }
    }
}

for (const state of ['disabled', 'failed', 'source-only']) {
    test(`editorial CTA fails closed: ${state}`, async ({ page }) => {
        await page.setViewportSize({ width: 390, height: 844 })
        const { backendOrigin } = qualityOrigins()
        await page.route(
            url => url.origin === backendOrigin && url.pathname === '/config/entitlements',
            route =>
                fulfillQualityJson(
                    route,
                    {
                        features: {
                            ...QUALITY_FEATURES,
                            a09: state === 'source-only',
                            c01: state === 'source-only',
                            b10: false,
                        },
                    },
                    state === 'failed' ? 503 : 200
                )
        )
        await page.goto('/', { waitUntil: 'networkidle' })
        const hero = page.locator('.rd-hero')
        if (state === 'source-only')
            await expect(
                hero.getByRole('link', { name: 'Open the source editor' })
            ).toHaveAttribute('href', '/try?mode=source')
        else {
            await expect(hero.locator('[data-marketing-action]')).toHaveCount(0)
            await expect(hero.locator('[data-marketing-status]')).toContainText(
                state === 'failed' ? 'could not be verified' : 'currently unavailable'
            )
        }
        await expect(
            page.getByRole('link', { name: 'Product', exact: true }).first()
        ).toBeAttached()
        if (artifacts)
            await page.screenshot({
                path: path.join(artifacts, `gate-${state}.png`),
                animations: 'disabled',
            })
    })
}

for (const mode of ['dark', 'light']) {
    for (const contrast of ['normal', 'high']) {
        for (const width of [390, 1440]) {
            test(`editorial forced colors ${mode} ${contrast} ${width}, reduced motion and keyboard navigation`, async ({
                page,
                context,
            }) => {
                await page.setViewportSize({ width, height: 960 })
                await context.addCookies([
                    { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                    { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
                ])
                await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' })
                await page.goto('/', { waitUntil: 'networkidle' })
                await expect(page.locator('.rd-hero [data-marketing-action]')).toBeVisible()
                const desk = page.getByTestId('review-desk')
                await desk.getByRole('tab', { name: 'Review', exact: true }).focus()
                await page.keyboard.press('ArrowRight')
                await expect(desk.getByRole('tab', { name: 'Tailor', exact: true })).toBeFocused()
                await expect(
                    desk.getByRole('tab', { name: 'Tailor', exact: true })
                ).toHaveAttribute('aria-selected', 'true')
                await desk.getByRole('tab', { name: 'Write', exact: true }).click()
                await desk.getByLabel('Your role', { exact: true }).fill(' ')
                await desk.getByRole('button', { name: 'Update sample' }).click()
                await expect(desk.getByRole('alert')).toBeVisible()
                if (artifacts)
                    await page.screenshot({
                        path: path.join(
                            artifacts,
                            `forced-colors-${mode}-${contrast}-${width}.png`
                        ),
                        fullPage: true,
                        animations: 'disabled',
                    })
            })
        }
    }
}
