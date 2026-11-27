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

  // Optimize: wait up to 25s for the feature gate
  await page.goto(`${BASE}/workspace/${RESUME}/optimize`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(25000);
  const optState = await page.evaluate(() => ({
    text: document.body.innerText.slice(0, 2500),
    buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || b.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 40),
    inputs: Array.from(document.querySelectorAll('input,textarea')).filter(e => e.offsetParent !== null).map(e => ({ tag: e.tagName, placeholder: e.placeholder, type: e.type })),
  }));
  await page.screenshot({ path: path.join(OUT, 'optimize-after-25s.png'), fullPage: false });

  // Tracker add application via UI
  await page.goto(`${BASE}/tracker`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const add = page.getByRole('button', { name: /Add (your first )?application/i }).first();
  let tracker = { opened: false };
  if (await add.count()) {
    await add.click();
    await page.waitForTimeout(600);
    tracker.opened = true;
    await page.locator('input[placeholder="e.g. Google"]').fill('Audit UI Co');
    await page.locator('input[placeholder="e.g. Software Engineer"]').fill('Senior Product Engineer');
    const date = new Date().toISOString().slice(0, 10);
    await page.locator('input[type="date"]').fill(date).catch(() => {});
    await page.locator('input[type="url"]').fill('https://example.com/job').catch(() => {});
    // Click the last visible Add Application button in the modal.
    const addButtons = page.getByRole('button', { name: /^Add Application$/ });
    const n = await addButtons.count();
    if (n) await addButtons.nth(n - 1).click();
    await page.waitForTimeout(2500);
    tracker.after = await page.evaluate(() => ({ text: document.body.innerText.slice(0, 1200), buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 25) }));
    await page.screenshot({ path: path.join(OUT, 'tracker-after-add.png'), fullPage: false });
  }
  fs.writeFileSync(path.join(OUT, 'optimize-tracker-result.json'), JSON.stringify({ optState, tracker, log }, null, 2));
  console.log(JSON.stringify({ optState: { text: optState.text.slice(0, 500), buttons: optState.buttons, inputs: optState.inputs }, tracker, log }, null, 2));
  await browser.close();
})();
