import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const contactForm = readFileSync(
  resolve(process.cwd(), 'src/app/u/[username]/ContactForm.tsx'),
  'utf8',
)
const portfolioPage = readFileSync(
  resolve(process.cwd(), 'src/app/u/[username]/page.tsx'),
  'utf8',
)
const apiClient = readFileSync(resolve(process.cwd(), 'src/lib/api-client.ts'), 'utf8')

describe('public portfolio contact form', () => {
  it('submits a bounded message through the public portfolio API', () => {
    expect(contactForm).toContain('apiClient.sendPortfolioContact(username')
    expect(contactForm).toContain('required')
    expect(contactForm).toContain('maxLength={100}')
    expect(contactForm).toContain('maxLength={254}')
    expect(contactForm).toContain('maxLength={5000}')
    expect(contactForm).not.toContain("Direct messaging isn&apos;t available yet")
  })

  it('passes the route username into the client form', () => {
    expect(portfolioPage).toContain('<ContactForm username={username} />')
  })

  it('uses an encoded username in the API request path', () => {
    expect(apiClient).toContain('async sendPortfolioContact(')
    expect(apiClient).toContain('`/portfolio/${encodeURIComponent(username)}/contact`')
  })
})
