import { useState, useMemo } from 'react'
import { Users, Clapperboard, ChevronLeft, ChevronRight } from 'lucide-react'

const PAGE_SIZE = 6

function PersonCard({ person, isCrew = false, index = 0 }) {
  const [imgError, setImgError] = useState(false)
  const initial = (person.name || '?').charAt(0).toUpperCase()

  return (
    <div className="group relative flex flex-col items-center text-center p-3 sm:p-4 rounded-xl bg-surface/60 hover:bg-surface border border-line/70 hover:border-brand/50 transition-all duration-200 shadow-sm hover:shadow-md hover:-translate-y-0.5">
      <div className="relative mx-auto h-20 w-20 sm:h-24 sm:w-24 overflow-hidden rounded-full bg-raised border-2 border-line/80 group-hover:border-brand/60 transition-colors shadow-md shrink-0">
        {person.profile_url && !imgError ? (
          <img
            src={person.profile_url}
            alt={person.name}
            loading="lazy"
            onError={() => setImgError(true)}
            className="h-full w-full object-cover group-hover:scale-105 transition-transform duration-300"
          />
        ) : (
          <div className="h-full w-full flex items-center justify-center bg-gradient-to-br from-brand/20 via-raised to-surface text-lg sm:text-xl font-bold text-white select-none">
            {initial}
          </div>
        )}
        {!isCrew && index < 3 && (
          <span className="absolute bottom-0 inset-x-0 bg-black/70 backdrop-blur-xs text-[10px] font-bold text-amber-400 py-0.5 border-t border-line/50">
            #{index + 1}
          </span>
        )}
      </div>

      <div className="mt-2.5 w-full">
        <h4 className="text-xs sm:text-sm font-semibold text-white group-hover:text-brand line-clamp-1 transition-colors" title={person.name}>
          {person.name}
        </h4>
        {isCrew ? (
          <div className="mt-1 space-y-0.5">
            <span className="inline-block max-w-full truncate px-2 py-0.5 rounded text-[11px] font-medium bg-brand/15 text-accent-text border border-brand/20">
              {person.job || 'Crew'}
            </span>
            {person.department && person.department !== person.job && (
              <p className="text-[10px] text-muted truncate">{person.department}</p>
            )}
          </div>
        ) : (
          <p className="mt-0.5 text-[11px] sm:text-xs text-muted line-clamp-2" title={person.character}>
            {person.character ? person.character : 'Self'}
          </p>
        )}
      </div>
    </div>
  )
}

