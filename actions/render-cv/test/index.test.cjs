'use strict'

const assert = require('node:assert/strict')
const { lstat, mkdir, mkdtemp, readFile, rm, symlink, writeFile } = require('node:fs/promises')
const http = require('node:http')
const { tmpdir } = require('node:os')
const { join } = require('node:path')
const test = require('node:test')

const { readLatexSource, renderCv, sameOriginUrl, validatedApiUrl, workspacePath } = require('../index.js')

const JOB_ID = 'b5e2f326-618b-4c43-9451-0272fb610da2'

test('source metadata and bounded content use one descriptor, even if it grows', async () => {
  let closes = 0
  let reads = 0
  const handle = {
    stat: async () => ({ isFile: () => true, size: 1 }),
    read: async (buffer, offset, length, position) => {
      assert.equal(position, offset)
      reads += 1
      buffer.fill('x', offset, offset + length)
      return { bytesRead: length }
    },
    close: async () => { closes += 1 },
  }
  await assert.rejects(readLatexSource('/replaced-path', async () => handle), /500,000-byte limit/)
  assert.equal(reads, 1)
  assert.equal(closes, 1)
})

test('source reads tolerate partial reads and close rejected descriptors', async () => {
  const data = Buffer.from('source')
  let closes = 0
  const handle = {
    stat: async () => ({ isFile: () => true, size: data.length }),
    read: async (buffer, offset, _length, position) => {
      const bytesRead = data.copy(buffer, offset, position, position + 2)
      return { bytesRead }
    },
    close: async () => { closes += 1 },
  }
  assert.equal(await readLatexSource('/source', async () => handle), 'source')
  await assert.rejects(readLatexSource('/directory', async () => ({
    ...handle, stat: async () => ({ isFile: () => false }),
  })), /regular file/)
  assert.equal(closes, 2)
})

test('validates API transport and workspace boundaries', () => {
  assert.equal(validatedApiUrl('https://api.example.test/base/').href, 'https://api.example.test/base')
  assert.equal(validatedApiUrl('http://127.0.0.1:8030').href, 'http://127.0.0.1:8030/')
  assert.throws(() => validatedApiUrl('http://api.example.test'), /HTTPS/)
  assert.throws(() => workspacePath('/tmp/work', '../secret', 'source'), /GITHUB_WORKSPACE/)
  const base = new URL('https://api.example.test')
  assert.equal(sameOriginUrl('/api/v1/jobs/1', base, 'poll_url').href, 'https://api.example.test/api/v1/jobs/1')
  assert.throws(() => sameOriginUrl('https://attacker.example/jobs/1', base, 'poll_url'), /configured Latexy API origin/)
})

test('compiles, polls, and atomically writes the returned PDF', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'latexy-action-'))
  const sourcePath = join(workspace, 'resume.tex')
  const outputPath = join(workspace, 'artifacts', 'resume.pdf')
  await writeFile(sourcePath, '\\documentclass{article}\\begin{document}Hello\\end{document}')
  const requests = []
  let polls = 0
  const pdf = Buffer.from('%PDF-1.7\nmock pdf\n%%EOF\n')
  const server = http.createServer(async (request, response) => {
    const body = []
    for await (const chunk of request) body.push(chunk)
    requests.push({ method: request.method, url: request.url, authorization: request.headers.authorization, body: Buffer.concat(body).toString() })
    response.setHeader('content-type', 'application/json')
    if (request.url === '/api/v1/compile') {
      response.end(JSON.stringify({ job_id: JOB_ID, status: 'queued', poll_url: `/api/v1/jobs/${JOB_ID}` }))
    } else if (request.url === `/api/v1/jobs/${JOB_ID}`) {
      polls += 1
      response.end(JSON.stringify(
        polls === 1
          ? { job_id: JOB_ID, status: 'processing', stage: 'latex_compilation' }
          : { job_id: JOB_ID, status: 'completed', pdf_url: `/api/v1/jobs/${JOB_ID}/pdf` },
      ))
    } else if (request.url === `/api/v1/jobs/${JOB_ID}/pdf`) {
      response.setHeader('content-type', 'application/pdf')
      response.end(pdf)
    } else {
      response.statusCode = 404
      response.end('{}')
    }
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))

  try {
    const address = server.address()
    const result = await renderCv({
      apiKey: 'lx_sk_secret',
      apiUrl: new URL(`http://127.0.0.1:${address.port}`),
      workspaceRoot: workspace,
      sourcePath,
      outputPath,
      compiler: 'lualatex',
      timeoutSeconds: 10,
      pollIntervalMs: 1,
    })
    assert.deepEqual(result, { jobId: JOB_ID, pdfPath: outputPath, bytes: pdf.length })
    assert.deepEqual(await readFile(outputPath), pdf)
    assert.equal(requests.length, 4)
    assert.ok(requests.every((request) => request.authorization === 'Bearer lx_sk_secret'))
    assert.deepEqual(JSON.parse(requests[0].body), {
      latex_content: '\\documentclass{article}\\begin{document}Hello\\end{document}',
      compiler: 'lualatex',
    })
  } finally {
    server.closeAllConnections()
    await new Promise((resolve) => server.close(resolve))
    await rm(workspace, { recursive: true, force: true })
  }
})

