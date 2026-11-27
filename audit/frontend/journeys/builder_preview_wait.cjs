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
  const http = [];
  page.on('response', r => { if (r.url().includes('/jobs') || r.url().includes('pdf') || r.url().includes('builder')) http.push({ status: r.status(), url: r.url().slice(0, 200) }); });
  await page.goto(`${BASE}/workspace/builder/${RESUME}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1200);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const start = Date.now();
  await page.getByRole('button', { name: /Preview PDF/i }).first().click();
  let state = null;
  for (let i = 0; i < 24; i++) {
    await page.waitForTimeout(2500);
    state = await page.evaluate(() => ({
      text: document.body.innerText.slice(-800),
      iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src.slice(0, 200)),
      imgs: Array.from(document.querySelectorAll('img')).map(i => i.src.slice(0, 200)).filter(s => s.includes('blob') || s.includes('pdf')),
      buttons: Array.from(document.querySelectorAll('button')).filter(b => /PDF|Download|Preparing/i.test(b.innerText)).map(b => ({ text: b.innerText, disabled: b.disabled })),
    }));
    if (state.iframes.length || state.imgs.length || /Download PDF/i.test(state.text)) break;
  }
  await page.screenshot({ path: path.join(OUT, 'builder-preview-after.png'), fullPage: false });
  fs.writeFileSync(path.join(OUT, 'builder-preview-result.json'), JSON.stringify({ elapsed: Date.now() - start, state, http }, null, 2));
  console.log(JSON.stringify({ elapsed: Date.now() - start, state, http: http.slice(-20) }, null, 2));
  await browser.close();
})();
