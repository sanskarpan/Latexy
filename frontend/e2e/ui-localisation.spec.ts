import { expect, test } from '@playwright/test'

test.describe('B55 UI localisation', () => {
  test('selector is reachable and persists without changing the route', async ({ page }) => {
    await page.goto('/')
    const selector = page.getByRole('combobox', { name: 'Interface language' })
    await expect(selector).toBeVisible()
    await selector.selectOption('hi')
    await expect(page.locator('html')).toHaveAttribute('lang', 'hi')
    await expect(page.getByRole('link', { name: 'प्लेटफ़ॉर्म' })).toBeVisible()
    await expect(page).toHaveURL(/\/$/)
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('lang', 'hi')
    await expect(page.getByRole('link', { name: 'प्लेटफ़ॉर्म' })).toBeVisible()
    await expect(page.getByRole('combobox', { name: 'इंटरफ़ेस भाषा' })).toHaveValue('hi')
  })
})
