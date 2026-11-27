/* Second visual pass: dismiss the consent banner, wait for lazy UI, viewport screenshots. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const OUT = path.resolve(__dirname, 'pages');
const pages = [
  ['/', 'anon', 'home'], ['/pricing', 'anon', 'pricing'], ['/login', 'anon', 'login'],
  ['/signup', 'anon', 'signup'], ['/templates', 'anon', 'templates'], ['/try', 'anon', 'try'],
  ['/dashboard', 'free', 'dashboard'], ['/settings', 'free', 'settings'], ['/tracker', 'free', 'tracker'],
  ['/workspace', 'free', 'workspace'], ['/workspace/new', 'free', 'workspace-new'],
  [`/workspace/${IDS.free_resume_id}/edit`, 'free', 'workspace-edit'],
  [`/workspace/${IDS.free_resume_id}/optimize`, 'free', 'workspace-optimize'],
  [`/workspace/variant/${IDS.free_resume_id}`, 'free', 'workspace-variant'],
  [`/r/${IDS.share_token}`, 'anon', 'share'], ['/admin', 'admin', 'admin'],
  ['/admin/tenant', 'admin', 'admin-tenant'], [`/workspaces/${IDS.workspace_id}`, 'team', 'workspaces-detail'],
  [`/workspaces/${IDS.workspace_id}/recruiter`, 'team', 'workspaces-recruiter'],
  ['/workspaces', 'team', 'workspaces'], ['/billing', 'pro', 'billing'], ['/byok', 'pro', 'byok'],
];
function cookie(label) {
  if (label === 'anon') return null;
  const u = IDS.users[label];
  return { name: '__Secure-better-auth.session_token', value: u.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' };
}
(async () => {
  const browser = await chromium.launch({ headless: true });
  for (const [route, role, slug] of pages) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const c = cookie(role); if (c) await ctx.addCookies([c]);
    const page = await ctx.newPage();
    await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(1000);
    for (const label of ['Essential only', 'Allow analytics']) {
      try { await page.getByRole('button', { name: label }).click({ timeout: 1200 }); break; } catch {}
    }
    await page.waitForTimeout(800);
    // Scroll to the main content for pages with a large hero/header.
    const h1 = page.locator('h1').first();
    if (await h1.count()) await h1.scrollIntoViewIfNeeded().catch(() => {});
    await page.screenshot({ path: path.join(OUT, slug, 'desktop-clean.png'), fullPage: false, animations: 'disabled' });
    // Capture the first scroll of the page for long dashboards.
    await page.evaluate(() => window.scrollBy(0, 700));
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(OUT, slug, 'desktop-clean-2.png'), fullPage: false, animations: 'disabled' });
    console.log(slug, 'captured');
    await ctx.close();
  }
  await browser.close();
})();
