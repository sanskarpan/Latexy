const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/interact9_identities.json', 'utf8'));
const BASE = 'https://latexy.xyz';
const OUT = 'C:/Users/Sansk/Projects/Latexy/audit/frontend/journeys';
const WS = IDS.users.owner.workspace_id;

function cookieFor(label) {
  return { name: '__Secure-better-auth.session_token', value: IDS.users[label].cookie, domain: 'latexy.xyz', path: '/', secure: true, httpOnly: true, sameSite: 'Lax' };
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const log = { owner: { console: [], http: [] }, member: { console: [], http: [] } };

  const ownerCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await ownerCtx.addCookies([cookieFor('owner')]);
  const owner = await ownerCtx.newPage();
  owner.on('console', m => { if (m.type() === 'error') log.owner.console.push(m.text().slice(0, 200)); });
  owner.on('response', r => { if (r.status() >= 400) log.owner.http.push({ status: r.status(), url: r.url().slice(0, 200) }); });
  await owner.goto(`${BASE}/workspaces/${WS}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await owner.waitForTimeout(3000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await owner.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const invite = owner.locator('input[placeholder="colleague@company.com"]').first();
  const inviteVisible = await invite.waitFor({ state: 'visible', timeout: 20000 }).then(() => true).catch(() => false);
  const ownerResult = { inviteVisible, pageText: (await owner.evaluate(() => document.body.innerText)).slice(0, 900) };
  if (inviteVisible) {
    await invite.fill(IDS.users.member.email);
    await invite.press('Enter');
    await owner.waitForTimeout(4000);
    ownerResult.afterText = (await owner.evaluate(() => document.body.innerText)).slice(0, 1400);
    ownerResult.memberVisible = ownerResult.afterText.includes(IDS.users.member.email);
    ownerResult.toastVisible = ownerResult.afterText.includes('added to workspace');
    await owner.screenshot({ path: path.join(OUT, 'team-workspace-owner.png'), fullPage: false });
  }
  await ownerCtx.close();

  const memberCtx = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await memberCtx.addCookies([cookieFor('member')]);
  const member = await memberCtx.newPage();
  member.on('console', m => { if (m.type() === 'error') log.member.console.push(m.text().slice(0, 200)); });
  member.on('response', r => { if (r.status() >= 400) log.member.http.push({ status: r.status(), url: r.url().slice(0, 200) }); });
  await member.goto(`${BASE}/workspaces`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await member.waitForTimeout(3000);
  for (const label of ['Essential only', 'Allow analytics']) { try { await member.getByRole('button', { name: label }).click({ timeout: 1000 }); break; } catch {} }
  const listText = (await member.evaluate(() => document.body.innerText)).slice(0, 1200);
  await member.goto(`${BASE}/workspaces/${WS}`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await member.waitForTimeout(3500);
  const memberText = (await member.evaluate(() => document.body.innerText)).slice(0, 1600);
  const memberResult = { listText, workspaceText: memberText, workspaceAccessible: !memberText.includes('not found') && !memberText.includes('404') && memberText.includes('Interaction9 Workspace') };
  await member.screenshot({ path: path.join(OUT, 'team-workspace-member.png'), fullPage: false });
  await memberCtx.close();

  fs.writeFileSync(path.join(OUT, 'team-invite-journey.json'), JSON.stringify({ ownerResult, memberResult, log }, null, 2));
  console.log(JSON.stringify({ ownerResult, memberResult, log }, null, 2));
  await browser.close();
})();
