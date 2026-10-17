/** Live Next auth + FastAPI + PostgreSQL coverage for public landing gates. */
import { expect, test, type BrowserContext } from '@playwright/test'
import { randomUUID } from 'node:crypto'
import { Pool } from 'pg'

test.skip(
    !process.env.PLAYWRIGHT_REQUIRE_BACKEND,
    'Requires explicitly started isolated local services'
)
test.setTimeout(180_000)

const LANDING_KEYS = ['a09', 'b01', 'c01', 'b04'] as const
const PARENT_KEYS = ['templates'] as const
const RESTORE_KEYS = [...LANDING_KEYS, ...PARENT_KEYS]

function isolatedDatabase() {
    const connectionString = (process.env.DATABASE_URL ?? '').replace(
        'postgresql+asyncpg:',
        'postgresql:'
    )
    const url = new URL(connectionString)
    if (
        !['localhost', '127.0.0.1', '::1'].includes(url.hostname) ||
        !url.pathname.endsWith('_test')
    ) {
        throw new Error(
            'Landing capability acceptance only runs against a loopback *_test database'
        )
    }
    if (
        process.env.OPENAI_API_KEY ||
        process.env.RESEND_API_KEY ||
        process.env.DEPLOY_TARGET === 'modal'
    ) {
        throw new Error(
            'Landing capability acceptance must not use live providers or remote workers'
        )
    }
    return new Pool({ connectionString })
}

async function createAdmin(context: BrowserContext, frontend: string) {
    const email = `test_landing_capability_${randomUUID()}@example.test`
    const response = await context.request.post(`${frontend}/api/auth/sign-up/email`, {
        headers: { Origin: frontend },
        data: {
            name: 'Synthetic landing capability admin',
            email,
            password: `Synthetic-${randomUUID()}!`,
        },
    })
    const body = await response.text()
    expect(response.status(), body).toBe(200)
    const result = JSON.parse(body) as { user: { id: string }; token: string }
    expect(result.user.id).toBeTruthy()
    expect(result.token).toBeTruthy()
    return { id: result.user.id, headers: { Authorization: `Bearer ${result.token}` } }
}

async function setRoleFeature(
    context: BrowserContext,
    backend: string,
    headers: Record<string, string>,
    key: string,
    enabled: boolean
) {
    const response = await context.request.patch(`${backend}/admin/entitlements/roles`, {
        headers,
        data: { role: 'anonymous', feature_key: key, enabled },
    })
    expect(response.status(), await response.text()).toBe(200)
}

async function setPlanFeature(
    context: BrowserContext,
    backend: string,
    headers: Record<string, string>,
    key: string,
    enabled: boolean
) {
    const response = await context.request.patch(`${backend}/admin/entitlements/matrix`, {
        headers,
        data: { plan_family: 'free', feature_key: key, enabled },
    })
    expect(response.status(), await response.text()).toBe(200)
}

async function setGlobalFeature(
    context: BrowserContext,
    backend: string,
    headers: Record<string, string>,
    key: string,
    enabled: boolean
) {
    const response = await context.request.patch(
        `${backend}/admin/entitlements/kill-switch/${key}`,
        {
            headers,
            data: { enabled },
        }
    )
    expect(response.status(), await response.text()).toBe(200)
}

function isEntitlementResponse(response: { url(): string }) {
    return new URL(response.url()).pathname === '/config/entitlements'
}

