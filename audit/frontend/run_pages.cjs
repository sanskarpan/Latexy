/* Front-end page audit: screenshots + DOM/console/network/performance signals. */
const fs = require('fs');
const path = require('path');
const { chromium } = require('C:/Users/Sansk/Projects/Latexy/frontend/node_modules/@playwright/test');

const BASE = 'https://latexy.xyz';
const OUT = path.resolve(__dirname, 'pages');
const IDS = JSON.parse(fs.readFileSync('C:/Users/Sansk/AppData/Local/Temp/opencode/fe_identities.json', 'utf8'));
const users = IDS.users;

const routes = [
  ['/', 'anon', 'home'],
  ['/accessibility', 'anon', 'accessibility'],
  ['/admin', 'admin', 'admin'],
  ['/admin/tenant', 'admin', 'admin-tenant'],
  ['/billing', 'pro', 'billing'],
  ['/byok', 'pro', 'byok'],
  ['/dashboard', 'free', 'dashboard'],
  ['/developer', 'pro', 'developer'],
  ['/faq', 'anon', 'faq'],
  ['/forgot-password', 'anon', 'forgot-password'],
  ['/login', 'anon', 'login'],
  ['/platform', 'anon', 'platform'],
  ['/pricing', 'anon', 'pricing'],
  ['/privacy', 'anon', 'privacy'],
  [`/r/${IDS.share_token}`, 'anon', 'share'],
  ['/reset-password', 'anon', 'reset-password'],
  ['/resources', 'anon', 'resources'],
  ['/settings', 'free', 'settings'],
  ['/signup', 'anon', 'signup'],
  ['/templates', 'anon', 'templates'],
  ['/tenant-invite', 'anon', 'tenant-invite'],
  ['/terms', 'anon', 'terms'],
  ['/tracker', 'free', 'tracker'],
  ['/try', 'anon', 'try'],
  ['/two-factor', 'anon', 'two-factor'],
  [`/u/${IDS.portfolio_username}`, 'anon', 'portfolio'],
  ['/updates', 'anon', 'updates'],
  ['/verify-email', 'free', 'verify-email'],
  [`/workspace/${IDS.free_resume_id}/batch-tailor`, 'free', 'workspace-batch-tailor'],
  [`/workspace/${IDS.free_resume_id}/career`, 'free', 'workspace-career'],
  [`/workspace/${IDS.free_resume_id}/cover-letter`, 'free', 'workspace-cover-letter'],
  [`/workspace/${IDS.free_resume_id}/edit`, 'free', 'workspace-edit'],
  [`/workspace/${IDS.free_resume_id}/optimize`, 'free', 'workspace-optimize'],
  [`/workspace/builder/${IDS.free_resume_id}`, 'free', 'workspace-builder'],
  ['/workspace/builder/new', 'free', 'workspace-builder-new'],
  ['/workspace/cover-letters', 'free', 'workspace-cover-letters'],
  ['/workspace/history', 'free', 'workspace-history'],
  ['/workspace/merge', 'free', 'workspace-merge'],
  ['/workspace/new', 'free', 'workspace-new'],
  ['/workspace', 'free', 'workspace'],
  [`/workspace/variant/${IDS.free_resume_id}`, 'free', 'workspace-variant'],
  [`/workspaces/${IDS.workspace_id}`, 'team', 'workspaces-detail'],
  [`/workspaces/${IDS.workspace_id}/recruiter`, 'team', 'workspaces-recruiter'],
  ['/workspaces', 'team', 'workspaces'],
];

function cookieFor(label) {
  if (label === 'anon') return null;
  const u = users[label];
  if (!u || !u.cookie) throw new Error(`missing cookie for ${label}`);
  return {
    name: '__Secure-better-auth.session_token',
    value: u.cookie,
    domain: 'latexy.xyz',
    path: '/',
    secure: true,
    httpOnly: true,
    sameSite: 'Lax',
  };
}

