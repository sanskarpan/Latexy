const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const BASE = 'https://latexy.xyz';
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/template_identity.json', 'utf8'));
const OUT = path.resolve(__dirname);
(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  const log = { console: [], http: [] };
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 300)); });
  page.on('response', r => { if (r.status() >= 400) log.http.push({ status: r.status(), url: r.url().slice(0, 220) }); });
  await page.goto(`${BASE}/templates`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await page.waitForTimeout(1500);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const preview = page.getByRole('button', { name: /^Preview$/ }).first();
  let result = { preview: false };
  if (await preview.count()) {
    await preview.click(); result.preview = true;
    await page.waitForTimeout(5000);
    result.modal = await page.evaluate(() => ({ text: document.body.innerText.slice(0, 1500), buttons: Array.from(document.querySelectorAll('button')).filter(b => b.offsetParent !== null).map(b => (b.innerText || '').trim()).filter(Boolean).slice(0, 30) }));
    await page.screenshot({ path: path.join(OUT, 'template-preview-5s.png'), fullPage: false });
    const use = page.getByRole('button', { name: /Use Template|Use this template/i }).first();
    if (await use.count()) {
      await use.click(); result.useClicked = true;
      await page.waitForTimeout(6000);
      result.after = { url: page.url(), text: await page.evaluate(() => document.body.innerText.slice(0, 1000)) };
      await page.screenshot({ path: path.join(OUT, 'template-use.png'), fullPage: false });
    }
  }
  fs.writeFileSync(path.join(OUT, 'template-journey.json'), JSON.stringify({ result, log }, null, 2));
  console.log(JSON.stringify({ result: { preview: result.preview, useClicked: result.useClicked, after: result.after, modalButtons: result.modal?.buttons }, log }, null, 2));
  await browser.close();
})();
