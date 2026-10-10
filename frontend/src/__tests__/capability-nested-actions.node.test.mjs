// Dependency-free regression checks: node --test src/__tests__/capability-nested-actions.node.test.mjs
// Executes the real TS handlers (not a duplicate policy); control markup checks
// supplement these checks but do not replace browser/React integration coverage.
import { readFileSync } from 'node:fs'
import * as nodeModule from 'node:module'
import assert from 'node:assert/strict'
import { test } from 'node:test'

const require = nodeModule.createRequire(import.meta.url)
const stripTypeScriptTypes = nodeModule.stripTypeScriptTypes ?? ((code) => {
  // Early Node 22 versions need the project's normal TypeScript dependency.
  const ts = require('typescript')
  return ts.transpileModule(code, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
})

const component = (name) => readFileSync(new URL(`../components/${name}.tsx`, import.meta.url), 'utf8')
const references = component('ReferencesPanel')
const publications = component('PublicationsPanel')
const writing = component('WritingAssistantWidget')
const imports = component('ImportProjectsModal')
const scope = (source, componentName) => {
  const start = source.indexOf(`function ${componentName}(`)
  assert.notEqual(start, -1, componentName)
  const end = source.indexOf('\nfunction ', start + 1)
  return source.slice(start, end < 0 ? undefined : end)
}
const zotero = scope(references, 'ZoteroSection')
const mendeley = scope(references, 'MendeleySection')
const orcid = scope(references, 'OrcidSection')
const citations = scope(references, 'CitationCheckSection')
const bibliography = scope(references, 'ReferencesPanel')
function handler(source, name, context = {}) {
  const marker = `  const ${name} = `
  const start = source.indexOf(marker)
  assert.notEqual(start, -1, name)
  const closing = source.startsWith('useCallback(\n', start + marker.length) ? '\n    }' : '\n  }'
  const end = source.indexOf(closing, start)
  assert.notEqual(end, -1, `${name} end`)
  const expression = source.slice(start + marker.length, end + closing.length).replace(/^useCallback\(\s*/, '')
  const javascript = stripTypeScriptTypes(`const action = ${expression}`)
  return new Function(...Object.keys(context), `${javascript}; return action`)(...Object.values(context))
}
const noop = () => {}
const setters = Object.fromEntries([
  'setActiveAction', 'setActiveTone', 'setActiveInstruction', 'setPhase', 'setLoadingMessage',
  'setError', 'setRewritten', 'setSynonyms', 'setVariantSet', 'setLibrary', 'setSuccess',
  'setCollectionsLoading', 'setCollections', 'setImporting', 'setLoading', 'setFetched',
  'setEntries', 'setFetchError', 'setIsLoading', 'setPublications', 'setSelectedPubs',
  'setLatexSection', 'setHasFetched', 'setStatus', 'setArchiveRequestedAt',
].map((name) => [name, noop]))
const deferred = () => {
  let resolve
  const promise = new Promise((done) => { resolve = done })
  return { promise, resolve }
}

for (const [source, name] of [
  [zotero, 'handleConnect'], [zotero, 'loadCollections'], [zotero, 'handleImport'],
  [mendeley, 'handleConnect'], [mendeley, 'handleImport'], [orcid, 'handleFetch'],
  [orcid, 'handleInsertAll'], [citations, 'check'], [bibliography, 'handleFetch'],
  [bibliography, 'handleInsertAll'], [publications, 'handleFetch'], [publications, 'handleInsert'],
]) {
  test(`${source.match(/function (\w+)/)?.[1] ?? 'PublicationsPanel'} ${name}: a retained action checks live grant before doing work`, async () => {
    const allowedRef = { current: true }
    const action = handler(source, name, { allowedRef })
    allowedRef.current = false
    // Any state, network or navigation access beyond the gate would throw.
    await action()
  })
}

for (const [name, feature, args] of [
  ['callApi', 'd06', ['improve']], ['handleActionClick', 'd06', ['steer']],
  ['loadSynonyms', 'd07', []], ['generateVariants', 'd10', []],
  ['openVariantSetup', 'd10', []], ['acceptOption', 'd07', ['replacement', 'd07']],
  ['acceptOption', 'd10', ['replacement', 'd10']], ['acceptOption', 'd06', ['replacement', 'd06']],
]) {
  test(`${name} uses ${feature}, independently of sibling grants`, async () => {
    const checked = []
    const canRef = { current: () => true }
    const action = handler(writing, name, { canRef })
    canRef.current = (key) => { checked.push(key); return key !== feature }
    await action(...args)
    assert.deepEqual(checked, [feature])
  })
}

test('enabled synonyms and variants still make the expected new requests', async () => {
  const requests = []
  const common = { ...setters, canRef: { current: () => true }, selectedText: 'source', context: 'context', resumeId: 'resume', jobDescription: '', targetLabel: 'General',
    apiClient: {
      suggestSynonyms: async (...args) => { requests.push(['synonyms', ...args]); return { synonyms: ['replacement'] } },
      generateBulletVariants: async (args) => { requests.push(['variants', args]); return { id: 'set' } },
    },
  }
  await handler(writing, 'loadSynonyms', common)()
  await handler(writing, 'generateVariants', common)()
  assert.deepEqual(requests, [ ['synonyms', 'source', 'context'], ['variants', { resume_id: 'resume', source_text: 'source', job_description: undefined, target_label: 'General' }] ])
})

test('enabled reference imports still call their own providers', async () => {
  const requests = []
  const common = { ...setters, allowedRef: { current: true }, resumeId: 'resume', selectedCollection: 'collection', onBibTeXImported: noop,
    apiClient: {
      importFromZotero: async (...args) => { requests.push(['zotero', ...args]); return { bibtex: '', entries_count: 0, source: {} } },
      importFromMendeley: async (...args) => { requests.push(['mendeley', ...args]); return { bibtex: '', entries_count: 0, source: {} } },
    },
  }
  await handler(zotero, 'handleImport', common)()
  await handler(mendeley, 'handleImport', common)()
  assert.deepEqual(requests, [['zotero', 'resume', 'collection'], ['mendeley', 'resume']])
})

test('provider disconnect and existing bullet-library recovery do not require feature grants', async () => {
  const recovered = []
  const common = { ...setters, confirm: () => true, resumeId: 'resume', variantSet: null,
    apiClient: {
      disconnectZotero: async () => { recovered.push('zotero') },
      disconnectMendeley: async () => { recovered.push('mendeley') },
      getBulletVariants: async () => { recovered.push('read'); return [] },
      deleteBulletVariantSet: async () => { recovered.push('delete') },
    },
  }
  await handler(zotero, 'handleDisconnect', common)()
  await handler(mendeley, 'handleDisconnect', common)()
  await handler(writing, 'openLibrary', common)()
  await handler(writing, 'deleteVariantSet', common)('set')
  assert.deepEqual(recovered, ['zotero', 'mendeley', 'read', 'delete'])
})

for (const [name, feature] of [['startGithubImport', 'g02'], ['beginGithub', 'g02'], ['connectGithubForImport', 'g02'], ['runUrlImport', 'g03'], ['runLinkedInImport', 'g04']]) {
  test(`${name} denies its own disabled capability before work`, async () => {
    const checked = []
    const canRef = { current: (key) => { checked.push(key); return key !== feature } }
    await handler(imports, name, { canRef })({ name: 'archive.zip' })
    assert.deepEqual(checked, [feature])
  })
}

for (const [name, expected] of [['runUrlImport', 'url'], ['runLinkedInImport', 'linkedin'], ['connectGithubForImport', 'github']]) {
  test(`${name} rejects stale controls from another source or a dismissed modal`, async () => {
    const scopeRef = { current: { source: 'wrong-source', isOpen: true } }
    const action = handler(imports, name, { canRef: { current: () => true }, scopeRef })
    await action({ name: 'archive.zip' })
    scopeRef.current = { source: expected, isOpen: false }
    await action({ name: 'archive.zip' })
  })
}

test('OAuth rechecks the grant after await and cannot navigate on revocation', async () => {
  const authorization = deferred()
  let allowed = true
  let navigated = false
  const action = handler(imports, 'connectGithubForImport', { ...setters,
    canRef: { current: () => allowed }, scopeRef: { current: { isOpen: true, source: 'github' } }, cancelledRef: { current: false }, requestVersion: { current: 1 }, isCurrentRequest: () => true,
    apiClient: { startGitHubOAuth: () => authorization.promise },
    window: { location: { pathname: '/workspace/resume/edit', assign: () => { navigated = true } } },
    safeOAuthAuthorizationUrl: () => 'https://github.com/login/oauth/authorize',
  })
  const pending = action()
  allowed = false
  authorization.resolve({ authorization_url: 'https://github.com/login/oauth/authorize' })
  await pending
  assert.equal(navigated, false)
})

for (const [name, apiMethod, source] of [['runUrlImport', 'importFromUrl', 'url'], ['runLinkedInImport', 'importLinkedIn', 'linkedin']]) {
  test(`${name} does not publish stale results into a newer source session`, async () => {
    const response = deferred()
    let current = true
    let loaded = false
    const action = handler(imports, name, { ...setters,
      canRef: { current: () => true }, scopeRef: { current: { isOpen: true, source } }, cancelledRef: { current: false }, requestVersion: { current: 1 }, isCurrentRequest: () => current,
      urlInput: 'https://example.com', apiClient: { [apiMethod]: () => response.promise },
      loadProjects: () => { loaded = true },
    })
    const pending = action({ name: 'archive.zip' })
    current = false
    response.resolve({ projects: [{ title: 'old project' }] })
    await pending
    assert.equal(loaded, false)
  })
}

test('GitHub import does not schedule polling after its source session ends', async () => {
  const response = deferred()
  let current = true
  let scheduled = false
  const action = handler(imports, 'startGithubImport', { ...setters,
    canRef: { current: () => true }, scopeRef: { current: { isOpen: true, source: 'github' } }, cancelledRef: { current: false }, requestVersion: { current: 1 }, isCurrentRequest: () => current,
    apiClient: { importGitHubProjects: () => response.promise }, setTimeout: () => { scheduled = true },
  })
  const pending = action()
  current = false
  response.resolve({ job_id: 'job' })
  await pending
  assert.equal(scheduled, false)
})

test('grant refresh does not resubmit imports; generation controls expose disabled state', () => {
  assert.match(imports, /\[availableSource, beginGithub, isOpen, reset, source\]/)
  assert.doesNotMatch(imports, /\[can, isOpen, source\]/)
  assert.match(imports, /disabled=\{!sourceAllowed \|\| phase !== 'ready'/)
  assert.match(writing, /disabled=\{!can\(key === 'synonyms' \? 'd07' : 'd06'\)\}/)
  assert.match(writing, /disabled=\{!can\('d10'\) \|\| !targetLabel.trim\(\)\}/)
  assert.match(publications, /disabled=\{!allowed \|\| isLoading/)
  for (const [section, feature] of [[zotero, 'g07'], [mendeley, 'g08'], [orcid, 'g09'], [citations, 'g09']]) {
    assert.ok(section.includes(`useReferenceCapability('${feature}')`))
    assert.match(section, /disabled=\{!allowed/)
  }
  assert.ok(references.includes('Download references.bib'))
  assert.ok(references.includes('apiClient.getZoteroStatus()'))
  assert.ok(references.includes('apiClient.getMendeleyStatus()'))
})
