const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const RESUME = 'e4672413-b158-447e-86ed-d0d31c3d912e';
const OUT = path.resolve(__dirname);
const log = { steps: [], console: [], pageErrors: [], httpErrors: [] };
const snap = async (page, name) => {
  await page.screenshot({ path: path.join(OUT, name), fullPage: false, animations: 'disabled' });
  log.steps.push({ step: name, url: page.url(), title: await page.title() });
};
(async () => {
  const browser = await chromium.launch({ headless: true, acceptDownloads: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.users.free.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 300)); });
  page.on('pageerror', e => log.pageErrors.push(String(e).slice(0, 300)));
  page.on('response', r => { if (r.status() >= 400) log.httpErrors.push({ status: r.status(), url: r.url().slice(0, 220) }); });

  await page.goto(`${BASE}/workspace/builder/${RESUME}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  await page.getByText('Profile & Summary', { exact: false }).first().click().catch(() => {});
  await page.waitForTimeout(600);
  const vals = ['Audit Candidate', 'Product Engineer', 'audit@example.test', '+91 90000 00000', 'Bengaluru, India', 'linkedin.com/in/audit', 'github.com/audit', 'audit.example'];
  const inputs = page.locator('input[type="text"]:visible');
  const n = await inputs.count();
  for (let i = 0; i < Math.min(vals.length, n - 1); i++) {
    await inputs.nth(i + 1).fill(vals[i]);
  }
  const ta = page.locator('textarea:visible').first();
  if (await ta.count()) await ta.fill('Product engineer with experience shipping fast, accessible web applications and distributed systems. Strong focus on measurable customer impact.');
  await page.waitForTimeout(2500);
  await snap(page, 'builder-filled.png');

  await page.getByRole('button', { name: /Preview PDF/i }).first().click();
  await page.waitForTimeout(12000);
  await snap(page, 'builder-preview.png');
  const preview = await page.evaluate(() => ({ text: document.body.innerText.slice(-1200), iframes: document.querySelectorAll('iframe').length, imgs: document.querySelectorAll('img').length, pdfLinks: Array.from(document.querySelectorAll('a')).map(a => a.href).filter(h => h.includes('pdf') || h.includes('download')).slice(0, 5) }));
  log.preview = preview;

  // Optimize page on the builder resume
  await page.goto(`${BASE}/workspace/${RESUME}/optimize`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(8000);
  await snap(page, 'optimize-builder-resume.png');
  log.optimizeText = await page.evaluate(() => document.body.innerText.slice(0, 1200));

  // Cover letter page
  await page.goto(`${BASE}/workspace/${RESUME}/cover-letter`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
  await snap(page, 'cover-letter-builder-resume.png');
  log.coverLetterText = await page.evaluate(() => document.body.innerText.slice(0, 1200));

  // ATS page if exposed through optimize tabs; capture current score text
  await page.goto(`${BASE}/workspace/${RESUME}/career`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  await snap(page, 'career-builder-resume.png');

  fs.writeFileSync(path.join(OUT, 'builder-journey.json'), JSON.stringify(log, null, 2));
  console.log(JSON.stringify({ steps: log.steps, preview: log.preview, optimizeText: log.optimizeText.slice(0, 400), coverLetterText: log.coverLetterText.slice(0, 400), console: log.console, pageErrors: log.pageErrors, httpErrors: log.httpErrors }, null, 2));
  await browser.close();
})();
