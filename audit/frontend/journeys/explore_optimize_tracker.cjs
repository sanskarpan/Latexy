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
  await page.goto(`${BASE}/workspace/${RESUME}/optimize`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(3000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  await page.waitForTimeout(800);
  const buttons = await page.evaluate(() => Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean));
  const inputs = await page.evaluate(() => Array.from(document.querySelectorAll('input,textarea')).filter(e => e.offsetParent !== null).map(e => ({ tag: e.tagName, type: e.type, placeholder: e.placeholder, value: (e.value || '').slice(0, 80) })));
  await page.screenshot({ path: path.join(OUT, 'optimize-loaded.png'), fullPage: false });

  // Tracker add application
  await page.goto(`${BASE}/tracker`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const add = page.getByRole('button', { name: /Add (your first )?application/i }).first();
  let tracker = { opened: false };
  if (await add.count()) {
    await add.click();
    await page.waitForTimeout(800);
    tracker.opened = true;
    tracker.form = await page.evaluate(() => ({
      inputs: Array.from(document.querySelectorAll('input,textarea,select')).filter(e => e.offsetParent !== null).map(e => ({ tag: e.tagName, type: e.type, name: e.name, placeholder: e.placeholder, label: e.getAttribute('aria-label') })),
      buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(-15),
    }));
    await page.screenshot({ path: path.join(OUT, 'tracker-add-form.png'), fullPage: false });
  }
  fs.writeFileSync(path.join(OUT, 'optimize-tracker-explore.json'), JSON.stringify({ buttons, inputs, tracker, log }, null, 2));
  console.log(JSON.stringify({ buttons: buttons.slice(0, 30), inputs, tracker, log }, null, 2));
  await browser.close();
})();
