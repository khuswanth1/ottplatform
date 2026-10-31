// "Are you still watching?": stop playing to nobody. Two triggers, both reset by any click, tap or key press.
export const EPISODES_BEFORE_ASK = 3 // episodes that rolled on by themselves
export const IDLE_AFTER_MS = 4 * 60 * 60 * 1000 // continuous playback with no input at all

/** True when the next episode should wait for an answer instead of starting by itself. */
export const askAfterEpisode = (unattended, limit = EPISODES_BEFORE_ASK) => unattended >= limit

/** True when nothing has been pressed or clicked for `limit` ms. */
export const isIdle = (lastInput, now = Date.now(), limit = IDLE_AFTER_MS) => now - lastInput >= limit
