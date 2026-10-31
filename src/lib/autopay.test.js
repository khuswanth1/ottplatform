import { describe, expect, it } from 'vitest'
import { shouldOfferAutopay } from './autopay'

const store = () => {
  const m = new Map()
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => m.set(k, v) }
}

describe('shouldOfferAutopay', () => {
  it('offers once to a free user, then never again', () => {
    const s = store()
    const u = { id: 'u1', plan: 'free', role: 'user' }
    expect(shouldOfferAutopay(u, s)).toBe(true)
    expect(shouldOfferAutopay(u, s)).toBe(false)
  })
  it('does not offer to paying users, admins or anonymous', () => {
    expect(shouldOfferAutopay({ id: 'u', plan: 'premium', role: 'user' }, store())).toBe(false)
    expect(shouldOfferAutopay({ id: 'a', plan: 'free', role: 'admin' }, store())).toBe(false)
    expect(shouldOfferAutopay(null, store())).toBe(false)
  })
  it('remembers per user', () => {
    const s = store()
    expect(shouldOfferAutopay({ id: 'a', plan: 'free', role: 'user' }, s)).toBe(true)
    expect(shouldOfferAutopay({ id: 'b', plan: 'free', role: 'user' }, s)).toBe(true)
  })
  it('stays quiet when storage is unavailable', () => {
    const broken = { getItem: () => { throw new Error('blocked') }, setItem: () => {} }
    expect(shouldOfferAutopay({ id: 'u', plan: 'free', role: 'user' }, broken)).toBe(false)
  })
})
