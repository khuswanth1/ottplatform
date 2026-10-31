import { describe, expect, it } from 'vitest'
import { formatDate, formatMoney } from './money'

describe('money helpers', () => {
  it('formats cents as currency', () => {
    expect(formatMoney(1299, 'USD', 'en-US')).toBe('$12.99')
    expect(formatMoney(0, 'USD', 'en-US')).toBe('$0.00')
  })
  it('degrades for bad input', () => {
    expect(formatMoney(NaN, 'USD')).toBe('')
    expect(formatMoney(500, '')).toBe('')
    expect(formatMoney(500, 'NOPE', 'en-US')).toContain('5.00')
  })
  it('formats dates and ignores junk', () => {
    expect(formatDate('2030-03-05T12:00:00Z', 'en-US')).toContain('2030')
    expect(formatDate('garbage')).toBe('')
    expect(formatDate(null)).toBe('')
  })
})
