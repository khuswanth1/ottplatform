// Profile maturity levels. Order matters: lowest to highest. The server enforces them; this is display only.
export const LEVELS = [
  { id: 'kids', label: 'Kids', hint: 'Family-friendly titles only, with a simpler look.' },
  { id: '7+', label: 'Ages 7+', hint: 'Ratings up to PG. Unrated titles are hidden.' },
  { id: '13+', label: 'Ages 13+', hint: 'Ratings up to PG-13 and TV-14. Unrated titles are hidden.' },
  { id: 'all', label: 'All ages', hint: 'Everything, including mature titles.' },
]

export const levelOf = (profile) => profile?.maturity_level || (profile?.is_kids ? 'kids' : 'all')
export const levelLabel = (profile) => LEVELS.find((l) => l.id === levelOf(profile))?.label ?? 'All ages'
export const isRestricted = (profile) => levelOf(profile) !== 'all'
