import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { PlayIcon } from './icons'

const ROTATE_MS = 8000

export default function Billboard({ titles }) {
  const items = (titles || []).filter((t) => t.backdrop_url)
  const [i, setI] = useState(0)
  const [paused, setPaused] = useState(false)
  const reduced = useRef(typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches)

  useEffect(() => { if (i >= items.length) setI(0) }, [items.length, i])
  useEffect(() => {
    if (items.length < 2 || paused || reduced.current) return undefined
    const t = setTimeout(() => setI((n) => (n + 1) % items.length), ROTATE_MS)
    return () => clearTimeout(t)
  }, [i, items.length, paused])

  const title = items[i]
  if (!title) return null
  const meta = [title.year, title.age_rating, title.genres?.slice(0, 3).join(' • ')].filter(Boolean).join(' • ')

  return (
    <section
      aria-roledescription="carousel" aria-label="Featured"
      className="relative isolate -mt-[var(--nav-h,3.5rem)] sm:-mt-[var(--nav-h,4.25rem)] mb-4 min-h-[62vh] sm:min-h-[75vh] md:min-h-[82vh] overflow-hidden"
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}
    >
      <img
        key={title.id}
        src={title.backdrop_url}
        alt=""
        className="absolute inset-0 -z-10 h-full w-full object-cover object-center scale-105 transition-transform duration-1000 ease-out"
        fetchpriority={i === 0 ? 'high' : 'auto'}
      />
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-bg via-bg/40 to-transparent sm:bg-gradient-to-r sm:from-black/85 sm:via-black/35 sm:to-transparent" />
      <div className="absolute inset-x-0 bottom-0 -z-10 h-28 sm:h-48 bg-gradient-to-t from-bg via-bg/70 to-transparent" />

      <div
        className="flex min-h-[62vh] sm:min-h-[75vh] md:min-h-[82vh] max-w-2xl flex-col justify-end gap-3 sm:gap-4 px-4 pb-12 sm:px-12 sm:pb-24 pt-20"
        aria-live={paused ? 'polite' : 'off'}
      >
        <h1 className="text-2xl xs:text-3xl sm:text-5xl md:text-6xl font-black drop-shadow-xl tracking-tight leading-tight line-clamp-2">
          <Link to={`/title/${title.id}`} className="hover:text-brand transition-colors">
            {title.name}
          </Link>
        </h1>
        {meta && (
          <p className="text-xs sm:text-sm font-medium text-text drop-shadow-md flex items-center gap-2 flex-wrap">
            {meta}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2.5 sm:gap-3.5 pt-1">
          <Link
            to={title.direct ? `/watch/${title.id}` : `/title/${title.id}`}
            className="btn btn-light !px-4 sm:!px-6 !py-2 sm:!py-2.5 !text-sm sm:!text-base font-bold shadow-lg shadow-black/40 hover:scale-105 active:scale-95 transition-transform"
          >
            <PlayIcon size={18} fill /> {title.direct ? 'Play Now' : 'Where to watch'}
          </Link>
          <Link
            to={`/title/${title.id}`}
            className="btn btn-dim !px-4 sm:!px-6 !py-2 sm:!py-2.5 !text-sm sm:!text-base font-semibold shadow-lg hover:scale-105 active:scale-95 transition-transform"
          >
            More Info
          </Link>
        </div>
      </div>

      {items.length > 1 && (
        <div className="absolute bottom-4 right-4 flex gap-1.5 sm:gap-2 sm:right-12 z-20" role="group" aria-label="Choose featured title">
          {items.map((t, n) => (
            <button
              key={t.id}
              type="button"
              aria-label={`Show ${t.name}`}
              aria-current={n === i}
              onClick={() => setI(n)}
              className={`h-1.5 sm:h-2 rounded-full transition-all duration-300 ${
                n === i ? 'w-6 sm:w-8 bg-white' : 'w-2 sm:w-2.5 bg-white/30 hover:bg-white/60'
              }`}
            />
          ))}
        </div>
      )}
    </section>
  )
}