export default function CastAndCrew({ cast = [], crew = [] }) {
  const hasCast = cast && cast.length > 0
  const hasCrew = crew && crew.length > 0

  if (!hasCast && !hasCrew) return null

  const [activeTab, setActiveTab] = useState(hasCast ? 'cast' : 'crew')
  const [selectedDept, setSelectedDept] = useState('All')
  const [page, setPage] = useState(1)

  // Compute departments for crew filter
  const departments = useMemo(() => {
    if (!hasCrew) return []
    const counts = {}
    crew.forEach((c) => {
      const dept = c.department || 'Other'
      counts[dept] = (counts[dept] || 0) + 1
    })
    const depts = Object.keys(counts).sort((a, b) => counts[b] - counts[a])
    return ['All', ...depts]
  }, [crew, hasCrew])

  // Get active list based on tab & filters
  const currentItems = useMemo(() => {
    if (activeTab === 'cast') return cast
    if (selectedDept === 'All') return crew
    return crew.filter((c) => (c.department || 'Other') === selectedDept)
  }, [activeTab, cast, crew, selectedDept])

  const totalItems = currentItems.length
  const totalPages = Math.ceil(totalItems / PAGE_SIZE) || 1
  const safePage = Math.min(Math.max(1, page), totalPages)

  const displayedItems = useMemo(() => {
    const start = (safePage - 1) * PAGE_SIZE
    return currentItems.slice(start, start + PAGE_SIZE)
  }, [currentItems, safePage])

  const handleTabChange = (tab) => {
    setActiveTab(tab)
    setPage(1)
    setSelectedDept('All')
  }

  const handleDeptChange = (dept) => {
    setSelectedDept(dept)
    setPage(1)
  }

  return (
    <section aria-label="Cast and Crew" className="space-y-4">
      {/* Header and Controls */}
      <div className="flex items-center justify-between border-b border-line pb-3">
        {hasCast && hasCrew ? (
          <div role="tablist" aria-label="Credits selection" className="flex items-center gap-1.5 p-1 bg-surface rounded-xl border border-line">
            <button
              role="tab"
              aria-selected={activeTab === 'cast'}
              onClick={() => handleTabChange('cast')}
              className={`btn !py-1.5 !px-3 text-xs sm:text-sm font-semibold rounded-lg transition-all ${
                activeTab === 'cast'
                  ? 'btn-primary shadow-sm'
                  : 'text-muted hover:text-white hover:bg-raised'
              }`}
            >
              <Users size={15} className="mr-1 inline-block" />
              Cast ({cast.length})
            </button>
            <button
              role="tab"
              aria-selected={activeTab === 'crew'}
              onClick={() => handleTabChange('crew')}
              className={`btn !py-1.5 !px-3 text-xs sm:text-sm font-semibold rounded-lg transition-all ${
                activeTab === 'crew'
                  ? 'btn-primary shadow-sm'
                  : 'text-muted hover:text-white hover:bg-raised'
              }`}
            >
              <Clapperboard size={15} className="mr-1 inline-block" />
              Crew ({crew.length})
            </button>
          </div>
        ) : (
          <h2 className="text-base sm:text-xl font-bold text-white flex items-center gap-2">
            {hasCast ? <Users size={20} className="text-brand" /> : <Clapperboard size={20} className="text-brand" />}
            {hasCast ? `Cast (${cast.length})` : `Crew (${crew.length})`}
          </h2>
        )}

        {/* Prev and Next navigation buttons */}
        {totalItems > PAGE_SIZE && (
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              aria-label="Previous 6"
              disabled={safePage <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="btn btn-ghost !py-1.5 !px-2.5 sm:!px-3 text-xs font-semibold rounded-lg disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1"
            >
              <ChevronLeft size={16} />
              <span>Prev</span>
            </button>
            <span className="text-xs text-muted font-medium px-1 select-none">
              {safePage} / {totalPages}
            </span>
            <button
              type="button"
              aria-label="Next 6"
              disabled={safePage >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="btn btn-ghost !py-1.5 !px-2.5 sm:!px-3 text-xs font-semibold rounded-lg disabled:opacity-30 disabled:cursor-not-allowed flex items-center gap-1"
            >
              <span>Next</span>
              <ChevronRight size={16} />
            </button>
          </div>
        )}
      </div>

      {/* Crew Department Filter Pills */}
      {activeTab === 'crew' && departments.length > 2 && (
        <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pb-1">
          {departments.map((dept) => (
            <button
              key={dept}
              onClick={() => handleDeptChange(dept)}
              className={`px-2.5 py-1 rounded-full text-xs font-medium whitespace-nowrap transition-colors ${
                selectedDept === dept
                  ? 'bg-brand/20 text-brand border border-brand/40'
                  : 'bg-surface text-muted hover:text-white hover:bg-raised border border-line'
              }`}
            >
              {dept}
            </button>
          ))}
        </div>
      )}

      {/* Grid of 6 Persons */}
      <div className="grid grid-cols-2 xs:grid-cols-3 sm:grid-cols-3 md:grid-cols-6 gap-3 sm:gap-4 min-h-[170px]">
        {displayedItems.map((person, idx) => {
          const globalIdx = (safePage - 1) * PAGE_SIZE + idx
          const key = (person.name || '') + (person.character || person.job || globalIdx)
          return (
            <PersonCard
              key={key}
              person={person}
              isCrew={activeTab === 'crew'}
              index={globalIdx}
            />
          )
        })}
      </div>
    </section>
  )
}
