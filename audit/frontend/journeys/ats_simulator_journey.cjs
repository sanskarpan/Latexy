const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/interact8_identity.json', 'utf8'));
const BASE = 'https://latexy.xyz';
const OUT = 'C:/Users/Sansk/Projects/Latexy/audit/frontend/journeys';

(async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
  await ctx.addCookies([{ name: '__Secure-better-auth.session_token', value: IDS.cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' }]);
  const page = await ctx.newPage();
  const log = { console: [], http: [], ats: [] };
  page.on('console', m => { if (m.type() === 'error') log.console.push(m.text().slice(0, 220)); });
  page.on('response', async r => {
    if (r.status() >= 400) log.http.push({ status: r.status(), url: r.url().slice(0, 200) });
    if (/\/ats\//i.test(r.url())) {
      let body = ''; try { body = (await r.text()).slice(0, 700); } catch {}
      log.ats.push({ status: r.status(), url: r.url().slice(0, 160), body });
    }
  });

  const t0 = Date.now();
  await page.goto(`${BASE}/workspace/${IDS.resume_id}/optimize`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(2000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await page.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const loaded = await page.getByText('Targeted Optimization', { exact: false }).first().waitFor({ state: 'visible', timeout: 45000 }).then(() => true).catch(() => false);
  const result = { loaded, loadMs: Date.now() - t0 };

  const profile = page.locator('button').filter({ hasText: 'Greenhouse' }).first();
  result.profileVisible = await profile.waitFor({ state: 'visible', timeout: 20000 }).then(() => true).catch(() => false);
  result.profileText = result.profileVisible ? (await profile.innerText()).trim().slice(0, 60) : null;
  const run = page.getByRole('button', { name: /^Run checks$/ }).first();
  result.runFound = await run.count();
  result.runDisabledBeforeProfile = await run.isDisabled().catch(() => null);
  if (result.profileVisible) {
    await profile.click();
    await page.waitForTimeout(500);
  }
  result.runDisabledAfterProfile = await run.isDisabled().catch(() => null);
  const simStart = Date.now();
  if (result.runFound && !(await run.isDisabled())) {
    await run.click();
    await page.getByText(/Heuristic check score|No issues detected|Issues \(/i).first().waitFor({ state: 'visible', timeout: 45000 }).catch(() => null);
    result.simMs = Date.now() - simStart;
    result.afterText = (await page.evaluate(() => document.body.innerText)).slice(-2200);
    result.scoreVisible = /Heuristic check score|No issues detected|Issues \(/i.test(result.afterText);
    await page.screenshot({ path: path.join(OUT, 'ats-simulator-result.png'), fullPage: false });
  }
  fs.writeFileSync(path.join(OUT, 'ats-simulator-journey.json'), JSON.stringify({ result, log }, null, 2));
  console.log(JSON.stringify({ result, log }, null, 2));
  await browser.close();
})();
