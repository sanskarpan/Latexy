import { expect, test } from '@playwright/test'

test('high-contrast control stays in sync with the pre-paint theme after reload', async ({
    page,
}) => {
    await page.goto('/accessibility')

    const contrastToggle = page.getByRole('button', { name: /high contrast mode/i }).first()
    const modeToggle = page.getByRole('button', { name: 'Toggle light or dark mode' }).first()

    for (const mode of ['light', 'dark'] as const) {
        await test.step(`${mode} theme`, async () => {
            if ((await page.locator('html').getAttribute('data-mode')) !== mode) {
                await modeToggle.click()
            }
            await expect(page.locator('html')).toHaveAttribute('data-mode', mode)

            if ((await contrastToggle.getAttribute('aria-pressed')) !== 'true') {
                await contrastToggle.click()
            }
            await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
            await expect(contrastToggle).toHaveAttribute('aria-pressed', 'true')
            await expect(contrastToggle).toHaveAccessibleName('Turn off high contrast mode')

            await page.reload({ waitUntil: 'domcontentloaded' })

            await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
            await expect(page.locator('html')).toHaveAttribute('data-contrast', 'high')
            await expect(contrastToggle).toHaveAttribute('aria-pressed', 'true')
            await expect(contrastToggle).toHaveAccessibleName('Turn off high contrast mode')

            await modeToggle.click()
            await expect(page.locator('html')).toHaveAttribute(
                'data-mode',
                mode === 'light' ? 'dark' : 'light'
            )
            await modeToggle.click()
            await expect(page.locator('html')).toHaveAttribute('data-mode', mode)

            await contrastToggle.click()
            await expect(page.locator('html')).toHaveAttribute('data-contrast', 'normal')
            await expect(contrastToggle).toHaveAttribute('aria-pressed', 'false')
            await expect(contrastToggle).toHaveAccessibleName('Turn on high contrast mode')

            await page.reload({ waitUntil: 'domcontentloaded' })

            await expect(page.locator('html')).toHaveAttribute('data-mode', mode)
            await expect(page.locator('html')).toHaveAttribute('data-contrast', 'normal')
            await expect(contrastToggle).toHaveAttribute('aria-pressed', 'false')
            await expect(contrastToggle).toHaveAccessibleName('Turn on high contrast mode')
        })
    }
})
