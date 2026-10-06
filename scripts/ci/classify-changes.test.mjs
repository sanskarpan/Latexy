import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, readFileSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { execFileSync, spawnSync } from 'node:child_process'
import { describe, test } from 'node:test'

import {
  SCOPE_KEYS,
  classifyChanges,
  classifyDiffOutputs,
  classifyEvent,
  classifyPaths,
} from './classify-changes.mjs'

function expected(...enabled) {
  return Object.fromEntries(SCOPE_KEYS.map((key) => [key, enabled.includes(key)]))
}

function git(repo, args) {
  return execFileSync('git', args, {
    cwd: repo,
    encoding: 'utf8',
    env: {
      ...process.env,
      GIT_AUTHOR_NAME: 'CI scope test',
      GIT_AUTHOR_EMAIL: 'ci-scope@example.invalid',
      GIT_COMMITTER_NAME: 'CI scope test',
      GIT_COMMITTER_EMAIL: 'ci-scope@example.invalid',
    },
  }).trim()
}

function makeRepo() {
  const repo = mkdtempSync(join(tmpdir(), 'latexy-ci-scope-'))
  git(repo, ['init', '-q'])
  git(repo, ['config', 'user.name', 'CI scope test'])
  git(repo, ['config', 'user.email', 'ci-scope@example.invalid'])
  writeFileSync(join(repo, 'README.md'), 'base\n')
  git(repo, ['add', 'README.md'])
  git(repo, ['commit', '-qm', 'base'])
  return repo
}

