const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const RESUME = 'e4672413-b158-447e-86ed-d0d31c3d912e';
const OUT = path.resolve(__dirname);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.users.free.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  const log = { console: [], http: [], jobs: [] };
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 300)); });
  page.on('response', r => { if (r.status() >= 400) log.http.push({ status: r.status(), url: r.url().slice(0, 220) }); if (r.url().includes('/jobs/')) log.jobs.push({ status: r.status(), url: r.url().slice(0, 220) }); });
  await page.goto(`${BASE}/workspace/${RESUME}/optimize`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(26000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const ta = page.locator('textarea').filter({ hasText: '' }).first();
  const area = page.locator('textarea[placeholder*="Paste a job description"]').first();
  if (await area.count()) await area.fill('We are hiring a senior product engineer to build fast, accessible web applications. Experience with React, TypeScript, distributed systems and performance required.');
  const btn = page.getByRole('button', { name: /Optimize Resume/i }).first();
  const start = Date.now();
  if (await btn.count()) await btn.click(); else log.noButton = true;
  let state = null;
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(3000);
    state = await page.evaluate(() => ({ text: document.body.innerText.slice(-1600), buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || '').trim()).filter(Boolean).slice(-15) }));
    if (/failed|error|complete|optimized|upgrade|quota/i.test(state.text)) break;
  }
  await page.screenshot({ path: path.join(OUT, 'optimize-action.png'), fullPage: false });
  fs.writeFileSync(path.join(OUT, 'optimize-action.json'), JSON.stringify({ elapsed: Date.now() - start, state, log }, null, 2));
  console.log(JSON.stringify({ elapsed: Date.now() - start, textTail: state.text.slice(-900), buttons: state.buttons, log }, null, 2));
  await browser.close();
})();
