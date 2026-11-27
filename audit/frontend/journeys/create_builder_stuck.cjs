const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const OUT = path.resolve(__dirname);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.users.free.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  const net = [];
  page.on('request', r => { if (/builder|resume|entitle|tenant/.test(r.url())) net.push({ phase: 'request', method: r.method(), url: r.url().slice(0, 220) }); });
  page.on('response', r => { if (/builder|resume|entitle|tenant/.test(r.url())) net.push({ phase: 'response', status: r.status(), url: r.url().slice(0, 220) }); });
  page.on('requestfailed', r => net.push({ phase: 'failed', url: r.url().slice(0, 220), err: r.failure()?.errorText }));
  await page.goto(BASE + '/workspace/builder/new', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1200);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const title = 'Audit UI Journey ' + Date.now();
  await page.locator('input[placeholder*="Senior Backend"]').first().fill(title);
  const t0 = Date.now();
  await page.getByRole('button', { name: /Start my r/i }).click();
  await page.waitForTimeout(30000);
  const state = await page.evaluate(() => ({
    url: location.href,
    text: document.body.innerText.slice(-1500),
    buttons: Array.from(document.querySelectorAll('button')).filter(e => e.offsetParent !== null).map(e => (e.innerText || '').trim()).filter(Boolean).slice(-10),
  }));
  await page.screenshot({ path: path.join(OUT, 'builder-create-stuck.png'), fullPage: false });
  fs.writeFileSync(path.join(OUT, 'builder-create-net.json'), JSON.stringify({ title, elapsed: Date.now() - t0, state, net }, null, 2));
  console.log(JSON.stringify({ title, elapsed: Date.now() - t0, url: state.url, textTail: state.text.slice(-500), net }, null, 2));
  await browser.close();
})();
