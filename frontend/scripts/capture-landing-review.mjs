import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

const baseUrl = process.argv[2] || 'http://localhost:5197/'
const outputDir = resolve(process.argv[3] || 'landing-review')
await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({ headless: true })
try {
    for (const theme of ['light', 'dark']) {
        if (process.argv[5] && theme !== process.argv[5]) continue
        for (const [label, viewport] of [
            ['desktop', { width: 1440, height: 900 }],
            ['mobile', { width: 390, height: 844 }],
        ]) {
            if (process.argv[4] && label !== process.argv[4]) continue
            const context = await browser.newContext({ viewport, deviceScaleFactor: 2 })
            await context.addCookies([{
                name: 'latexy-theme',
                value: theme,
                url: baseUrl,
            }])
            const page = await context.newPage()
            await page.emulateMedia({ reducedMotion: 'reduce' })
            await page.goto(baseUrl, { waitUntil: 'domcontentloaded' })
            await page.locator('.lp-hero h1').waitFor({ state: 'visible' })
            await page.locator('.lp-document-card[data-slot="center"] .lp-hero-paper').waitFor({ state: 'visible' })
            await page.locator('.lp-gallery-personalise input').first().waitFor({ state: 'visible' })
            await page.locator('.lp-footer').scrollIntoViewIfNeeded()
            await page.locator('.lp-footer-art img').evaluate(image => image.decode())
            await page.evaluate(() => document.fonts.ready)
            await page.evaluate(() => {
                scrollTo({ top: 0, left: 0, behavior: 'instant' })
                return new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))
            })
            await page.waitForTimeout(400)
            await page.screenshot({ path: resolve(outputDir, `${label}-${theme}.png`), fullPage: true, animations: 'disabled' })
            await page.screenshot({ path: resolve(outputDir, `${label}-${theme}-first-screen.png`), animations: 'disabled' })
            await page.locator('.lp-opening').screenshot({ path: resolve(outputDir, `${label}-${theme}-opening.png`), animations: 'disabled' })
            await context.close()
        }
    }
} finally {
    await browser.close()
}
