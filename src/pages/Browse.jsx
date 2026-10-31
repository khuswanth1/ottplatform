import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Grid, GridSkeleton } from '../components/Row'
import { ErrorBox, Notice, PageTitle, setDocTitle } from '../components/ui'
import { pageParam } from '../lib/utils'
import { COUNTRIES, useCountry } from '../lib/region'
import { SettingsIcon } from '../components/icons'

const SECTIONS = [
  ['popular', 'Popular'],
  ['trending', 'Trending'],
  ['top_rated', 'Top rated'],
  ['upcoming', 'Upcoming'],
  ['recent', 'Recently added'],
  ['free', 'Free to watch here'],
]
const AVAILABILITY = { free: 'Free to watch', subscription: 'With subscription', rent: 'Rent', buy: 'Buy' }
const TYPES = { movie: 'Movies', series: 'TV series', documentary: 'Documentaries' }

export function Filters({ params, setParams, showSection = false }) {
  const genres = useQuery({ queryKey: ['genres'], queryFn: () => api('/catalog/genres'), staleTime: 24 * 3600_000 })
  const langs = useQuery({ queryKey: ['languages'], queryFn: () => api('/catalog/languages'), staleTime: 24 * 3600_000 })
  const [mobileExpanded, setMobileExpanded] = useState(false)
  const set = (k) => (e) =>
    setParams(
      (p) => {
        const n = new URLSearchParams(p)
        e.target.value ? n.set(k, e.target.value) : n.delete(k)
        return n
      },
      { replace: true },
    )
  const get = (k) => params.get(k) || ''
  const region = useCountry()
  const regionName = COUNTRIES.find(([c]) => c === region)?.[1] || region

  const activeCount = ['section', 'type', 'genre', 'original_language', 'origin_country', 'availability', 'year'].filter(
    (k) => !!get(k),
  ).length

  return (
    <div className="mb-6 space-y-2">
      <div className="flex sm:hidden items-center justify-between">
        <button
          type="button"
          className="btn btn-ghost !py-1.5 !px-3 text-xs flex items-center gap-2"
          onClick={() => setMobileExpanded((m) => !m)}
        >
          <SettingsIcon size={14} />
          <span>Filters {activeCount > 0 && `(${activeCount})`}</span>
          <span className="text-[10px] text-muted">{mobileExpanded ? '▲' : '▼'}</span>
        </button>
        {activeCount > 0 && (
          <button
            type="button"
            className="text-xs text-brand hover:underline"
            onClick={() => setParams({}, { replace: true })}
          >
            Clear all
          </button>
        )}
      </div>

      <div
        className={`grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-7 ${
          mobileExpanded ? 'grid' : 'hidden sm:grid'
        }`}
        role="group"
        aria-label="Catalog filters"
      >
        {showSection && (
          <select aria-label="Section" className="input text-xs sm:text-sm !py-1.5" value={get('section') || 'popular'} onChange={set('section')}>
            {SECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        )}
        <select aria-label="Content type" className="input text-xs sm:text-sm !py-1.5" value={get('type')} onChange={set('type')}>
          <option value="">All types</option>
          {Object.entries(TYPES).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <select aria-label="Genre" className="input text-xs sm:text-sm !py-1.5" value={get('genre')} onChange={set('genre')}>
          <option value="">All genres</option>
          {(genres.data || []).map((g) => <option key={g}>{g}</option>)}
        </select>
        <select aria-label="Language" className="input text-xs sm:text-sm !py-1.5" value={get('original_language')} onChange={set('original_language')}>
          <option value="">Any language</option>
          {(langs.data || []).map((l) => (
            <option key={l.code} value={l.code}>
              {l.english_name}{l.name !== l.english_name ? ` (${l.name})` : ''}
            </option>
          ))}
        </select>
        <select aria-label="Country of origin" className="input text-xs sm:text-sm !py-1.5" value={get('origin_country')} onChange={set('origin_country')}>
          <option value="">Any country</option>
          {COUNTRIES.map(([c, n]) => <option key={c} value={c}>{n}</option>)}
        </select>
        <select aria-label={`Availability in ${regionName}`} className="input text-xs sm:text-sm !py-1.5" value={get('availability')} onChange={set('availability')}>
          <option value="">Any availability</option>
          {Object.entries(AVAILABILITY).map(([v, l]) => <option key={v} value={v}>{l} ({region})</option>)}
        </select>
        <input
          aria-label="Release year"
          className="input text-xs sm:text-sm !py-1.5"
          inputMode="numeric"
          placeholder="Year"
          maxLength={4}
          value={get('year')}
          onChange={(e) => set('year')({ target: { value: e.target.value.replace(/\D/g, '') } })}
        />
      </div>
    </div>
  )
}

export function usePagedCatalog(path, params, enabled = true) {
  const { profileId } = useAuth()
  const region = useCountry()
  const key = useMemo(
    () => ({
      ...Object.fromEntries(params),
      ...(params.get('availability') ? { watch_region: region } : {}),
    }),
    [params, region],
  )
  return useInfiniteQuery({
    queryKey: ['catalog', path, key, profileId],
    queryFn: ({ pageParam: page }) => api(path, { params: { ...key, page } }),
    initialPageParam: 1,
    getNextPageParam: pageParam,
    enabled,
    placeholderData: (prev) => prev,
  })
}

export function PagedGrid({ query, empty = 'No titles match these filters.' }) {
  const items = query.data?.pages.flatMap((p) => p.items) ?? []
  const note = query.data?.pages.find((p) => p.message)
  const seen = new Set()
  const unique = items.filter((i) => !seen.has(i.id) && seen.add(i.id))
  return (
    <>
      {note && <div className="mb-4"><Notice tone={note.degraded ? 'warn' : 'info'}>{note.message}</Notice></div>}
      <ErrorBox error={query.error} onRetry={query.refetch} className="mb-4" />
      {query.isLoading ? <GridSkeleton /> : unique.length ? <Grid items={unique} /> : !query.isError && <p className="text-muted text-sm">{empty}</p>}
      {query.hasNextPage && (
        <div className="mt-8 text-center">
          <button className="btn btn-ghost !px-6 !py-2.5 text-sm font-semibold" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
            {query.isFetchingNextPage ? 'Loading...' : 'Load more titles'}
          </button>
        </div>
      )}
    </>
  )
}

export default function Browse() {
  const [params, setParams] = useSearchParams()
  const type = params.get('type') || 'all'
  useEffect(() => setDocTitle(TYPES[type] || 'Browse'), [type])
  const query = usePagedCatalog('/catalog', params)
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8">
      <PageTitle sub="Filter by language, genre and year. Titles marked 'Free here' can be streamed directly on this platform.">
        {TYPES[type] || 'Browse everything'}
      </PageTitle>
      <Filters params={params} setParams={setParams} showSection />
      <PagedGrid query={query} />
    </div>
  )
}
