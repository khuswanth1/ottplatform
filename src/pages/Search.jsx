import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Filters, PagedGrid, usePagedCatalog } from './Browse'
import { PageTitle, setDocTitle, useDebounced } from '../components/ui'

function DebouncedParam({ name, label, params, setParams }) {
  const urlValue = params.get(name) || ''
  const [value, setValue] = useState(urlValue)
  const debounced = useDebounced(value, 400)
  useEffect(() => { setValue(urlValue) }, [urlValue]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (debounced === urlValue) return
    setParams((p) => { const n = new URLSearchParams(p); debounced ? n.set(name, debounced) : n.delete(name); return n }, { replace: true })
  }, [debounced]) // eslint-disable-line react-hooks/exhaustive-deps
  return <input className="input text-xs sm:text-sm !py-2" aria-label={label} placeholder={label} maxLength={100} value={value} onChange={(e) => setValue(e.target.value)} />
}

export default function Search() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') || ''
  const actor = params.get('actor') || ''
  useEffect(() => setDocTitle(q ? `Search: ${q}` : 'Search'), [q])
  const hasCriteria = q.trim().length >= 2 || actor.trim().length >= 2 || ['type', 'genre', 'original_language', 'year', 'origin_country', 'availability'].some((k) => params.get(k))
  const query = usePagedCatalog('/catalog/search', params, hasCriteria)

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8">
      <PageTitle sub={q ? `Results for "${q}"` : 'Search by title or actor, or browse by genre, language, country, year and availability'}>
        Search
      </PageTitle>
      <div className="mb-4 grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        <DebouncedParam name="q" label="Search title..." params={params} setParams={setParams} />
        <DebouncedParam name="actor" label="Search actor or actress..." params={params} setParams={setParams} />
      </div>
      <Filters params={params} setParams={setParams} />
      {hasCriteria ? <PagedGrid query={query} empty="No results found. Try a different spelling or fewer filters." /> : <p className="text-muted text-sm">Type at least two characters or choose a filter.</p>}
    </div>
  )
}
