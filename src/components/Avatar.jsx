// Profile avatars. Twelve simple drawings made for this project from basic shapes (no stock or borrowed artwork).
// A profile stores only the id ("avatar-1" to "avatar-24"); ids with no drawing yet fall back to a letter tile, so a
// stored id never breaks the page. The drawings are decoration: the profile name always sits next to them.

const L = { fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' }

export const AVATARS = [
  { id: 'avatar-1', name: 'Sun', bg: '#f6c453', art: (
    <>
      <circle cx="32" cy="32" r="11" fill="#e8742c" />
      {[0, 45, 90, 135, 180, 225, 270, 315].map((a) => <line key={a} x1="32" y1="14" x2="32" y2="8" stroke="#e8742c" strokeWidth="3.5" strokeLinecap="round" transform={`rotate(${a} 32 32)`} />)}
    </>
  ) },
  { id: 'avatar-2', name: 'Moon', bg: '#2d3a6b', art: (
    <>
      <circle cx="30" cy="33" r="17" fill="#f3e9b8" />
      <circle cx="39" cy="28" r="14" fill="#2d3a6b" />
      <circle cx="46" cy="46" r="1.6" fill="#f3e9b8" /><circle cx="16" cy="16" r="1.4" fill="#f3e9b8" /><circle cx="50" cy="14" r="1.2" fill="#f3e9b8" />
    </>
  ) },
  { id: 'avatar-3', name: 'Cat', bg: '#8fd3c1', art: (
    <>
      <polygon points="14,28 17,10 31,20" fill="#f2a65a" /><polygon points="50,28 47,10 33,20" fill="#f2a65a" />
      <circle cx="32" cy="36" r="18" fill="#f2a65a" />
      <circle cx="25" cy="34" r="2.4" fill="#2b2b3a" /><circle cx="39" cy="34" r="2.4" fill="#2b2b3a" />
      <polygon points="29.5,40 34.5,40 32,43.5" fill="#d9534f" />
      <path d="M12 38 L22 40 M12 45 L22 43 M52 38 L42 40 M52 45 L42 43" stroke="#6b4a2b" strokeWidth="1.6" {...L} />
    </>
  ) },
  { id: 'avatar-4', name: 'Robot', bg: '#c9b6f2', art: (
    <>
      <line x1="32" y1="20" x2="32" y2="11" stroke="#59627a" strokeWidth="3" strokeLinecap="round" /><circle cx="32" cy="9" r="3.5" fill="#ff6b6b" />
      <rect x="13" y="20" width="38" height="31" rx="7" fill="#8e99a8" />
      <rect x="19" y="28" width="10" height="9" rx="2" fill="#fff" /><rect x="35" y="28" width="10" height="9" rx="2" fill="#fff" />
      <circle cx="25" cy="33" r="2.6" fill="#2b2b3a" /><circle cx="39" cy="33" r="2.6" fill="#2b2b3a" />
      <path d="M24 44 H40" stroke="#2b2b3a" strokeWidth="2.6" {...L} />
    </>
  ) },
  { id: 'avatar-5', name: 'Fox', bg: '#ffd6a5', art: (
    <>
      <polygon points="10,14 25,27 39,27 54,14 50,42 32,55 14,42" fill="#e8742c" />
      <polygon points="23,43 32,55 41,43 32,36" fill="#fff6e8" />
      <circle cx="24" cy="34" r="2.3" fill="#2b2b3a" /><circle cx="40" cy="34" r="2.3" fill="#2b2b3a" />
      <circle cx="32" cy="47" r="2.2" fill="#2b2b3a" />
    </>
  ) },
  { id: 'avatar-6', name: 'Owl', bg: '#a0c4ff', art: (
    <>
      <polygon points="17,18 22,9 28,17" fill="#8b6b4a" /><polygon points="47,18 42,9 36,17" fill="#8b6b4a" />
      <ellipse cx="32" cy="36" rx="17" ry="20" fill="#8b6b4a" />
      <circle cx="24.5" cy="31" r="7.5" fill="#fff" /><circle cx="39.5" cy="31" r="7.5" fill="#fff" />
      <circle cx="25.5" cy="31.5" r="3.2" fill="#2b2b3a" /><circle cx="38.5" cy="31.5" r="3.2" fill="#2b2b3a" />
      <polygon points="29.5,38 34.5,38 32,44" fill="#f6c453" />
    </>
  ) },
  { id: 'avatar-7', name: 'Ghost', bg: '#3a3a52', art: (
    <>
      <path d="M15 52 V31 a17 17 0 0 1 34 0 V52 l-5.5 -4.5 -5.5 4.5 -6 -4.5 -6 4.5 -5.5 -4.5 z" fill="#f4f4fb" />
      <circle cx="26" cy="31" r="3" fill="#2b2b3a" /><circle cx="38" cy="31" r="3" fill="#2b2b3a" />
      <ellipse cx="32" cy="39" rx="3" ry="3.6" fill="#2b2b3a" />
    </>
  ) },
  { id: 'avatar-8', name: 'Cactus', bg: '#ffe3a3', art: (
    <>
      <rect x="26" y="12" width="12" height="40" rx="6" fill="#4c9f70" />
      <path d="M26 33 H20 a4 4 0 0 1 -4 -4 V25" stroke="#4c9f70" strokeWidth="7" {...L} />
      <path d="M38 38 H44 a4 4 0 0 0 4 -4 V28" stroke="#4c9f70" strokeWidth="7" {...L} />
      <rect x="19" y="49" width="26" height="9" rx="2" fill="#c46a3d" />
    </>
  ) },
  { id: 'avatar-9', name: 'Planet', bg: '#1f2a44', art: (
    <>
      <circle cx="32" cy="32" r="12" fill="#ff9f6e" />
      <ellipse cx="32" cy="32" rx="23" ry="6.5" transform="rotate(-20 32 32)" stroke="#f6e2b3" strokeWidth="3" fill="none" />
      <circle cx="12" cy="14" r="1.4" fill="#fff" /><circle cx="52" cy="50" r="1.6" fill="#fff" /><circle cx="50" cy="14" r="1.1" fill="#fff" />
    </>
  ) },
  { id: 'avatar-10', name: 'Cloud', bg: '#bde0fe', art: (
    <>
      <circle cx="23" cy="36" r="10" fill="#fff" /><circle cx="35" cy="30" r="12" fill="#fff" /><circle cx="46" cy="38" r="8.5" fill="#fff" />
      <rect x="15" y="38" width="38" height="9" rx="4.5" fill="#fff" />
      <path d="M24 52 l-2 5 M33 52 l-2 5 M42 52 l-2 5" stroke="#5aa9e6" strokeWidth="2.4" {...L} />
    </>
  ) },
  { id: 'avatar-11', name: 'Mountains', bg: '#ffd6e0', art: (
    <>
      <circle cx="49" cy="17" r="6" fill="#f6c453" />
      <polygon points="5,52 24,22 40,52" fill="#6d7ea8" /><polygon points="26,52 43,28 59,52" fill="#4a5a86" />
      <polygon points="24,22 19,30.5 29,30.5" fill="#fff" />
    </>
  ) },
  { id: 'avatar-12', name: 'Waves', bg: '#0b6e99', art: (
    <>
      <circle cx="46" cy="17" r="6" fill="#ffe08a" />
      <path d="M5 38 q6.5 -9 13 0 t13 0 t13 0 t13 0" stroke="#fff" strokeWidth="3.2" {...L} />
      <path d="M5 48 q6.5 -9 13 0 t13 0 t13 0 t13 0" stroke="#7cc6e8" strokeWidth="3.2" {...L} />
    </>
  ) },
]

const FALLBACK = ['bg-rose-500', 'bg-sky-500', 'bg-emerald-500', 'bg-amber-500', 'bg-violet-500', 'bg-teal-500']

export default function Avatar({ avatar, name, size = 'h-24 w-24 text-3xl', className = '' }) {
  const found = AVATARS.find((a) => a.id === avatar)
  if (!found) {
    const n = Number(String(avatar || '').split('-')[1]) || 1
    return <span className={`grid ${size} shrink-0 place-items-center rounded-lg font-bold text-white ${FALLBACK[(n - 1) % FALLBACK.length]} ${className}`} aria-hidden>{name?.[0]?.toUpperCase()}</span>
  }
  return (
    <span className={`inline-block ${size} shrink-0 overflow-hidden rounded-lg ${className}`} style={{ background: found.bg }} aria-hidden>
      <svg viewBox="0 0 64 64" className="h-full w-full" focusable="false">{found.art}</svg>
    </span>
  )
}

// Radio group: real radio inputs (arrow keys, one tab stop, screen-reader "n of 12" for free), drawn as the artwork.
export function AvatarPicker({ value, onChange, name = 'avatar' }) {
  return (
    <fieldset>
      <legend className="mb-1 text-sm text-muted">Avatar</legend>
      <div className="grid grid-cols-4 gap-2 sm:grid-cols-6">
        {AVATARS.map((a) => (
          <label key={a.id} className="relative cursor-pointer">
            <input type="radio" name={name} value={a.id} checked={value === a.id} onChange={() => onChange(a.id)} className="peer sr-only" />
            <span className="block rounded-xl p-0.5 ring-offset-2 ring-offset-surface peer-checked:ring-2 peer-checked:ring-text peer-focus-visible:ring-2 peer-focus-visible:ring-accent-text">
              <Avatar avatar={a.id} size="h-full w-full aspect-square" />
            </span>
            <span className="sr-only">{a.name}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
