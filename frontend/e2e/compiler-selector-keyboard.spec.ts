import { createHash } from 'node:crypto'
import { expect, test } from '@playwright/test'
import { installMockWorkboxRegistration } from './helpers/mock-workbox-registration'
import { fulfillEngineResponse, mockEngineAncillaryApi, mockEngineRoute, readMonacoSource } from './quality/engine-fixtures'

const RESUME_ID = '8a85a6b1-851d-428c-8cdd-919276558e25'
const OWNER = 'compiler-keyboard-owner'
const TOKEN = 'compiler-keyboard-synthetic-session'
const SOURCE = '\\documentclass{article}\n\\begin{document}Keyboard compiler fixture.\\end{document}'

test.use({ serviceWorkers: 'block' })

test('C07 saved owner selects a compiler with keyboard navigation and one settings write', async ({ page }) => {
    await installMockWorkboxRegistration(page)
    await page.addInitScript(id => {
        localStorage.setItem(`latexy_editor_mode_${id}`, 'source')
        localStorage.setItem('latexy_auto_compile', 'false')
    }, RESUME_ID)
    const unknown: string[] = []
    const pageErrors: string[] = []
    const settingsWrites: unknown[] = []
    const compilationRequests: string[] = []
    page.on('pageerror', error => pageErrors.push(error.message))
    const appOrigin = new URL(test.info().project.use.baseURL!).origin
    await page.route('**/*', route => {
        const url = new URL(route.request().url())
        if (url.origin === appOrigin && !url.pathname.startsWith('/api/')) return route.continue()
        unknown.push(`${route.request().method()} ${url.pathname}`)
        return route.abort()
    })
    // Reuse the ordinary synthetic owner API/CORS boundary. C07 is available;
    // background compilation is denied and no administrative role is granted.
    await mockEngineAncillaryApi(page, OWNER, { c07: true, c05: false, c06: false })
    await mockEngineRoute(page, url => url.pathname === '/api/auth/get-session', route => fulfillEngineResponse(route, {
        json: { session: { token: TOKEN }, user: { id: OWNER, email: 'compiler-owner@example.invalid', name: 'Compiler owner', role: 'user' } },
    }))
    await mockEngineRoute(page, '**/me', route => fulfillEngineResponse(route, {
        json: { id: OWNER, role: 'user', preferences: { has_onboarded: true } },
    }))
    await mockEngineRoute(page, '**/public/engine/capabilities', route => fulfillEngineResponse(route, {
        status: 404, json: { detail: 'This bounded fixture exercises the saved source toolbar' },
    }))
    let compiler = 'xelatex'
    const resume = () => ({
        id: RESUME_ID, user_id: OWNER, access_role: 'owner', title: 'Keyboard compiler fixture',
        latex_content: SOURCE, content_revision: 1, document_type: 'resume', metadata: { compiler },
        created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
    })
    await mockEngineRoute(page, `**/resumes/${RESUME_ID}`, route => {
        expect(route.request().method()).toBe('GET')
        return fulfillEngineResponse(route, { json: resume() })
    })
    await mockEngineRoute(page, `**/resumes/${RESUME_ID}/latest-accepted-artifact`, route => fulfillEngineResponse(route, {
        json: { artifact: null, source_sha256: createHash('sha256').update(SOURCE).digest('hex'), content_revision: 1 },
    }))
    await mockEngineRoute(page, url => /\/(checkpoints|comments|collaborators|suggestions)$/.test(url.pathname),
        route => fulfillEngineResponse(route, { json: [] }))
    await mockEngineRoute(page, '**/jobs/submit', route => {
        compilationRequests.push(route.request().method())
        return fulfillEngineResponse(route, { status: 403, json: { detail: 'Compilation is outside this keyboard contract' } })
    })
    await page.routeWebSocket('**/ws/**', socket => socket.close())
    let releaseSettings!: () => void
    const settingsGate = new Promise<void>(resolve => { releaseSettings = resolve })
    await mockEngineRoute(page, `**/resumes/${RESUME_ID}/settings`, async route => {
        expect(route.request().method()).toBe('PATCH')
        expect(route.request().headers().authorization).toBe(`Bearer ${TOKEN}`)
        settingsWrites.push(route.request().postDataJSON())
        await settingsGate
        compiler = 'lualatex'
        return fulfillEngineResponse(route, { json: resume() })
    })

    try {
        await page.goto(`/workspace/${RESUME_ID}/edit`, { waitUntil: 'domcontentloaded' })
        await expect.poll(() => readMonacoSource(page)).toBe(SOURCE)
        const trigger = page.getByRole('button', { name: 'XeLaTeX', exact: true })
        const menu = page.getByRole('menu', { name: 'LaTeX compiler options' })
        const pdf = menu.getByRole('menuitemradio', { name: /^pdfLaTeX\b/ })
        const xe = menu.getByRole('menuitemradio', { name: /^XeLaTeX\b/ })
        const lua = menu.getByRole('menuitemradio', { name: /^LuaLaTeX\b/ })
        await expect(trigger).toBeEnabled()
        await trigger.focus()
        await page.keyboard.press('ArrowDown')
        await expect(menu).toBeVisible()
        await expect(menu).toHaveAttribute('id', (await trigger.getAttribute('aria-controls'))!)
        await expect(trigger).toHaveAttribute('aria-expanded', 'true')
        await expect(xe).toHaveAttribute('aria-checked', 'true')
        await expect(xe).toBeFocused()
        await page.keyboard.press('ArrowDown')
        await expect(lua).toBeFocused()
        await page.keyboard.press('ArrowDown')
        await expect(pdf).toBeFocused()
        await page.keyboard.press('ArrowUp')
        await expect(lua).toBeFocused()
        await page.keyboard.press('Home')
        await expect(pdf).toBeFocused()
        await page.keyboard.press('End')
        await expect(lua).toBeFocused()
        await page.keyboard.press('Escape')
        await expect(menu).toHaveCount(0)
        await expect(trigger).toBeFocused()
        expect(settingsWrites).toEqual([])

        await page.keyboard.press('ArrowUp')
        await expect(xe).toBeFocused()
        await page.keyboard.press('Tab')
        await expect(menu).toHaveCount(0)
        await expect(trigger).toHaveAttribute('aria-expanded', 'false')
        await expect(page.getByRole('button', { name: 'Compile settings', exact: true })).toBeFocused()
        await page.keyboard.press('Shift+Tab')
        await expect(trigger).toBeFocused()
        expect(settingsWrites).toEqual([])

        await page.keyboard.press('Enter')
        await expect(xe).toBeFocused()
        await page.keyboard.press('End')
        await expect(lua).toBeFocused()
        await page.keyboard.press('Enter')
        await expect.poll(() => settingsWrites.length).toBe(1)
        expect(settingsWrites).toEqual([{ compiler: 'lualatex' }])
        await expect(menu).toHaveCount(0)
        await expect(trigger).toBeDisabled()
        releaseSettings()
        const savedTrigger = page.getByRole('button', { name: 'LuaLaTeX', exact: true })
        await expect(savedTrigger).toBeEnabled()
        await savedTrigger.focus()
        await page.keyboard.press('ArrowDown')
        await expect(lua).toHaveAttribute('aria-checked', 'true')
        await expect(lua).toBeFocused()
        await page.keyboard.press('Escape')
        await expect(savedTrigger).toBeFocused()
        await expect.poll(() => readMonacoSource(page)).toBe(SOURCE)
        expect(settingsWrites).toEqual([{ compiler: 'lualatex' }])
        expect(compilationRequests).toEqual([])
        expect(unknown).toEqual([])
        expect(pageErrors).toEqual([])
    } finally {
        releaseSettings()
    }
})
