import { describe, expect, it } from 'vitest'
import { activeAgo, activeMarker, describeNotification, formatDay, parseTime, formatTime, formatRuntime, groupExternal, isFuture, isSafeExternalUrl, pageParam } from './utils'
import { buildQuery, parseDetail } from '../api/client'

describe('utils', () => {
  it('formats time', () => {
    expect(formatTime(0)).toBe('0:00')
    expect(formatTime(75)).toBe('1:15')
    expect(formatTime(3661)).toBe('1:01:01')
    expect(formatTime(NaN)).toBe('0:00')
  })
  it('formats runtime', () => {
    expect(formatRuntime(45)).toBe('45m')
    expect(formatRuntime(135)).toBe('2h 15m')
    expect(formatRuntime(null)).toBe('')
  })
  it('groups external options in priority order', () => {
    const g = groupExternal([{ kind: 'buy' }, { kind: 'free' }, { kind: 'subscription' }, { kind: 'free' }])
    expect(g.map((x) => x.kind)).toEqual(['free', 'subscription', 'buy'])
    expect(g[0].items).toHaveLength(2)
  })
  it('only allows http(s) external links', () => {
    expect(isSafeExternalUrl('https://example.com/x')).toBe(true)
    expect(isSafeExternalUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeExternalUrl('nonsense')).toBe(false)
  })
  it('computes next page', () => {
    expect(pageParam({ page: 1, total_pages: 3 })).toBe(2)
    expect(pageParam({ page: 3, total_pages: 3 })).toBeUndefined()
  })
  it('builds query strings without empty values', () => {
    expect(buildQuery({ a: 1, b: '', c: undefined, d: 'x y' })).toBe('?a=1&d=x+y')
    expect(buildQuery({})).toBe('')
  })
  it('parses FastAPI errors', () => {
    expect(parseDetail({ detail: 'nope' })).toBe('nope')
    expect(parseDetail({ detail: [{ loc: ['body', 'email'], msg: 'bad' }] })).toBe('email: bad')
    expect(parseDetail(null)).toMatch(/went wrong/)
  })
  it('knows whether a release date is still ahead, by local date', () => {
    const now = new Date(2026, 9, 17, 23, 30) // 17 Oct 2026, late evening
    expect(isFuture('2026-10-18', now)).toBe(true)
    expect(isFuture('2026-10-17', now)).toBe(false) // out today
    expect(isFuture('2025-01-01', now)).toBe(false)
    expect(isFuture(null, now)).toBe(false)
  })
  it('formats a date without shifting the day', () => {
    expect(formatDay('2026-10-17')).toMatch(/17/)
    expect(formatDay(null)).toBe('')
  })
  it('describes how recently a device was active', () => {
    const now = new Date('2026-10-17T12:00:00Z').getTime()
    const at = (minsAgo) => new Date(now - minsAgo * 60_000).toISOString()
    expect(activeAgo(at(2), now)).toBe('Active now')
    expect(activeAgo(at(20), now)).toBe('Active 20 min ago')
    expect(activeAgo(at(180), now)).toBe('Active 3 h ago')
    expect(activeAgo(at(60 * 24 * 5), now)).toBe('Active 5 days ago')
    expect(activeAgo(at(20).replace('Z', ''), now)).toBe('Active 20 min ago') // no zone means UTC, not local time
  })
  it('finds the marker that covers the current time', () => {
    const ms = [{ kind: 'recap', start_s: 0, end_s: 30 }, { kind: 'intro', start_s: 30, end_s: 90 }]
    expect(activeMarker(ms, 0).kind).toBe('recap')
    expect(activeMarker(ms, 29.9).kind).toBe('recap')
    expect(activeMarker(ms, 30).kind).toBe('intro')   // start inclusive, end exclusive
    expect(activeMarker(ms, 90)).toBeNull()
    expect(activeMarker(undefined, 5)).toBeNull()
  })
  it('parses typed times', () => {
    expect(parseTime('90')).toBe(90)
    expect(parseTime('1:30')).toBe(90)
    expect(parseTime(' 1:02:03 ')).toBe(3723)
    expect(parseTime('')).toBeNull()
    expect(parseTime('1:xx')).toBeNull()
    expect(parseTime('1:2:3:4')).toBeNull()
    expect(parseTime('-5')).toBeNull()
  })
  it('words each kind of notification', () => {
    const title = { name: 'Harbor Nights', release_date: '2026-10-16' }
    expect(describeNotification({ kind: 'new_episode', title, episode_label: 'S2:E3 The Return' })).toEqual({ headline: 'New episode of Harbor Nights', detail: 'S2:E3 The Return' })
    expect(describeNotification({ kind: 'new_episode', title }).detail).toBe('Just added')
    expect(describeNotification({ kind: 'new_in_list', title }).headline).toBe('Harbor Nights is now available to watch')
    expect(describeNotification({ kind: 'reminder_released', title }).headline).toBe('Harbor Nights is out now')
    expect(describeNotification({ kind: 'reminder_released', title: { name: 'X' } }).detail).toBe('New')
  })
})
