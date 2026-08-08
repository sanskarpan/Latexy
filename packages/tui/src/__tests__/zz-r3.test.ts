/** TEMPORARY audit probe round 3. Delete after run. */
import { describe, it } from 'vitest'
import http from 'node:http'

import { dispatch } from '../commands/dispatch.js'
import { ApiClient, ApiError, initApiClient, getApiClient } from '../lib/api-client.js'
import { pickPending, settlePick } from '../lib/pick.js'
import { $messages, clearMessages, $activeJobId } from '../stores/messages.js'
import { closeOverlay } from '../stores/overlay.js'
import { $session } from '../stores/session.js'
import { busyWithAnotherJob, claimJobSlot, releaseJobSlot } from '../tools/shared.js'

const API = process.env['LATEXY_API_URL'] ?? 'http://localhost:8030'
const TOKEN = process.env['LATEXY_SESSION_TOKEN'] ?? ''
const RESUME = process.env['LATEXY_TEST_RESUME'] ?? ''

function transcript(): string {
  return $messages.get().map(m =>
    `[${m.role}] ${m.content ?? ''}${m.toolName ? ` tool=${m.toolName} state=${m.toolState}` : ''}` +
    `${m.toolResult != null ? ' result=' + JSON.stringify(m.toolResult) : ''}`,
  ).join('\n')
}
function show(t: string, out: string): void {
  console.log(`\n╔══ ${t}\n${out.split('\n').map(l => '║ ' + l).join('\n')}\n╚══`)
}
function auth(url = API, tok = TOKEN): void {
  $session.set({
    ...$session.get(), token: tok, backendUrl: url,
    wsUrl: url.replace(/^http/, 'ws') + '/ws/jobs', isAuthenticated: true, plan: 'pro',
  })
  initApiClient(url, tok)
}
async function run(input: string, ms = 3500, pickWith?: string): Promise<string> {
  clearMessages(); closeOverlay()
  const call = dispatch(input).catch(e => console.log('THREW:', String(e)))
  await new Promise(r => setTimeout(r, 300))
  if (pickPending()) settlePick(pickWith ?? RESUME)
  await Promise.race([call, new Promise(r => setTimeout(r, ms))])
  return transcript()
}

