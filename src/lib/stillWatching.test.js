import { describe, expect, it } from 'vitest'
import { EPISODES_BEFORE_ASK, IDLE_AFTER_MS, askAfterEpisode, isIdle } from './stillWatching'

describe('still watching', () => {
  it('lets a couple of episodes roll on, then asks', () => {
    expect(EPISODES_BEFORE_ASK).toBe(3)
    expect([0, 1, 2].map((n) => askAfterEpisode(n))).toEqual([false, false, false])
    expect(askAfterEpisode(3)).toBe(true)
    expect(askAfterEpisode(7)).toBe(true)
    expect(askAfterEpisode(1, 1)).toBe(true) // the limit can be changed
  })
  it('calls it idle only after the full period with no input', () => {
    const t0 = 1_000_000
    expect(isIdle(t0, t0 + IDLE_AFTER_MS - 1)).toBe(false)
    expect(isIdle(t0, t0 + IDLE_AFTER_MS)).toBe(true)
    expect(isIdle(t0, t0)).toBe(false)
  })
})
