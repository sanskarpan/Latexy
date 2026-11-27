/* Exploratory: create a builder resume through the real UI and dump the editor controls. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const OUT = path.resolve(__dirname, 'journeys');
fs.mkdirSync(OUT, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.users.free.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  const logs = { console: [], errors: [], requests: [] };
  page.on('console', m => { if (m.type() === 'error') logs.console.push(m.text().slice(0, 300)); });
  page.on('pageerror', e => logs.errors.push(String(e).slice(0, 300)));
  page.on('response', r => { if (r.status() >= 400) logs.requests.push({ status: r.status(), url: r.url().slice(0, 200) }); });
  await page.goto(BASE + '/workspace/builder/new', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const title = 'Audit UI Journey ' + Date.now();
  const titleInput = page.locator('input[placeholder*="Senior Backend"]').first();
  await titleInput.fill(title);
  await page.getByRole('button', { name: /Start my r/i }).click();
  await page.waitForURL(/\/workspace\/builder\//, { timeout: 30000 }).catch(() => {});
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(OUT, 'builder-created.png'), fullPage: false, animations: 'disabled' });
  const controls = await page.evaluate(() => {
    const q = s => Array.from(document.querySelectorAll(s));
    return {
      url: location.href,
      title: document.title,
      h1: q('h1').map(e => e.innerText),
      inputs: q('input,textarea').filter(e => e.offsetParent !== null).map(e => ({ tag: e.tagName, type: e.type, name: e.name, placeholder: e.placeholder, aria: e.getAttribute('aria-label'), value: (e.value || '').slice(0, 60) })).slice(0, 40),
      buttons: q('button').filter(e => e.offsetParent !== null).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 40),
      text: document.body.innerText.slice(0, 3000),
    };
  });
  fs.writeFileSync(path.join(OUT, 'builder-controls.json'), JSON.stringify({ title, logs, controls }, null, 2));
  console.log(JSON.stringify({ title, url: controls.url, h1: controls.h1, inputs: controls.inputs.length, buttons: controls.buttons, logs }, null, 2));
  fs.writeFileSync(path.join(OUT, 'builder-identity.json'), JSON.stringify({ title, url: controls.url }, null, 2));
  await browser.close();
})();
