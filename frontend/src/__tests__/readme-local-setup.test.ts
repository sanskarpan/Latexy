import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), '../../..')

describe('README development setup', () => {
  it('references tracked environment templates for the files its commands create', () => {
    const readme = readFileSync(resolve(repositoryRoot, 'README.md'), 'utf8')
    const templates = [...readme.matchAll(/\bcp\s+([^\s]*\.env(?:\.production)?\.example)\s+[^\s]+/g)]
      .map(match => match[1])

    expect(templates).toContain('backend/.env.example')
    expect(templates).toContain('.env.production.example')
    expect(templates.every(template => existsSync(resolve(repositoryRoot, template)))).toBe(true)
    expect(readme).not.toMatch(/\bcp\s+\.env\.example\s+\.env\b/)
  })

  it('documents the root environment file used by the full Docker stack', () => {
    const readme = readFileSync(resolve(repositoryRoot, 'README.md'), 'utf8')
    const compose = readFileSync(resolve(repositoryRoot, 'docker-compose.yml'), 'utf8')

    expect(compose).toMatch(/env_file:\s*\r?\n\s+- \.env\b/)
    expect(readme).toContain('copy `backend/.env.example` to the repository-root `.env`')
  })
})
