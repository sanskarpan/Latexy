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
  const log = { console: [], http: [] };
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 300)); });
  page.on('response', r => { if (r.status() >= 400) log.http.push({ status: r.status(), url: r.url().slice(0, 220) }); });

  await page.goto(`${BASE}/workspace/${RESUME}/cover-letter`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const jd = page.locator('textarea').first();
  if (await jd.count()) await jd.fill('We are hiring a senior product engineer to build fast, accessible web applications. React, TypeScript, performance and distributed systems experience required.');
  const gen = page.getByRole('button', { name: /Generate Cover Letter/i }).first();
  let cover = { clicked: false };
  if (await gen.count()) {
    await gen.click(); cover.clicked = true;
    let state = null;
    for (let i = 0; i < 15; i++) {
      await page.waitForTimeout(3000);
      state = await page.evaluate(() => ({ text: document.body.innerText.slice(-1800), buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || '').trim()).filter(Boolean).slice(-15) }));
      if (/failed|error|generated|ready|download|copy/i.test(state.text)) break;
    }
    cover.state = state;
    await page.screenshot({ path: path.join(OUT, 'cover-letter-after-generate.png'), fullPage: false });
  }

  // Template preview
  await page.goto(`${BASE}/templates`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const cards = page.locator('button, a').filter({ hasText: /Use template|Preview|Choose/i });
  let tpl = { cards: await cards.count() };
  if (tpl.cards) {
    await cards.first().click().catch(() => {});
    await page.waitForTimeout(2000);
    tpl.after = await page.evaluate(() => ({ text: document.body.innerText.slice(0, 1200), buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 20) }));
    await page.screenshot({ path: path.join(OUT, 'template-preview.png'), fullPage: false });
  }
  fs.writeFileSync(path.join(OUT, 'cover-template-result.json'), JSON.stringify({ cover, tpl, log }, null, 2));
  console.log(JSON.stringify({ cover: { clicked: cover.clicked, text: cover.state?.text?.slice(-700), buttons: cover.state?.buttons }, tpl, log }, null, 2));
  await browser.close();
})();
