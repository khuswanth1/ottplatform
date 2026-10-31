import { describe, expect, it } from 'vitest'
import { isRestricted, levelLabel, levelOf } from './maturity'

describe('maturity helpers', () => {
  it('falls back to the legacy kids flag', () => {
    expect(levelOf({ is_kids: true })).toBe('kids')
    expect(levelOf({ is_kids: false })).toBe('all')
    expect(levelOf(null)).toBe('all')
  })
  it('prefers the explicit level', () => {
    expect(levelOf({ maturity_level: '13+', is_kids: false })).toBe('13+')
    expect(levelLabel({ maturity_level: '7+' })).toBe('Ages 7+')
  })
  it('knows which profiles are restricted', () => {
    expect(isRestricted({ maturity_level: 'all' })).toBe(false)
    expect(isRestricted({ maturity_level: 'kids' })).toBe(true)
  })
})