test('does not replace output with a non-PDF response', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'latexy-action-invalid-'))
  const sourcePath = join(workspace, 'resume.tex')
  const outputPath = join(workspace, 'resume.pdf')
  await writeFile(sourcePath, 'source')
  await writeFile(outputPath, 'previous')
  const responses = [
    new Response(JSON.stringify({ job_id: JOB_ID, poll_url: '/jobs/1' }), { status: 200 }),
    new Response(JSON.stringify({ status: 'completed', pdf_url: '/jobs/1/pdf' }), { status: 200 }),
    new Response('not a pdf', { status: 200 }),
  ]
  try {
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), sourcePath, outputPath,
        workspaceRoot: workspace,
        compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
      }, { fetchImpl: async () => responses.shift(), sleep: async () => {} }),
      /valid PDF header/,
    )
    assert.equal(await readFile(outputPath, 'utf8'), 'previous')
  } finally {
    await rm(workspace, { recursive: true, force: true })
  }
})

test('rejects a cross-origin server URL before sending the API key', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'latexy-action-origin-'))
  const sourcePath = join(workspace, 'resume.tex')
  await writeFile(sourcePath, 'source')
  let calls = 0
  try {
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), sourcePath,
        workspaceRoot: workspace,
        outputPath: join(workspace, 'resume.pdf'), compiler: 'pdflatex',
        timeoutSeconds: 10, pollIntervalMs: 1,
      }, {
        fetchImpl: async () => {
          calls += 1
          return new Response(JSON.stringify({
            job_id: JOB_ID,
            poll_url: 'https://attacker.example/steal',
          }), { status: 200 })
        },
      }),
      /configured Latexy API origin/,
    )
    assert.equal(calls, 1)
  } finally {
    await rm(workspace, { recursive: true, force: true })
  }
})