test('live anonymous landing gates reflect each capability and recover after fetch failure', async ({
    browser,
}, testInfo) => {
    const database = isolatedDatabase()
    const frontend = `http://localhost:${process.env.PLAYWRIGHT_PORT ?? '5181'}`
    const backend = process.env.PLAYWRIGHT_BACKEND_URL ?? 'http://127.0.0.1:8030'
    const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL ?? backend).origin
    const adminContext = await browser.newContext({ baseURL: frontend })
    const guestContext = await browser.newContext({
        baseURL: frontend,
        viewport: { width: 1440, height: 1000 },
    })
    await guestContext.addInitScript(() => {
        localStorage.setItem('latexy_auto_compile', 'false')
    })

    const createdUsers: string[] = []
    const oldRoles = await database.query(
        'SELECT role, feature_key, enabled, updated_at FROM role_features WHERE role = $1 AND feature_key = ANY($2::text[])',
        ['anonymous', RESTORE_KEYS]
    )
    const oldMatrix = await database.query(
        'SELECT plan_family, feature_key, enabled, updated_at FROM plan_features WHERE plan_family = $1 AND feature_key = ANY($2::text[])',
        ['free', RESTORE_KEYS]
    )
    const oldGlobals = await database.query(
        'SELECT key, enabled, updated_at FROM feature_flags WHERE key = ANY($1::text[])',
        [RESTORE_KEYS]
    )

    try {
        const admin = await createAdmin(adminContext, frontend)
        createdUsers.push(admin.id)
        await database.query(
            "UPDATE users SET role = 'admin', email_verified = true WHERE id = $1",
            [admin.id]
        )

        // Start from an explicit, known-enabled state across the real role, plan,
        // and global policy layers. Each OFF check below then changes one role cell.
        for (const key of RESTORE_KEYS) {
            await setGlobalFeature(adminContext, backend, admin.headers, key, true)
            await setPlanFeature(adminContext, backend, admin.headers, key, true)
            await setRoleFeature(adminContext, backend, admin.headers, key, true)
        }

        const page = await guestContext.newPage()
        const hero = page.locator('.lp-hero-actions')
        const studio = hero.getByRole('link', { name: 'Try the studio', exact: true })
        const templates = hero.getByRole('link', { name: 'Explore templates', exact: true })
        const publicFallback = hero.getByRole('link', { name: 'Explore Latexy', exact: true })
        const initialEntitlements = page.waitForResponse(
            response => isEntitlementResponse(response) && response.status() === 200
        )
        await page.goto('/', { waitUntil: 'domcontentloaded' })
        const initialFeatures = (await (await initialEntitlements).json()).features as Record<
            string,
            boolean
        >
        for (const key of LANDING_KEYS)
            expect(initialFeatures[key], `${key} starts enabled`).toBe(true)
        expect(initialFeatures.templates, 'the b04 parent starts enabled').toBe(true)
        await expect(studio).toBeVisible()
        await expect(studio).toHaveAttribute('href', '/try?mode=visual')
        await expect(templates).toBeVisible()
        await expect(publicFallback).toBeVisible()

        await page.evaluate(() => document.fonts.ready)
        const desktopPath = testInfo.outputPath('landing-desktop-enabled.png')
        const desktopImage = await page.screenshot({
            path: desktopPath,
            fullPage: true,
            animations: 'disabled',
            caret: 'hide',
        })
        expect(desktopImage.byteLength, 'desktop evidence is a populated PNG').toBeGreaterThan(
            10_000
        )
        await testInfo.attach('landing-desktop-enabled', {
            body: desktopImage,
            contentType: 'image/png',
        })

        await page.setViewportSize({ width: 390, height: 844 })
        const mobileGallery = page.locator('.lp-gallery')
        await expect(mobileGallery.getByRole('textbox', { name: 'Sample name' })).toBeVisible()
        await expect(mobileGallery.getByRole('textbox', { name: 'Sample role' })).toBeVisible()
        await expect(
            mobileGallery.getByRole('button', { name: 'Read the full sample' })
        ).toBeVisible()
        expect(
            (await mobileGallery.boundingBox())!.height,
            'mobile gallery remains compact and usable'
        ).toBeLessThan(550)
        const mobileWidth = await page.evaluate(() => ({
            viewport: document.documentElement.clientWidth,
            document: document.documentElement.scrollWidth,
        }))
        expect(mobileWidth.document).toBeLessThanOrEqual(mobileWidth.viewport + 1)
        await expect(studio).toBeVisible()
        await expect(templates).toBeVisible()
        const mobilePath = testInfo.outputPath('landing-mobile-enabled.png')
        const mobileImage = await page.screenshot({
            path: mobilePath,
            fullPage: true,
            animations: 'disabled',
            caret: 'hide',
        })
        expect(mobileImage.byteLength, 'mobile evidence is a populated PNG').toBeGreaterThan(10_000)
        await testInfo.attach('landing-mobile-enabled', {
            body: mobileImage,
            contentType: 'image/png',
        })

        for (const key of ['a09', 'b01', 'c01'] as const) {
            await setRoleFeature(adminContext, backend, admin.headers, key, false)
            const deniedResponse = page.waitForResponse(
                response => isEntitlementResponse(response) && response.status() === 200
            )
            await page.reload({ waitUntil: 'domcontentloaded' })
            const deniedFeatures = (await (await deniedResponse).json()).features as Record<
                string,
                boolean
            >
            expect(deniedFeatures[key], `${key} is denied by the live backend`).toBe(false)
            for (const other of ['a09', 'b01', 'c01'].filter(candidate => candidate !== key)) {
                expect(deniedFeatures[other], `${other} remains enabled while testing ${key}`).toBe(
                    true
                )
            }
            await expect(studio, `${key} individually hides the studio CTA`).toHaveCount(0)
            await expect(publicFallback).toBeVisible()

            await setRoleFeature(adminContext, backend, admin.headers, key, true)
            const restoredResponse = page.waitForResponse(
                response => isEntitlementResponse(response) && response.status() === 200
            )
            await page.reload({ waitUntil: 'domcontentloaded' })
            const restoredFeatures = (await (await restoredResponse).json()).features as Record<
                string,
                boolean
            >
            expect(restoredFeatures[key]).toBe(true)
            await expect(studio, `${key} recovery restores the studio CTA`).toBeVisible()
        }

        await setRoleFeature(adminContext, backend, admin.headers, 'b04', false)
        const templatesDeniedResponse = page.waitForResponse(
            response => isEntitlementResponse(response) && response.status() === 200
        )
        await page.reload({ waitUntil: 'domcontentloaded' })
        const templatesDenied = (await (await templatesDeniedResponse).json()).features as Record<
            string,
            boolean
        >
        expect(templatesDenied.b04).toBe(false)
        expect(templatesDenied.a09).toBe(true)
        expect(templatesDenied.b01).toBe(true)
        expect(templatesDenied.c01).toBe(true)
        await expect(templates).toHaveCount(0)
        await expect(studio).toBeVisible()

        await setRoleFeature(adminContext, backend, admin.headers, 'b04', true)
        const templatesRestoredResponse = page.waitForResponse(
            response => isEntitlementResponse(response) && response.status() === 200
        )
        await page.reload({ waitUntil: 'domcontentloaded' })
        const templatesRestored = (await (await templatesRestoredResponse).json())
            .features as Record<string, boolean>
        expect(templatesRestored.b04).toBe(true)
        await expect(templates).toBeVisible()

        const entitlementUrl = (url: URL) =>
            url.origin === apiOrigin && url.pathname === '/config/entitlements'
        let failNextEntitlementFetch = true
        await page.route(entitlementUrl, async route => {
            if (failNextEntitlementFetch) {
                failNextEntitlementFetch = false
                await route.fulfill({
                    status: 503,
                    contentType: 'application/json',
                    body: JSON.stringify({ detail: 'Synthetic one-request entitlement outage' }),
                })
                return
            }
            await route.continue()
        })
        const failedFetch = page.waitForResponse(
            response => isEntitlementResponse(response) && response.status() === 503
        )
        await page.reload({ waitUntil: 'domcontentloaded' })
        await failedFetch
        await expect(studio, 'an entitlement fetch failure fails closed').toHaveCount(0)
        await expect(templates).toHaveCount(0)
        await expect(publicFallback).toBeVisible()

        await page.unroute(entitlementUrl)
        const recoveredFetch = page.waitForResponse(
            response => isEntitlementResponse(response) && response.status() === 200
        )
        await page.evaluate(() => window.dispatchEvent(new Event('latexy:entitlements-updated')))
        const recoveredFeatures = (await (await recoveredFetch).json()).features as Record<
            string,
            boolean
        >
        for (const key of LANDING_KEYS) expect(recoveredFeatures[key]).toBe(true)
        await expect(studio, 'a live entitlement refetch restores the studio CTA').toBeVisible()
        await expect(templates, 'a live entitlement refetch restores templates').toBeVisible()
    } finally {
        for (const row of oldGlobals.rows) {
            await database.query(
                'UPDATE feature_flags SET enabled = $1, updated_at = $2 WHERE key = $3',
                [row.enabled, row.updated_at, row.key]
            )
        }
        for (const row of oldMatrix.rows) {
            await database.query(
                'UPDATE plan_features SET enabled = $1, updated_at = $2 WHERE plan_family = $3 AND feature_key = $4',
                [row.enabled, row.updated_at, row.plan_family, row.feature_key]
            )
        }
        for (const row of oldRoles.rows) {
            await database.query(
                'UPDATE role_features SET enabled = $1, updated_at = $2 WHERE role = $3 AND feature_key = $4',
                [row.enabled, row.updated_at, row.role, row.feature_key]
            )
        }
        if (createdUsers.length) {
            await database.query('DELETE FROM session WHERE "userId" = ANY($1::text[])', [
                createdUsers,
            ])
            await database.query('DELETE FROM account WHERE "userId" = ANY($1::text[])', [
                createdUsers,
            ])
            await database.query('DELETE FROM users WHERE id = ANY($1::uuid[])', [createdUsers])
        }
        await adminContext.close()
        await guestContext.close()
        await database.end()
    }
})