describe('pure changed-file classification', () => {
  test('docs-only prose and known assets skip expensive jobs', () => {
    assert.deepEqual(classifyPaths(['README.md', 'docs/qa/release-notes.md', 'legal/logo.png']), expected())
  })

  test('executable/configuration files under prose trees fail closed', () => {
    assert.deepEqual(classifyPaths(['docs/verify.py']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['legal/policy.yml']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['features-checklist/runner.ts']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docs/embedded.mdx']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docs/Makefile']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docs/diagram.svg']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docs\\runner.md']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['/docs/runner.md']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docs/../frontend/src/App.tsx']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['frontend/src/README.md']), expected('frontend'))
  })

  test('ordinary component folders stay narrow', () => {
    assert.deepEqual(classifyPaths(['backend/app/services/worker.py']), expected('backend'))
    assert.deepEqual(classifyPaths(['frontend/src/components/Card.tsx']), expected('frontend'))
    assert.deepEqual(classifyPaths(['packages/tui/src/cli.tsx']), expected('tui'))
    assert.deepEqual(classifyPaths(['packages/browser-extension/popup.js']), expected('extension'))
    assert.deepEqual(classifyPaths(['actions/render-cv/index.js']), expected('render_cv'))
    assert.deepEqual(classifyPaths(['monitoring/prometheus.yml']), expected('observability'))
  })

  test('auth/schema words in TUI and extension paths do not become backend contracts', () => {
    assert.deepEqual(classifyPaths(['packages/tui/src/commands/auth.js']), expected('tui'))
    assert.deepEqual(classifyPaths(['packages/browser-extension/src/auth-schema.js']), expected('extension'))
  })

  test('public API/auth/shared-contract paths cover both app sides', () => {
    const cross = expected('backend', 'frontend', 'full_stack')
    assert.deepEqual(classifyPaths(['frontend/src/lib/api-client.ts']), cross)
    assert.deepEqual(classifyPaths(['frontend/src/app/api/deployment-identity/route.ts']), cross)
    assert.deepEqual(classifyPaths(['backend/app/api/routes.py']), cross)
    assert.deepEqual(classifyPaths(['backend/app/models/schemas.py']), cross)
    assert.deepEqual(classifyPaths(['backend/database/models.py']), cross)
  })

  test('known backend runtime and dependency paths avoid unrelated workspace jobs', () => {
    const runtime = expected('backend', 'frontend', 'full_stack')
    for (const path of [
      'backend/requirements.txt',
      'backend/requirements.lock',
      'backend/alembic/versions/0001_initial.py',
      'backend/modal_app.py',
      'backend/Dockerfile.prod',
      'backend/app/core/config.py',
      'backend/app/database/connection.py',
      'backend/app/main.py',
    ]) {
      assert.deepEqual(classifyPaths([path]), runtime, path)
    }
    assert.deepEqual(
      classifyPaths(['backend/scripts/verify-template-extraction.sh']),
      expected('backend', 'frontend', 'templates', 'full_stack'),
    )
    assert.deepEqual(
      classifyPaths(['backend/app/scripts/compile_templates.py']),
      expected('backend', 'frontend', 'templates', 'full_stack'),
    )
  })

  test('templates include backend and full-stack asset checks', () => {
    assert.deepEqual(
      classifyPaths(['backend/app/data/templates/presentation/example.tex']),
      expected('backend', 'frontend', 'templates', 'full_stack'),
    )
  })

  test('shared JavaScript lock/config covers every JavaScript workspace', () => {
    const shared = expected('frontend', 'tui', 'extension', 'full_stack')
    assert.deepEqual(classifyPaths(['pnpm-lock.yaml']), shared)
    assert.deepEqual(classifyPaths(['package.json']), shared)
    assert.deepEqual(classifyPaths(['patches/braces@3.0.3.patch']), shared)
  })

  test('workflow, CI, deployment, and unknown paths select every gate', () => {
    assert.deepEqual(classifyPaths(['.github/workflows/ci.yml']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['scripts/ci/new-check.mjs']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['docker-compose.prod.yml']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['future-tool/config.toml']), expected(...SCOPE_KEYS))
  })

  test('generated frontend artifacts cannot masquerade as docs-only changes', () => {
    assert.deepEqual(classifyPaths(['frontend/playwright-report/index.html']), expected('frontend'))
    assert.deepEqual(classifyPaths(['frontend/tsconfig.tsbuildinfo']), expected('frontend'))
  })

  test('mixed paths union scopes and malformed input fails closed', () => {
    assert.deepEqual(classifyPaths(['frontend/src/App.tsx', 'packages/tui/src/cli.tsx']), expected('frontend', 'tui'))
    assert.deepEqual(classifyPaths([]), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['']), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyPaths(['frontend/src/a\0b.ts']), expected(...SCOPE_KEYS))
  })

  test('deletions, additions, newline names, renames, and type metadata are conservative', () => {
    const outputs = classifyDiffOutputs(
      'D\0frontend/src/old.ts\0A\0backend/app/services/new.py\0',
      ':100644 000000 aaaaaaa 0000000 D\0frontend/src/old.ts\0' +
        ':000000 100644 0000000 bbbbbbb A\0backend/app/services/new.py\0',
    )
    assert.deepEqual(outputs, expected('backend', 'frontend'))
    assert.deepEqual(
      classifyDiffOutputs('M\0frontend/src/name\nwith-newline.ts\0', ':100644 100644 aaaaaaa bbbbbbb M\0frontend/src/name\nwith-newline.ts\0'),
      expected('frontend'),
    )
    assert.deepEqual(classifyChanges([{ status: 'T', path: 'frontend/src/file.ts' }]), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyChanges([{ status: 'M', path: 'frontend/link', newMode: '120000' }]), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyChanges([{ status: 'A', path: 'packages/submodule', newMode: '160000' }]), expected(...SCOPE_KEYS))
    assert.deepEqual(classifyChanges([{ status: 'R', path: 'frontend/new.ts', oldPath: 'backend/old.py' }]), expected('backend', 'frontend'))
    assert.deepEqual(
      classifyDiffOutputs('M\0frontend/src/a.ts\0garbage', ':100644 100644 aaaaaaa bbbbbbb M\0frontend/src/a.ts\0'),
      expected(...SCOPE_KEYS),
    )
    assert.deepEqual(
      classifyDiffOutputs('M\0frontend/src/a.ts\0', ':100644 100644 aaaaaaa bbbbbbb M\0backend/app/other.py\0'),
      expected(...SCOPE_KEYS),
    )
  })
})

