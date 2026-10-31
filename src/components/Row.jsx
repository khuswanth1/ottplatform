import { useRef } from 'react'
import TitleCard from './TitleCard'

export function RankedCard({ title, rank }) {
  return (
    <div className="flex shrink-0 snap-start items-end">
      <span
        aria-hidden
        className="-mr-2.5 sm:-mr-4 select-none text-[85px] xs:text-[105px] sm:text-[130px] lg:text-[160px] font-black leading-[0.78] text-bg"
        style={{
          WebkitTextStroke: '2.5px var(--color-border-input, #8a8a96)',
          filter: 'drop-shadow(0 4px 6px rgba(0,0,0,0.5))',
        }}
      >
        {rank}
      </span>
      <TitleCard title={title} rank={rank} className="w-[100px] xs:w-[115px] sm:w-[135px] lg:w-[155px]" />
    </div>
  )
}

export default function Row({ title, items, children, ranked = false }) {
  const ref = useRef(null)
  if (!items?.length) return null

  const scroll = (dir) => {
    if (!ref.current) return
    ref.current.scrollBy({ left: dir * ref.current.clientWidth * 0.8, behavior: 'smooth' })
  }

  return (
    <section className="group/row relative mb-6 sm:mb-10" aria-label={title}>
      <div className="flex items-center justify-between mb-2.5 px-4 sm:px-12">
        <h2 className="text-base sm:text-xl font-bold tracking-tight text-white hover:text-brand transition-colors">
          {title}
        </h2>
      </div>

      <button
        type="button"
        aria-label={`Scroll ${title} left`}
        className="absolute bottom-4 left-0 top-11 z-30 hidden w-11 items-center justify-center bg-black/60 hover:bg-black/90 backdrop-blur-sm text-2xl text-white opacity-0 transition-all duration-200 group-hover/row:opacity-100 sm:flex rounded-r-lg"
        onClick={() => scroll(-1)}
      >
        ‹
      </button>
      <button
        type="button"
        aria-label={`Scroll ${title} right`}
        className="absolute bottom-4 right-0 top-11 z-30 hidden w-11 items-center justify-center bg-black/60 hover:bg-black/90 backdrop-blur-sm text-2xl text-white opacity-0 transition-all duration-200 group-hover/row:opacity-100 sm:flex rounded-l-lg"
        onClick={() => scroll(1)}
      >
        ›
      </button>

      <div
        ref={ref}
        className="no-scrollbar -my-3 flex gap-2.5 sm:gap-3.5 overflow-x-auto px-4 py-4 sm:px-12 snap-x snap-mandatory"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        {ranked
          ? items.slice(0, 10).map((t, i) => <RankedCard key={t.id} title={t} rank={i + 1} />)
          : items.map((t) => (
              <TitleCard
                key={t.id}
                title={t}
                className="w-[115px] xs:w-[130px] sm:w-[155px] md:w-[175px] lg:w-[195px] snap-start"
              />
            ))}
        {children}
      </div>
    </section>
  )
}

export function Grid({ items }) {
  return (
    <div className="grid grid-cols-2 xs:grid-cols-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2.5 sm:gap-4">
      {items.map((t) => <TitleCard key={t.id} title={t} />)}
    </div>
  )
}

export function GridSkeleton({ n = 12 }) {
  return (
    <div className="grid grid-cols-2 xs:grid-cols-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2.5 sm:gap-4" aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="skeleton aspect-[2/3] rounded-lg" />
      ))}
    </div>
  )
}