test('canonicalizes internal source links and rejects external workspace links', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'latexy-action-links-'))
  const outside = await mkdtemp(join(tmpdir(), 'latexy-action-links-outside-'))
  const jobId = JOB_ID
  const pdf = Buffer.from('%PDF-1.7\nlink test\n')
  try {
    const targetSource = join(workspace, 'docs', 'resume.tex')
    const linkedSource = join(workspace, 'resume-link.tex')
    const outputDirectory = join(workspace, 'real-artifacts')
    const outputLink = join(workspace, 'artifacts')
    const workspaceAlias = join(outside, 'workspace-link')
    await mkdir(join(workspace, 'docs'), { recursive: true })
    await mkdir(outputDirectory, { recursive: true })
    await writeFile(targetSource, 'internal source')
    await symlink(targetSource, linkedSource)
    await symlink(outputDirectory, outputLink, 'dir')
    await symlink(workspace, workspaceAlias, 'dir')
    const outputPath = join(workspaceAlias, 'artifacts', 'resume.pdf')
    const responses = [
      new Response(JSON.stringify({ job_id: jobId, poll_url: `/api/v1/jobs/${jobId}` })),
      new Response(JSON.stringify({ status: 'completed', pdf_url: `/api/v1/jobs/${jobId}/pdf` })),
      new Response(pdf),
    ]
    await renderCv({
      apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspaceAlias,
      sourcePath: join(workspaceAlias, 'resume-link.tex'), outputPath, compiler: 'pdflatex', timeoutSeconds: 10,
      pollIntervalMs: 1,
    }, { fetchImpl: async () => responses.shift(), sleep: async () => {} })
    assert.deepEqual(await readFile(join(outputDirectory, 'resume.pdf')), pdf)

    const externalSource = join(workspace, 'external-link.tex')
    await writeFile(join(outside, 'secret.tex'), 'external source')
    await symlink(join(outside, 'secret.tex'), externalSource)
    let calls = 0
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspace,
        sourcePath: externalSource, outputPath: join(workspace, 'rejected.pdf'),
        compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
      }, { fetchImpl: async () => { calls += 1; return new Response('{}') } }),
      /source must stay inside GITHUB_WORKSPACE/,
    )
    assert.equal(calls, 0)

    const externalOutputDirectory = join(workspace, 'output-link')
    await symlink(outside, externalOutputDirectory)
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspace,
        sourcePath: targetSource, outputPath: join(externalOutputDirectory, 'nested', 'rejected.pdf'),
        compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
      }, { fetchImpl: async () => { calls += 1; return new Response('{}') } }),
      /output must stay inside GITHUB_WORKSPACE/,
    )
    assert.equal(calls, 0)
    await assert.rejects(lstat(join(outside, 'nested')))
    await assert.rejects(lstat(join(outside, 'rejected.pdf')))

    const regularOutputParent = join(workspace, 'output-file')
    await writeFile(regularOutputParent, 'not a directory')
    calls = 0
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspace,
        sourcePath: targetSource, outputPath: join(regularOutputParent, 'rejected.pdf'),
        compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
      }, { fetchImpl: async () => { calls += 1; return new Response('{}') } }),
      /output parent must be a directory/,
    )
    assert.equal(calls, 0)

    const danglingOutputParent = join(workspace, 'dangling-output-link')
    await symlink(join(outside, 'missing-output-target'), danglingOutputParent)
    calls = 0
    await assert.rejects(
      renderCv({
        apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspace,
        sourcePath: targetSource, outputPath: join(danglingOutputParent, 'nested', 'rejected.pdf'),
        compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
      }, { fetchImpl: async () => { calls += 1; return new Response('{}') } }),
      /output parent contains a dangling symlink/,
    )
    assert.equal(calls, 0)
  } finally {
    await rm(workspace, { recursive: true, force: true })
    await rm(outside, { recursive: true, force: true })
  }
})

test('replaces an existing final output symlink without following it', async () => {
  const workspace = await mkdtemp(join(tmpdir(), 'latexy-action-output-link-'))
  const outside = await mkdtemp(join(tmpdir(), 'latexy-action-output-link-outside-'))
  const jobId = JOB_ID
  const pdf = Buffer.from('%PDF-1.7\nreplacement\n')
  try {
    const sourcePath = join(workspace, 'resume.tex')
    const outputPath = join(workspace, 'resume.pdf')
    const outsideTarget = join(outside, 'target.pdf')
    await writeFile(sourcePath, 'source')
    await writeFile(outsideTarget, 'old external output')
    await symlink(outsideTarget, outputPath)
    const responses = [
      new Response(JSON.stringify({ job_id: jobId, poll_url: `/api/v1/jobs/${jobId}` })),
      new Response(JSON.stringify({ status: 'completed', pdf_url: `/api/v1/jobs/${jobId}/pdf` })),
      new Response(pdf),
    ]
    await renderCv({
      apiKey: 'key', apiUrl: new URL('https://api.example.test'), workspaceRoot: workspace,
      sourcePath, outputPath, compiler: 'pdflatex', timeoutSeconds: 10, pollIntervalMs: 1,
    }, { fetchImpl: async () => responses.shift(), sleep: async () => {} })
    assert.deepEqual(await readFile(outsideTarget, 'utf8'), 'old external output')
    assert.equal((await lstat(outputPath)).isSymbolicLink(), false)
    assert.deepEqual(await readFile(outputPath), pdf)
  } finally {
    await rm(workspace, { recursive: true, force: true })
    await rm(outside, { recursive: true, force: true })
  }
})
