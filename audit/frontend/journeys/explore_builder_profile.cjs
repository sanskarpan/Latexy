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
  await page.goto(`${BASE}/workspace/builder/${RESUME}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(2000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  await page.getByText('Profile & Summary', { exact: false }).first().click().catch(() => {});
  await page.waitForTimeout(800);
  const controls = await page.evaluate(() => {
    const q = s => Array.from(document.querySelectorAll(s));
    return {
      text: document.body.innerText.slice(0, 4000),
      inputs: q('input,textarea').filter(e => e.offsetParent !== null).map(e => ({ tag: e.tagName, type: e.type, name: e.name, placeholder: e.placeholder, aria: e.getAttribute('aria-label'), value: (e.value || '').slice(0, 80) })),
      buttons: q('button').filter(e => e.offsetParent !== null).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim()).filter(Boolean).slice(0, 60),
    };
  });
  await page.screenshot({ path: path.join(OUT, 'builder-profile-open.png'), fullPage: false });
  fs.writeFileSync(path.join(OUT, 'builder-profile-controls.json'), JSON.stringify(controls, null, 2));
  console.log(JSON.stringify({ inputs: controls.inputs, buttons: controls.buttons.slice(0, 30) }, null, 2));
  await browser.close();
})();
