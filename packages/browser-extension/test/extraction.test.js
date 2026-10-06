import assert from 'node:assert/strict'
import test from 'node:test'

import { extractJobPosting } from '../extraction.js'

const node = (textContent = '', attributes = {}) => ({
  textContent,
  getAttribute(name) { return attributes[name] || null },
})

function fakeDocument({ jsonLd = [], selectors = {} } = {}) {
  return {
    querySelector(selector) { return selectors[selector] || null },
    querySelectorAll(selector) {
      return selector === 'script[type="application/ld+json"]' ? jsonLd : []
    },
  }
}

test('prefers nested schema.org JobPosting data and strips markup', () => {
  const doc = fakeDocument({
    jsonLd: [node(JSON.stringify({
      '@graph': [{
        '@type': 'JobPosting',
        title: 'Senior Engineer',
        hiringOrganization: { name: 'Acme Corp' },
        description: '<p>Build &amp; operate <strong>reliable</strong> systems.</p>',
        jobLocation: { address: { addressLocality: 'Pune', addressCountry: 'IN' } },
      }],
    }))],
  })

  assert.deepEqual(
    extractJobPosting(doc, 'https://jobs.example/role?id=42&utm_source=test&token=secret#apply'),
    {
      title: 'Senior Engineer',
      company: 'Acme Corp',
      description: 'Build & operate reliable systems.',
      location: 'Pune, IN',
      url: 'https://jobs.example/role?id=42',
      source: 'json_ld',
    },
  )
})

test('falls back to visible semantic selectors', () => {
  const doc = fakeDocument({
    selectors: {
      h1: node(' Platform Engineer '),
      '.company-name': node('Example Ltd'),
      '.job-description': node('Operate the platform and improve reliability.'),
      '.job-location': node('Remote'),
    },
  })
  const result = extractJobPosting(doc, 'https://example.test/jobs/1')
  assert.equal(result.source, 'visible_page')
  assert.equal(result.title, 'Platform Engineer')
  assert.equal(result.company, 'Example Ltd')
  assert.equal(result.description, 'Operate the platform and improve reliability.')
  assert.equal(result.location, 'Remote')
})

test('bounds descriptions and rejects non-web URLs', () => {
  const doc = fakeDocument({ selectors: { main: node('x'.repeat(25_000)) } })
  const result = extractJobPosting(doc, 'chrome://extensions')
  assert.equal(result.description.length, 20_000)
  assert.equal(result.url, '')
})

test('decodes entities only once and removes spaced script/style end tags', () => {
  const doc = fakeDocument({ jsonLd: [node(JSON.stringify({
    '@type': 'JobPosting',
    description: '<script>private script</script >Visible &amp;quot; &quot;text&quot;<style>private style</style\t>',
  }))] })
  assert.equal(extractJobPosting(doc, 'https://example.test/job').description, 'Visible &quot; "text"')
})