describe('round 3', () => {

  // ═══════ A. JOB SLOT — try to wedge it ═══════
  it('A1: /cover releases a slot it never claimed', async () => {
    auth(); $activeJobId.set(null); releaseJobSlot()
    console.log('slot busy at start?', busyWithAnotherJob())
    const claimed = claimJobSlot()          // pretend /optimize is mid-flight
    console.log('simulated /optimize claimed slot:', claimed, '| busy now?', busyWithAnotherJob())
    clearMessages(); closeOverlay()
    // /cover with no id -> picker -> user presses Esc -> `if (!resumeId) { releaseJobSlot(); return }`
    const call = dispatch('/cover').catch(() => {})
    await new Promise(r => setTimeout(r, 900))
    if (pickPending()) settlePick(null)
    await Promise.race([call, new Promise(r => setTimeout(r, 3000))])
    console.log('AFTER /cover cancelled its picker — slot still held?', busyWithAnotherJob())
    console.log('  (a slot claimed by /optimize has been released by /cover)')
    releaseJobSlot(); $activeJobId.set(null)
  })

  it('A2: /compile does not participate in the slot at all', async () => {
    auth(); $activeJobId.set(null); releaseJobSlot()
    const real = globalThis.fetch
    const submits: string[] = []
    globalThis.fetch = ((u: RequestInfo | URL, i?: RequestInit) => {
      const s = String(u)
      if (s.includes('/jobs/submit') || s.includes('/ats/deep-analyze')) submits.push(s.split('8030')[1] ?? s)
      return real(u as never, i as never)
    }) as typeof fetch
    try {
      clearMessages(); closeOverlay()
      // two /compile dispatched together
      await Promise.race([
        Promise.all([
          dispatch(`/compile ${RESUME}`).catch(() => {}),
          dispatch(`/compile ${RESUME}`).catch(() => {}),
        ]),
        new Promise(r => setTimeout(r, 8000)),
      ])
      console.log('two /compile together -> submissions:', submits.length, submits)
      show('two /compile dispatched together', transcript())
      // now: /compile + /optimize together, from a clean slot
      $activeJobId.set(null); releaseJobSlot(); submits.length = 0; clearMessages()
      await Promise.race([
        Promise.all([
          dispatch(`/compile ${RESUME}`).catch(() => {}),
          dispatch(`/optimize ${RESUME} --jd "Go engineer"`).catch(() => {}),
        ]),
        new Promise(r => setTimeout(r, 8000)),
      ])
      console.log('/compile + /optimize together -> submissions:', submits.length, submits)
      show('/compile + /optimize dispatched together', transcript())
    } finally { globalThis.fetch = real }
    $activeJobId.set(null); releaseJobSlot()
  })

  it('A3: can the slot get stuck so no job can ever start?', async () => {
    auth(); $activeJobId.set(null); releaseJobSlot()
    // /ats: claimJobSlot() succeeds, then resolveJobDescription/latexOf run.
    // Point the client at a server that 500s so submitJob's POST fails.
    const srv = http.createServer((req, res) => {
      const u = req.url ?? ''
      if (u.startsWith('/resumes/') && req.method === 'GET') {
        res.writeHead(200, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ id: RESUME, title: 'T', latex_content: '\\documentclass{article}\\begin{document}x\\end{document}' }))
      } else { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"detail":"boom"}') }
    })
    await new Promise<void>(r => srv.listen(0, '127.0.0.1', r))
    const port = (srv.address() as { port: number }).port
    auth(`http://127.0.0.1:${port}`, 't')
    show('/ats against a 500 backend', await run(`/ats ${RESUME}`, 8000))
    console.log('slot after failed submit (should be free):', busyWithAnotherJob())
    // Now a path where latexOf ITSELF throws, before submitJob is ever called
    srv.close()
    const srv2 = http.createServer((_req, res) => { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"detail":"resume fetch boom"}') })
    await new Promise<void>(r => srv2.listen(0, '127.0.0.1', r))
    const port2 = (srv2.address() as { port: number }).port
    auth(`http://127.0.0.1:${port2}`, 't')
    $activeJobId.set(null); releaseJobSlot()
    show('/ats where the resume fetch itself 500s', await run(`/ats ${RESUME}`, 12000))
    console.log('slot after latexOf threw (should be free):', busyWithAnotherJob())
    srv2.close(); auth(); $activeJobId.set(null); releaseJobSlot()
  })

  it('A4: slot after a picker cancel on a real job command', async () => {
    auth(); $activeJobId.set(null); releaseJobSlot()
    clearMessages(); closeOverlay()
    const call = dispatch('/optimize --jd "Go engineer"').catch(() => {})
    await new Promise(r => setTimeout(r, 900))
    console.log('picker open?', pickPending())
    if (pickPending()) settlePick(null)
    await Promise.race([call, new Promise(r => setTimeout(r, 3000))])
    console.log('slot after /optimize picker cancelled (should be free):', busyWithAnotherJob())
    // and can a job start afterwards?
    console.log('can claim again?', claimJobSlot()); releaseJobSlot()
    $activeJobId.set(null)
  })

  // ═══════ B. jdFailureReported ═══════
  it('B1: /ats leaves the jd flag set; /interview never clears it', async () => {
    auth(); $activeJobId.set(null); releaseJobSlot()
    const { jdFailureAlreadyReported } = await import('../tools/shared.js')
    // /ats calls resolveJobDescription but never reads the flag
    await run(`/ats ${RESUME} --jd https://example.com/nope`, 8000)
    console.log('flag left set after /ats with a bad --jd URL?', jdFailureAlreadyReported())
    $activeJobId.set(null); releaseJobSlot()
  })

  it('B2: the THROW path in resolveJobDescription still double-reports', async () => {
    // scrape endpoint 500s -> the catch branch fires, which does NOT set the flag
    const srv = http.createServer((req, res) => {
      const u = req.url ?? ''
      if (u.startsWith('/scrape-job-description')) { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"detail":"scraper exploded"}') }
      else if (u.startsWith('/resumes/')) { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ id: RESUME, title: 'T', latex_content: 'x' })) }
      else { res.writeHead(200, { 'Content-Type': 'application/json' }); res.end('{}') }
    })
    await new Promise<void>(r => srv.listen(0, '127.0.0.1', r))
    const port = (srv.address() as { port: number }).port
    auth(`http://127.0.0.1:${port}`, 't'); $activeJobId.set(null); releaseJobSlot()
    show('/optimize --jd <url> where the scraper THROWS', await run(`/optimize ${RESUME} --jd https://example.com/x`, 9000))
    srv.close(); auth(); $activeJobId.set(null); releaseJobSlot()
  })

  // ═══════ C. getBinary ═══════
  it('C1: getBinary retry / abort / binaryError shapes', async () => {
    let hits: Record<string, number> = {}
    const bump = (k: string) => { hits[k] = (hits[k] ?? 0) + 1 }
    const srv = http.createServer((req, res) => {
      const u = (req.url ?? '').split('?')[0] ?? ''
      bump(u)
      if (u === '/ok') { res.writeHead(200, { 'Content-Type': 'application/octet-stream' }); res.end(Buffer.from([1, 2, 3])) }
      else if (u === '/e500') { res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"detail":"boom"}') }
      else if (u === '/e404') { res.writeHead(404, { 'Content-Type': 'application/json' }); res.end('{"error":{"code":"http_error","message":"Resume not found"},"detail":"Resume not found"}') }
      else if (u === '/e401') { res.writeHead(401, { 'Content-Type': 'application/json' }); res.end('{"detail":"Authentication required"}') }
      else if (u === '/e401html') { res.writeHead(401, { 'Content-Type': 'text/html' }); res.end('<html><body>nginx auth wall</body></html>') }
      else if (u === '/e502html') { res.writeHead(502, { 'Content-Type': 'text/html' }); res.end('<html><head><title>502</title></head><body>nginx/1.24.0</body></html>') }
      else if (u === '/nodetail') { res.writeHead(400, { 'Content-Type': 'application/json' }); res.end('{"foo":"bar"}') }
      else if (u === '/emptybody') { res.writeHead(400, { 'Content-Type': 'application/json' }); res.end('') }
      else if (u === '/zero') { res.writeHead(200, { 'Content-Type': 'application/octet-stream' }); res.end() }
      else if (u === '/e429') { res.writeHead(429, { 'Content-Type': 'application/json' }); res.end('{"detail":"Rate limit exceeded"}') }
      else if (u === '/hang') { /* never */ }
      else { res.writeHead(404); res.end('{}') }
    })
    await new Promise<void>(r => srv.listen(0, '127.0.0.1', r))
    const port = (srv.address() as { port: number }).port
    const c = new ApiClient({ baseUrl: `http://127.0.0.1:${port}` }); c.setToken('t')
    const msg = async (p: string): Promise<string> => {
      try { const b = await c.getBinary(p); return `OK ${b.length} bytes` }
      catch (e) { return `${(e as ApiError).name}/${(e as ApiError).status}: ${JSON.stringify((e as ApiError).message)}` }
    }
    for (const p of ['/e404', '/e401', '/e401html', '/e502html', '/nodetail', '/emptybody', '/zero', '/e429']) {
      hits = {}
      console.log(`${p.padEnd(12)} -> ${await msg(p)}   attempts=${JSON.stringify(hits)}`)
    }
    hits = {}; console.log(`/e500        -> ${await msg('/e500')}   attempts=${JSON.stringify(hits)}`)
    hits = {}; console.log(`/ok          -> ${await msg('/ok')}   attempts=${JSON.stringify(hits)}`)

    // abort: already-aborted external signal — does it retry pointlessly?
    hits = {}
    const ac = new AbortController(); ac.abort()
    const t0 = Date.now()
    try { await c.getBinary('/ok', { signal: ac.signal }); console.log('ABORT IGNORED — download completed') }
    catch (e) { console.log(`abort(pre) -> ${String(e).slice(0, 60)} after ${Date.now() - t0}ms attempts=${JSON.stringify(hits)}`) }
    // abort mid-flight against /hang
    hits = {}
    const ac2 = new AbortController()
    const t1 = Date.now()
    setTimeout(() => ac2.abort(), 400)
    try { await c.getBinary('/hang', { signal: ac2.signal, timeoutMs: 30000 }) }
    catch (e) { console.log(`abort(mid) -> ${String(e).slice(0, 60)} after ${Date.now() - t1}ms attempts=${JSON.stringify(hits)}`) }
    srv.close()
  }, 60000)

  // ═══════ D. /edit ═══════
  it('D1: /edit exit codes, EDITOR with args, invalid utf-8, dir swap, unchanged', async () => {
    auth()
    const hdr = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
    const good = '\\documentclass{article}\\begin{document}KEEP THIS CONTENT\\end{document}'
    const { writeFile, mkdir } = await import('node:fs/promises')
    const { tmpdir } = await import('node:os'); const { join } = await import('node:path')
    const dir = join(tmpdir(), 'r3edit'); await mkdir(dir, { recursive: true })
    const saved = process.env['EDITOR']

    const cases: Array<[string, string]> = [
      ['clean exit, real edit', '#!/bin/sh\nprintf "\\\\documentclass{article}\\\\begin{document}EDITED OK\\\\end{document}" > "$1"\nexit 0\n'],
      ['truncate + exit 3', '#!/bin/sh\n: > "$1"\nexit 3\n'],
      ['truncate + SIGTERM', '#!/bin/sh\n: > "$1"\nkill -TERM $$\n'],
      ['clean exit, emptied file', '#!/bin/sh\n: > "$1"\nexit 0\n'],
      ['clean exit, whitespace only', '#!/bin/sh\nprintf "   \\n\\t\\n" > "$1"\nexit 0\n'],
      ['clean exit, INVALID UTF-8', '#!/bin/sh\nprintf "\\\\documentclass{article}" > "$1"\nprintf "\\\\377\\\\376\\\\377" >> "$1"\nexit 0\n'],
      ['clean exit, file replaced by a DIRECTORY', '#!/bin/sh\nrm -f "$1"\nmkdir -p "$1"\nexit 0\n'],
      ['clean exit, no modification at all', '#!/bin/sh\nexit 0\n'],
    ]
    for (const [name, script] of cases) {
      await fetch(`${API}/resumes/${RESUME}`, { method: 'PUT', headers: hdr, body: JSON.stringify({ latex_content: good }) })
      const f = join(dir, name.replace(/\W+/g, '_') + '.sh')
      await writeFile(f, script, { mode: 0o755 })
      process.env['EDITOR'] = f
      const out = await run(`/edit ${RESUME}`, 6000)
      const after = await (await fetch(`${API}/resumes/${RESUME}`, { headers: hdr })).json() as { latex_content: string }
      const changed = after.latex_content !== good
      console.log(`\nEDITOR ${name}`)
      console.log('  TUI :', out.split('\n').filter(l => !l.startsWith('[user]')).join(' // '))
      console.log('  content:', JSON.stringify(after.latex_content).slice(0, 90), '| CHANGED:', changed)
    }
    // $EDITOR containing arguments, e.g. "code --wait"
    process.env['EDITOR'] = 'sh -c'
    console.log('\nEDITOR="sh -c" (an editor with arguments):')
    console.log('  ', (await run(`/edit ${RESUME}`, 6000)).split('\n').filter(l => !l.startsWith('[user]')).join(' // '))
    process.env['EDITOR'] = 'code --wait'
    console.log('EDITOR="code --wait":')
    console.log('  ', (await run(`/edit ${RESUME}`, 6000)).split('\n').filter(l => !l.startsWith('[user]')).join(' // '))

    if (saved != null) process.env['EDITOR'] = saved; else delete process.env['EDITOR']
    await fetch(`${API}/resumes/${RESUME}`, { method: 'PUT', headers: hdr, body: JSON.stringify({ latex_content: good }) })
  }, 90000)

  // ═══════ E. /diff ═══════
  it('E1: /diff with 500 changed lines, identical, no parent, prefix-looking content', async () => {
    auth()
    const hdr = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
    const mk = async (parent: string, child: string): Promise<string> => {
      await fetch(`${API}/resumes/${RESUME}`, { method: 'PUT', headers: hdr, body: JSON.stringify({ latex_content: parent }) })
      const v = await (await fetch(`${API}/resumes/${RESUME}/fork`, { method: 'POST', headers: hdr, body: JSON.stringify({ title: 'DiffV' }) })).json() as { id: string }
      await fetch(`${API}/resumes/${v.id}`, { method: 'PUT', headers: hdr, body: JSON.stringify({ latex_content: child }) })
      return v.id
    }
    const body = (n: number, w: string) => Array.from({ length: n }, (_, i) => `\\item ${w} bullet ${i}`).join('\n')

    // 500 changed lines
    let v = await mk(body(500, 'Parent'), body(500, 'Variant'))
    let out = await run(`/diff ${v}`, 5000, v)
    const sys = $messages.get().find(m => m.role === 'system')?.content ?? ''
    const ls = sys.split('\n')
    console.log(`\n500-line diff: message has ${ls.length} lines`)
    console.log('  header  :', JSON.stringify(ls.slice(0, 4)))
    console.log('  removals shown:', ls.filter(l => l.startsWith('- ')).length, '| additions shown:', ls.filter(l => l.startsWith('+ ')).length)
    console.log('  last line:', JSON.stringify(ls[ls.length - 1]))
    await fetch(`${API}/resumes/${v}`, { method: 'DELETE', headers: hdr })

    // identical
    v = await mk(body(5, 'Same'), body(5, 'Same'))
    console.log('\nidentical:', (await run(`/diff ${v}`, 4000, v)).split('\n').filter(l => !l.startsWith('[user]')).join(''))
    await fetch(`${API}/resumes/${v}`, { method: 'DELETE', headers: hdr })

    // content that already looks like diff markers
    v = await mk('- old bullet\n+ plus line\n--- header line', '- new bullet\n+ plus line\n+++ other')
    out = await run(`/diff ${v}`, 4000, v)
    console.log('\ncontent containing -/+/---/+++ markers:')
    console.log(($messages.get().find(m => m.role === 'system')?.content ?? '').split('\n').map(l => '   ' + JSON.stringify(l)).join('\n'))
    await fetch(`${API}/resumes/${v}`, { method: 'DELETE', headers: hdr })

    // reordered only
    v = await mk('alpha\nbeta\ngamma', 'gamma\nbeta\nalpha')
    console.log('\nreordered only:', JSON.stringify(($messages.get().find(m => m.role === 'system')?.content ?? '')))
    out = await run(`/diff ${v}`, 4000, v)
    console.log('   ->', JSON.stringify(($messages.get().find(m => m.role === 'system')?.content ?? '')))
    await fetch(`${API}/resumes/${v}`, { method: 'DELETE', headers: hdr })

    // no parent
    console.log('\nno parent:', (await run(`/diff ${RESUME}`, 4000)).split('\n').filter(l => !l.startsWith('[user]')).join(''))
    void out
  }, 120000)

  // ═══════ F. re-confirm the 7 round-2 fixes ═══════
  it('F: re-confirm round-2 fixes', async () => {
    auth()
    const hdr = { Authorization: `Bearer ${TOKEN}`, 'Content-Type': 'application/json' }
    await fetch(`${API}/resumes/${RESUME}`, { method: 'PUT', headers: hdr, body: JSON.stringify({ latex_content: '\\documentclass{article}\\begin{document}\\section*{A}Go and Kubernetes.\\end{document}' }) })
    const { execSync } = await import('node:child_process')
    show('R2#4 /export docx (must be valid + nonzero)', await run(`/export ${RESUME} --format docx`, 9000))
    try {
      execSync(`unzip -t resume-${RESUME.slice(0, 8)}.docx > /dev/null 2>&1`); console.log('   docx unzip: VALID')
    } catch { console.log('   docx unzip: CORRUPT') }
    show('R2#3 /export bad fmt (must be a clean message, no JSON envelope)', await run(`/export ${RESUME} --format markdown`, 6000))
    show('R2#3 /pdf ghost (clean message)', await run('/pdf 00000000-0000-4000-8000-000000000000', 8000))
    show('R2#7 --jd url failure (ONE message only)', await run(`/cover ${RESUME} --jd https://example.com/job`, 8000))
    show('R2#6 /diff no-parent', await run(`/diff ${RESUME}`, 5000))
  }, 90000)
})