async function metrics(page) {
  return page.evaluate(() => {
    const q = (s) => Array.from(document.querySelectorAll(s));
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none';
    };
    const text = (el) => (el.innerText || el.textContent || '').trim();
    const smallText = q('body *').filter((el) => {
      if (!visible(el) || !text(el)) return false;
      const size = parseFloat(getComputedStyle(el).fontSize || '16');
      return size < 12;
    }).length;
    const overflow = q('body *').filter((el) => {
      if (!visible(el)) return false;
      const r = el.getBoundingClientRect();
      return r.right > window.innerWidth + 2 || r.left < -2;
    }).slice(0, 10).map((el) => ({
      tag: el.tagName,
      cls: (el.className || '').toString().slice(0, 80),
      text: text(el).slice(0, 80),
      right: Math.round(el.getBoundingClientRect().right),
      left: Math.round(el.getBoundingClientRect().left),
    }));
    const unlabeled = q('button, a[href], input, select, textarea').filter((el) => {
      if (!visible(el)) return false;
      const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.getAttribute('title');
      const txt = text(el) || el.getAttribute('alt') || el.getAttribute('placeholder') || '';
      return !aria && !txt;
    }).length;
    const inputs = q('input, select, textarea').filter(visible);
    const unlabelledInputs = inputs.filter((el) => {
      if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
      if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return false;
      if (el.closest('label')) return false;
      if (el.getAttribute('placeholder')) return false;
      return true;
    }).length;
    const imgs = q('img');
    const nav = performance.getEntriesByType('navigation')[0];
    const lcp = performance.getEntriesByType('largest-contentful-paint').slice(-1)[0];
    const shifts = performance.getEntriesByType('layout-shift');
    const cls = shifts.filter((e) => !e.hadRecentInput).reduce((a, e) => a + e.value, 0);
    const headings = q('h1,h2,h3,h4,h5,h6').map((h) => ({ tag: h.tagName, text: text(h).slice(0, 100) }));
    return {
      title: document.title,
      url: location.href,
      h1: q('h1').map((h) => text(h)),
      headings,
      bodyTextLength: document.body.innerText.length,
      links: q('a[href]').length,
      buttons: q('button').length,
      forms: q('form').length,
      images: imgs.length,
      imagesMissingAlt: imgs.filter((i) => !i.getAttribute('alt')).length,
      iframes: q('iframe').length,
      canvases: q('canvas').length,
      svgs: q('svg').length,
      horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth + 2,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      offscreen: overflow,
      smallText,
      unlabeledInteractive: unlabeled,
      inputs: inputs.length,
      unlabelledInputs,
      nav: nav ? {
        dcl: Math.round(nav.domContentLoadedEventEnd),
        load: Math.round(nav.loadEventEnd),
        ttfb: Math.round(nav.responseStart),
        transfer: nav.transferSize,
      } : null,
      lcp: lcp ? Math.round(lcp.startTime) : null,
      cls: Math.round(cls * 1000) / 1000,
      domNodes: document.querySelectorAll('*').length,
    };
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const summary = [];
  for (const [route, role, slug] of routes) {
    const dir = path.join(OUT, slug);
    fs.mkdirSync(dir, { recursive: true });
    const result = { route, role, slug, consoleErrors: [], pageErrors: [], failedRequests: [], httpErrors: [], redirects: [] };
    let context;
    try {
      context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
      const c = cookieFor(role);
      if (c) await context.addCookies([c]);
      const page = await context.newPage();
      page.on('console', (m) => { if (m.type() === 'error') result.consoleErrors.push(m.text().slice(0, 500)); });
      page.on('pageerror', (e) => result.pageErrors.push(String(e).slice(0, 500)));
      page.on('requestfailed', (r) => result.failedRequests.push({ url: r.url().slice(0, 300), err: r.failure()?.errorText }));
      page.on('response', (r) => {
        if (r.status() >= 400 && ['document', 'xhr', 'fetch'].includes(r.request().resourceType())) {
          result.httpErrors.push({ status: r.status(), url: r.url().slice(0, 300), type: r.request().resourceType() });
        }
      });
      const resp = await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch((e) => { result.gotoError = String(e); return null; });
      result.status = resp ? resp.status() : null;
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(1800);
      result.finalUrl = page.url();
      result.redirected = page.url() !== BASE + route;
      result.metrics = await metrics(page);
      await page.screenshot({ path: path.join(dir, 'desktop.png'), fullPage: true, animations: 'disabled' });
      await context.close();

      // Mobile pass with the same auth cookie.
      context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
      if (c) await context.addCookies([c]);
      const mp = await context.newPage();
      await mp.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
      await mp.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await mp.waitForTimeout(1200);
      result.mobile = await metrics(mp);
      await mp.screenshot({ path: path.join(dir, 'mobile.png'), fullPage: true, animations: 'disabled' });
      await context.close();
    } catch (e) {
      result.error = String(e).slice(0, 1000);
      if (context) await context.close().catch(() => {});
    }
    fs.writeFileSync(path.join(dir, 'report.json'), JSON.stringify(result, null, 2));
    summary.push(result);
    console.log(`${slug} ${result.status || '-'} ${result.finalUrl || ''} ${result.error ? 'ERR' : ''}`);
  }
  await browser.close();
  fs.writeFileSync(path.join(OUT, 'summary.json'), JSON.stringify(summary, null, 2));
  console.log('summary', path.join(OUT, 'summary.json'));
})();