describe('event and Git range handling', () => {
  test('actual docs-only Git range skips suites, but moving code into docs retains its old scope', () => {
    const repo = makeRepo()
    const before = git(repo, ['rev-parse', 'HEAD'])
    writeFileSync(join(repo, 'README.md'), 'updated documentation\n')
    git(repo, ['add', 'README.md'])
    git(repo, ['commit', '-qm', 'docs only'])
    const docsHead = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before, after: docsHead } }), expected())
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'pull_request', event: { pull_request: { base: { sha: before }, head: { sha: docsHead } } } }), expected())
    mkdirSync(join(repo, 'frontend'), { recursive: true })
    writeFileSync(join(repo, 'frontend', 'README.md'), 'component documentation\n')
    git(repo, ['add', 'frontend/README.md'])
    git(repo, ['commit', '-qm', 'component file'])
    const renameBase = git(repo, ['rev-parse', 'HEAD'])
    mkdirSync(join(repo, 'docs'), { recursive: true })
    git(repo, ['mv', 'frontend/README.md', 'docs/component.md'])
    git(repo, ['commit', '-qm', 'move to docs'])
    const renameHead = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before: renameBase, after: renameHead } }), expected('frontend'))
  })

  test('push uses before/after and classifies the actual changed range', () => {
    const repo = makeRepo()
    const before = git(repo, ['rev-parse', 'HEAD'])
    mkdirSync(join(repo, 'frontend', 'src'), { recursive: true })
    writeFileSync(join(repo, 'frontend/src/new.ts'), 'export const value = 1\n')
    git(repo, ['add', 'frontend/src/new.ts'])
    git(repo, ['commit', '-qm', 'frontend'])
    const after = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before, after } }), expected('frontend'))
  })

  test('force-pushed push ranges use two-dot and retain divergent deletions', () => {
    const repo = makeRepo()
    const common = git(repo, ['rev-parse', 'HEAD'])
    mkdirSync(join(repo, 'backend'), { recursive: true })
    writeFileSync(join(repo, 'backend/old.py'), 'old = True\n')
    git(repo, ['add', 'backend/old.py'])
    git(repo, ['commit', '-qm', 'old branch'])
    const before = git(repo, ['rev-parse', 'HEAD'])
    git(repo, ['checkout', '-qb', 'new-branch', common])
    mkdirSync(join(repo, 'frontend'), { recursive: true })
    writeFileSync(join(repo, 'frontend/new.ts'), 'export const next = true\n')
    git(repo, ['add', 'frontend/new.ts'])
    git(repo, ['commit', '-qm', 'new branch'])
    const after = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before, after } }), expected('backend', 'frontend'))
  })

  test('pull requests use three-dot merge-base, not a moving base tip', () => {
    const repo = makeRepo()
    const common = git(repo, ['rev-parse', 'HEAD'])
    git(repo, ['branch', 'base'])
    git(repo, ['checkout', '-qb', 'feature'])
    mkdirSync(join(repo, 'frontend', 'src'), { recursive: true })
    writeFileSync(join(repo, 'frontend/src/feature.ts'), 'export const feature = true\n')
    git(repo, ['add', 'frontend/src/feature.ts'])
    git(repo, ['commit', '-qm', 'feature'])
    const head = git(repo, ['rev-parse', 'HEAD'])
    git(repo, ['checkout', '-q', 'base'])
    mkdirSync(join(repo, 'backend', 'app'), { recursive: true })
    writeFileSync(join(repo, 'backend/app/base.py'), 'base = True\n')
    git(repo, ['add', 'backend/app/base.py'])
    git(repo, ['commit', '-qm', 'base moved'])
    const base = git(repo, ['rev-parse', 'HEAD'])
    assert.equal(common.length, 40)
    assert.deepEqual(
      classifyEvent({ repoRoot: repo, eventName: 'pull_request', event: { pull_request: { base: { sha: base }, head: { sha: head } } } }),
      expected('frontend'),
    )
  })

  test('manual, fork/missing SHA, invalid range, and Git failure all fail closed', () => {
    const repo = makeRepo()
    const sha = git(repo, ['rev-parse', 'HEAD'])
    const all = expected(...SCOPE_KEYS)
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'workflow_dispatch', event: {} }), all)
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'pull_request', event: { pull_request: { base: { sha }, head: { sha: 'not-a-sha' } } } }), all)
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before: '0'.repeat(40), after: sha } }), all)
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before: sha, after: 'f'.repeat(40) } }), all)
    assert.deepEqual(classifyEvent({ repoRoot: join(repo, 'missing'), eventName: 'push', event: { before: sha, after: sha } }), all)
  })

  test('actual Git symlink and submodule modes fail closed', () => {
    const repo = makeRepo()
    const before = git(repo, ['rev-parse', 'HEAD'])
    writeFileSync(join(repo, 'target.txt'), 'target\n')
    // A symlink is deliberately committed as a mode change, not followed.
    symlinkSync('target.txt', join(repo, 'frontend-link'))
    git(repo, ['add', 'frontend-link', 'target.txt'])
    git(repo, ['commit', '-qm', 'symlink'])
    const symlinkAfter = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before, after: symlinkAfter } }), expected(...SCOPE_KEYS))

    const submoduleBefore = symlinkAfter
    const submoduleSha = git(repo, ['rev-parse', 'HEAD'])
    execFileSync('git', ['update-index', '--add', '--cacheinfo', `160000,${submoduleSha},vendor/submodule`], { cwd: repo })
    git(repo, ['commit', '-qm', 'gitlink'])
    const submoduleAfter = git(repo, ['rev-parse', 'HEAD'])
    assert.deepEqual(classifyEvent({ repoRoot: repo, eventName: 'push', event: { before: submoduleBefore, after: submoduleAfter } }), expected(...SCOPE_KEYS))
  })

  test('CLI writes only fixed boolean output names and no changed paths', () => {
    const repo = makeRepo()
    const before = git(repo, ['rev-parse', 'HEAD'])
    mkdirSync(join(repo, 'frontend'), { recursive: true })
    writeFileSync(join(repo, 'frontend', 'new.ts'), 'export const x = 1\n')
    git(repo, ['add', 'frontend/new.ts'])
    git(repo, ['commit', '-qm', 'frontend'])
    const after = git(repo, ['rev-parse', 'HEAD'])
    const eventPath = join(repo, 'event.json')
    const outputPath = join(repo, 'output.txt')
    writeFileSync(eventPath, JSON.stringify({ before, after }))
    const result = spawnSync(process.execPath, [fileURLToPath(new URL('./classify-changes.mjs', import.meta.url))], {
      cwd: repo,
      encoding: 'utf8',
      env: { ...process.env, GITHUB_EVENT_PATH: eventPath, GITHUB_EVENT_NAME: 'push', GITHUB_OUTPUT: outputPath },
    })
    assert.equal(result.status, 0, result.stderr)
    const output = readFileSync(outputPath, 'utf8')
    assert.deepEqual(output.trim().split('\n'), SCOPE_KEYS.map((key) => `${key}=${key === 'frontend' ? 'true' : 'false'}`))
    assert.equal(output.includes('frontend/new.ts'), false)
  })

  test('CLI invalid, zero, and fork ranges write all booleans', () => {
    const repo = makeRepo()
    const sha = git(repo, ['rev-parse', 'HEAD'])
    const all = SCOPE_KEYS.map((key) => `${key}=true`)
    for (const [eventName, event] of [
      ['workflow_dispatch', {}],
      ['push', { before: '0'.repeat(40), after: sha }],
      ['pull_request', { pull_request: { base: { sha }, head: { sha: 'f'.repeat(40) } } }],
    ]) {
      const eventPath = join(repo, `event-${eventName}.json`)
      const outputPath = join(repo, `output-${eventName}.txt`)
      writeFileSync(eventPath, JSON.stringify(event))
      const result = spawnSync(process.execPath, [fileURLToPath(new URL('./classify-changes.mjs', import.meta.url))], {
        cwd: repo,
        encoding: 'utf8',
        env: { ...process.env, GITHUB_EVENT_PATH: eventPath, GITHUB_EVENT_NAME: eventName, GITHUB_OUTPUT: outputPath },
      })
      assert.equal(result.status, 0, result.stderr)
      assert.deepEqual(readFileSync(outputPath, 'utf8').trim().split('\n'), all)
    }
  })
})
