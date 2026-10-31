export function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return '0:00'
  const s = Math.floor(sec)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const r = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${r}` : `${m}:${r}`
}

export function formatRuntime(min) {
  if (!min) return ''
  const h = Math.floor(min / 60)
  return h ? `${h}h ${min % 60}m` : `${min}m`
}

export function pageParam(lastPage) {
  return lastPage.page < lastPage.total_pages ? lastPage.page + 1 : undefined
}

const KIND_ORDER = ['free', 'subscription', 'rent', 'buy']
export function groupExternal(options = []) {
  const g = {}
  options.forEach((o) => { (g[o.kind] ||= []).push(o) })
  return KIND_ORDER.filter((k) => g[k]).map((k) => ({ kind: k, items: g[k] }))
}

export const KIND_LABEL = { free: 'Free (external site)', subscription: 'With subscription', rent: 'Rent', buy: 'Buy' }

export function isSafeExternalUrl(u) {
  try { return ['https:', 'http:'].includes(new URL(u).protocol) } catch { return false }
}

/** True when an ISO date (yyyy-mm-dd) is after today in the viewer's local date. */
export function isFuture(isoDate, now = new Date()) {
  if (!isoDate) return false
  const [y, m, d] = isoDate.split('-').map(Number)
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return new Date(y, m - 1, d) > today
}

/** "17 Oct 2026" from an ISO date without shifting it across a time zone. */
export function formatDay(isoDate) {
  if (!isoDate) return ''
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
}

/** "Active now", "Active 12 min ago", "Active 3 h ago" or "Active 5 days ago" for a timestamp. */
export function activeAgo(iso, now = Date.now()) {
  // the API stores UTC; a timestamp without a zone (SQLite dev databases) must not be read as local time
  const utc = /(Z|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`
  const mins = Math.max(0, Math.round((now - new Date(utc).getTime()) / 60_000))
  if (mins < 5) return 'Active now'
  if (mins < 60) return `Active ${mins} min ago`
  const hours = Math.round(mins / 60)
  if (hours < 48) return `Active ${hours} h ago`
  return `Active ${Math.round(hours / 24)} days ago`
}

/** The marker (intro, recap, credits) that covers `time` seconds, or null. Ranges are start inclusive, end exclusive. */
export function activeMarker(markers, time) {
  return (markers || []).find((m) => time >= m.start_s && time < m.end_s) || null
}

/** "90", "1:30" or "1:02:03" to seconds; null when it is not a time. */
export function parseTime(text) {
  const parts = String(text ?? '').trim().split(':')
  if (parts.length > 3 || parts.some((p) => !/^\d+$/.test(p))) return null
  return parts.reduce((total, p) => total * 60 + Number(p), 0)
}

/** The two lines the notification bell shows for one notification: what happened, and a smaller detail line. */
export function describeNotification(n) {
  const name = n.title.name
  if (n.kind === 'new_episode') return { headline: `New episode of ${name}`, detail: n.episode_label || 'Just added' }
  if (n.kind === 'new_in_list') return { headline: `${name} is now available to watch`, detail: 'From your list' }
  return { headline: `${name} is out now`, detail: n.title.release_date ? `Released ${formatDay(n.title.release_date)}` : 'New' }
}
