import { mkdir } from 'node:fs/promises'
import path from 'node:path'
import { expect, test } from './quality-test'
import { fulfillQualityJson, QUALITY_FEATURES, qualityOrigins } from './mock-api'

const screenshots = process.env.LANDING_SCREENSHOT_DIR

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

for (const mode of ['dark', 'light'])
    for (const contrast of ['normal', 'high']) {
        test(`document selection and preview keyboard behavior: ${mode} ${contrast}`, async ({
            page,
            context,
        }) => {
            await context.addCookies([
                { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
            ])
            await page.setViewportSize({ width: 390, height: 844 })
            await page.goto('/', { waitUntil: 'networkidle' })
            await expect(page.locator('.rd-hero [data-marketing-action]')).toBeVisible()
            await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' })
            await page.evaluate(() => document.fonts.ready)
            if (screenshots) {
                await mkdir(screenshots, { recursive: true })
                for (const width of [320, 375, 390, 430, 768, 1100, 1101, 1180, 1440]) {
                    await page.setViewportSize({ width, height: 960 })
                    if (width <= 430) {
                        const primary = await page
                            .locator('.lp-footer-message [data-marketing-action]')
                            .boundingBox()
                        const secondary = await page.locator('.ts-closing-secondary').boundingBox()
                        expect(
                            secondary!.y - (primary!.y + primary!.height)
                        ).toBeGreaterThanOrEqual(11)
                    }

                    await page.screenshot({
                        path: path.join(screenshots, `${mode}-${contrast}-final-${width}.png`),
                        fullPage: true,
                        animations: 'disabled',
                    })
                }
                await page.setViewportSize({ width: 390, height: 844 })
            }

            for (const selector of [
                '.rd-paper li',
                '.ts-document-pair .ts-document li',
                '.ts-preview-scroll .ts-document li',
            ]) {
                const text = page.locator(selector).first()
                await text.evaluate(element => {
                    const range = document.createRange()
                    range.selectNodeContents(element)
                    const selection = window.getSelection()!
                    selection.removeAllRanges()
                    selection.addRange(range)
                })
                expect(
                    await page.evaluate(() => window.getSelection()!.toString().length)
                ).toBeGreaterThan(10)
                const ratio = await text.evaluate(element => {
                    const style = getComputedStyle(element, '::selection')
                    const luminance = (color: string) => {
                        const rgb = color
                            .match(/[\d.]+/g)!
                            .slice(0, 3)
                            .map(Number)
                            .map(v => {
                                const c = v / 255
                                return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
                            })
                        return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
                    }
                    const fg = luminance(style.color)
                    const bg = luminance(style.backgroundColor)
                    return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05)
                })
                expect(ratio).toBeGreaterThanOrEqual(contrast === 'high' ? 7 : 4.5)
            }
            await page
                .locator('.rd-paper li')
                .first()
                .evaluate(element => {
                    const range = document.createRange()
                    range.selectNodeContents(element)
                    window.getSelection()!.removeAllRanges()
                    window.getSelection()!.addRange(range)
                })
            if (screenshots) {
                await mkdir(screenshots, { recursive: true })
                await page.locator('.rd-hero').screenshot({
                    path: path.join(screenshots, `${mode}-${contrast}-390-selection.png`),
                    animations: 'disabled',
                })
            }
            await page.evaluate(() => window.getSelection()!.removeAllRanges())
            await page.setViewportSize({ width: 320, height: 844 })
            const source = page.locator('#source-to-pdf')
            const previewDocument = source.getByRole('article')
            const before = await previewDocument.evaluate(element =>
                Number.parseFloat(getComputedStyle(element).lineHeight)
            )
            await source
                .getByRole('combobox', { name: 'Spacing', exact: true })
                .selectOption('relaxed')
            const after = await previewDocument.evaluate(element =>
                Number.parseFloat(getComputedStyle(element).lineHeight)
            )
            expect(after).toBeGreaterThan(before)
            const preview = page.getByRole('region', { name: 'Scrollable layout preview' })
            await preview.focus()
            await expect(preview).toBeFocused()
            const geometry = await preview.evaluate(element => ({
                height: element.clientHeight,
                content: element.scrollHeight,
            }))
            if (geometry.content > geometry.height) {
                await page.keyboard.press('PageDown')
                await expect
                    .poll(() => preview.evaluate(element => element.scrollTop))
                    .toBeGreaterThan(0)
            } else expect(geometry.content).toBeLessThanOrEqual(geometry.height)
            await source
                .getByRole('combobox', { name: 'Spacing', exact: true })
                .selectOption('normal')
            expect(
                await previewDocument.evaluate(element =>
                    Number.parseFloat(getComputedStyle(element).lineHeight)
                )
            ).toBe(before)
        })

        test(`forced-color selection, focus and active tab: ${mode} ${contrast}`, async ({
            page,
            context,
        }) => {
            await context.addCookies([
                { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
            ])
            await page.emulateMedia({ forcedColors: 'active' })
            await page.setViewportSize({ width: 390, height: 844 })
            await page.goto('/', { waitUntil: 'networkidle' })
            const tab = page
                .getByTestId('review-desk')
                .getByRole('tab', { name: 'Review', exact: true })
            await expect(tab).toBeEnabled()
            for (
                let step = 0;
                step < 20 &&
                !(await tab.evaluate(element => element === window.document.activeElement));
                step++
            ) {
                await page.keyboard.press('Tab')
            }
            await expect(tab).toBeFocused()
            const focus = await tab.evaluate(element => {
                const style = getComputedStyle(element)
                return {
                    outline: style.outlineStyle,
                    width: Number.parseFloat(style.outlineWidth),
                    selected: style.textDecorationLine,
                    border: Number.parseFloat(style.borderBottomWidth),
                }
            })
            expect(focus.outline).not.toBe('none')
            expect(focus.width).toBeGreaterThanOrEqual(2)
            expect(focus.selected).toContain('underline')
            expect(focus.border).toBeGreaterThanOrEqual(3)
            if (screenshots) {
                await page.locator('.rd-hero').screenshot({
                    path: path.join(screenshots, `${mode}-${contrast}-390-forced-keyboard.png`),
                    animations: 'disabled',
                })
            }
            const selection = await page
                .locator('.rd-paper li')
                .first()
                .evaluate(element => {
                    const style = getComputedStyle(element, '::selection')
                    const probe = window.document.createElement('span')
                    probe.style.color = 'HighlightText'
                    probe.style.background = 'Highlight'
                    window.document.body.append(probe)
                    const system = getComputedStyle(probe)
                    const result = {
                        color: style.color,
                        background: style.backgroundColor,
                        systemColor: system.color,
                        systemBackground: system.backgroundColor,
                    }
                    probe.remove()
                    return result
                })
            expect(selection.color).toBe(selection.systemColor)
            expect(selection.background).toBe(selection.systemBackground)
        })

        for (const state of ['disabled', 'failed', 'source-only']) {
            test(`gated public navigation remains visible: ${mode} ${contrast} ${state}`, async ({
                page,
                context,
            }) => {
                await context.addCookies([
                    { name: 'latexy-theme', value: mode, url: qualityOrigins().appOrigin },
                    { name: 'latexy-contrast', value: contrast, url: qualityOrigins().appOrigin },
                ])
                await page.setViewportSize({ width: 390, height: 844 })
                await page.route(
                    url =>
                        url.origin === qualityOrigins().backendOrigin &&
                        url.pathname === '/config/entitlements',
                    route =>
                        fulfillQualityJson(
                            route,
                            {
                                features: {
                                    ...QUALITY_FEATURES,
                                    a09: state === 'source-only',
                                    c01: state === 'source-only',
                                    b10: false,
                                    b04: state === 'source-only',
                                },
                            },
                            state === 'failed' ? 503 : 200
                        )
                )
                await page.goto('/', { waitUntil: 'networkidle' })
                if (state === 'source-only')
                    await expect(page.locator('.rd-hero [data-marketing-action]')).toHaveAttribute(
                        'href',
                        '/try?mode=source'
                    )
                else await expect(page.locator('.rd-hero [data-marketing-status]')).toBeVisible()
                await page.locator('.lp-menu-trigger').click()
                const menu = page.locator('#landing-navigation')
                await expect(
                    menu.getByRole('link', { name: 'Platform', exact: true })
                ).toBeVisible()
                await expect(
                    menu.getByRole('link', { name: 'Resources', exact: true })
                ).toBeVisible()
                const templates = menu.getByRole('link', { name: 'Templates', exact: true })
                if (state === 'source-only') await expect(templates).toBeVisible()
                else await expect(templates).toHaveCount(0)
            })
        }
    }

test('server-rendered hero controls wait for hydration', async ({ browser }) => {
    const context = await browser.newContext({ javaScriptEnabled: false })
    const page = await context.newPage()
    await page.goto(qualityOrigins().appOrigin, { waitUntil: 'load' })
    const desk = page.getByTestId('review-desk')
    await expect(desk.locator('.rd-paper')).toContainText('Alex Morgan')
    await expect(desk.locator('.rd-note-actions .rd-small-primary')).toBeDisabled()
    await expect(desk.locator('.rd-note-actions .rd-small-secondary')).toBeDisabled()
    for (const tab of ['Write', 'Review', 'Tailor', 'Export']) {
        await expect(
            desk.getByRole('tab', { name: tab, exact: true, includeHidden: true })
        ).toBeDisabled()
    }
    await context.close()
})
