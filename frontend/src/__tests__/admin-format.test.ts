import { describe, expect, it } from 'vitest'
import { formatMoney } from '../components/admin/admin-format'

describe('admin money formatting', () => {
  it('does not throw for missing or invalid currency codes', () => {
    expect(formatMoney(1234, null)).toContain('1,234')
    expect(formatMoney(1234, undefined)).toContain('1,234')
    expect(formatMoney(1234, '')).toContain('1,234')
    expect(formatMoney(1234, 'usd')).toContain('1,234')
    expect(formatMoney(null, null)).toContain('0')
  })
})
