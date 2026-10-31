import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Row from '../components/Row'
import RemindButton from '../components/RemindButton'
import { ErrorBox, PageTitle, setDocTitle } from '../components/ui'
import { formatDay, isFuture } from '../lib/utils'

const section = (name) => ({ queryKey: ['latest', name], queryFn: () => api('/catalog', { params: { section: name, type: 'all' } }), staleTime: 5 * 60_000 })

// New & Popular: what is coming (with a reminder), what is hot now, and what was added most recently.
export default function Latest() {
  useEffect(() => setDocTitle('New & popular'), [])
  const soon = useQuery(section('upcoming'))
  const hot = useQuery(section('trending'))
  const added = useQuery(section('recent'))
  const coming = (soon.data?.items ?? []).filter((t) => isFuture(t.release_date)).sort((a, b) => a.release_date.localeCompare(b.release_date))
  return (
    <div className="px-4 py-6 sm:px-8">
      <PageTitle sub="What is arriving, what people are watching, and what we added lately.">New &amp; popular</PageTitle>

      <section aria-labelledby="soon-h" className="mb-10">
        <h2 id="soon-h" className="mb-3 text-xl font-semibold">Coming soon</h2>
        {soon.isLoading && <div className="space-y-2" aria-hidden>{[0, 1, 2].map((i) => <div key={i} className="skeleton h-24" />)}</div>}
        <ErrorBox error={soon.error} onRetry={soon.refetch} />
        {soon.data?.message && <p className="mb-2 text-sm text-warn">{soon.data.message}</p>}
        {soon.data && !coming.length && !soon.isError && <p className="text-muted">Nothing with a future release date right now.</p>}
        <ul className="space-y-2">
          {coming.map((t) => (
            <li key={t.id} className="card flex flex-wrap items-center gap-3 p-3">
              {t.poster_url ? <img src={t.poster_url} alt="" loading="lazy" className="h-24 w-16 rounded object-cover" /> : <span className="h-24 w-16 rounded bg-surface" aria-hidden />}
              <div className="min-w-0 flex-1 basis-48">
                <Link to={`/title/${t.id}`} className="block break-words text-lg font-semibold hover:underline">{t.name}</Link>
                <div className="text-sm text-muted">Arrives {formatDay(t.release_date)} · {t.type === 'series' ? 'Series' : 'Movie'}{t.genres?.length ? ` · ${t.genres.slice(0, 3).join(', ')}` : ''}</div>
              </div>
              <div className="flex items-center gap-2"><RemindButton id={t.id} /></div>
            </li>
          ))}
        </ul>
      </section>

      <div className="-mx-4 sm:-mx-8">
        <ErrorBox error={hot.error} onRetry={hot.refetch} className="mx-4 sm:mx-8" />
        <Row title="Popular right now" items={hot.data?.items} />
        <ErrorBox error={added.error} onRetry={added.refetch} className="mx-4 sm:mx-8" />
        <Row title="Recently added here" items={added.data?.items} />
      </div>
    </div>
  )
}
