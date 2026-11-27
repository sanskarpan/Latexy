const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/interaction_identities.json', 'utf8'));
const OUT = path.resolve(__dirname);
function cookie(label) { return { name: '__Secure-better-auth.session_token', value: IDS.users[label].cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }; }
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addCookies([cookie('free')]);
  const page = await ctx.newPage();
  const log = { console: [], http: [] };
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 300)); });
  page.on('response', r => { if (r.status() >= 400) log.http.push({ status: r.status(), url: r.url().slice(0, 220) }); });
  await page.goto(`${BASE}/templates`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const use = page.getByRole('button', { name: /^Use Template$/ }).first();
  const result = { useCount: await use.count() };
  if (result.useCount) {
    await use.click();
    await page.waitForTimeout(6000);
    result.after = { url: page.url(), text: await page.evaluate(() => document.body.innerText.slice(0, 1500)) };
    await page.screenshot({ path: path.join(OUT, 'template-use-free.png'), fullPage: false });
  }
  fs.writeFileSync(path.join(OUT, 'template-use-free.json'), JSON.stringify({ result, log }, null, 2));
  console.log(JSON.stringify({ result, log }, null, 2));
  await browser.close();
})();
