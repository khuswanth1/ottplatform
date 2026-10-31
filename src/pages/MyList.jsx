import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { usePagedCatalog, PagedGrid } from './Browse'
import { ErrorBox, PageTitle, setDocTitle } from '../components/ui'

const TABS = [['watchlist', 'My list'], ['favorite', 'Favorites'], ['history', 'Viewing activity']]

const PAGE = 50
const MAX = 100

// Viewing activity: newest first. Removing an entry also drops it from Continue Watching on Home.
export function History() {
  const { profileId } = useAuth()
  const qc = useQueryClient()
  const [limit, setLimit] = useState(PAGE)
  const [notice, setNotice] = useState('')
  const q = useQuery({ queryKey: ['history', profileId, limit], queryFn: () => api('/watch-progress', { params: { history: true, limit } }), placeholderData: keepPreviousData })
  const remove = useMutation({
    mutationFn: ({ entry, series }) => (series
      ? api('/watch-progress', { method: 'DELETE', params: { title_id: entry.title.id } })
      : api(`/watch-progress/${entry.id}`, { method: 'DELETE' })),
    onSuccess: (_, { entry, series }) => {
      setNotice(series ? `Removed “${entry.title.name}” from your viewing activity.` : `Removed “${entry.title.name}”${entry.episode_label ? ` (${entry.episode_label})` : ''} from your viewing activity.`)
      qc.invalidateQueries({ queryKey: ['history'] })
      qc.invalidateQueries({ queryKey: ['continue'] })
      qc.invalidateQueries({ queryKey: ['recs'] })
    },
  })
  if (q.isLoading) return <div className="space-y-2" aria-hidden>{[0, 1, 2, 3].map((i) => <div key={i} className="skeleton h-20" />)}</div>
  return (
    <>
      <ErrorBox error={q.error || remove.error} onRetry={q.error ? q.refetch : undefined} className="mb-3" />
      <p role="status" className="sr-only">{notice}</p>
      {notice && <p className="mb-3 text-sm text-muted" aria-hidden>{notice}</p>}
      {!q.data?.length && !q.isError && <p className="text-muted">Nothing watched yet. What you play on this profile shows up here.</p>}
      <ul className="space-y-2">
        {q.data?.map((p) => {
          const pct = p.duration_seconds ? Math.round((p.position_seconds / p.duration_seconds) * 100) : 0
          return (
            <li key={p.id} className="card flex flex-wrap items-center gap-3 p-3">
              {p.title.poster_url && <img src={p.title.poster_url} alt="" loading="lazy" className="h-16 w-11 rounded object-cover" />}
              <div className="min-w-0 flex-1 basis-40">
                <Link to={`/title/${p.title.id}`} className="block break-words font-medium hover:underline">{p.title.name}</Link>
                <div className="text-xs text-muted">{p.episode_label || 'Movie'} · {p.completed ? 'Watched' : `${pct}%`} · {new Date(p.updated_at).toLocaleDateString()}</div>
              </div>
              <div className="flex flex-wrap gap-2">
                {p.title.direct && <Link className="btn btn-ghost" to={`/watch/${p.title.id}${p.episode_id ? `?episode=${p.episode_id}` : ''}`}>{p.completed ? 'Rewatch' : 'Resume'}</Link>}
                <button className="btn btn-ghost" disabled={remove.isPending} aria-label={`Remove ${p.title.name}${p.episode_label ? ` ${p.episode_label}` : ''} from viewing activity`}
                  onClick={() => remove.mutate({ entry: p, series: false })}>Remove</button>
                {p.episode_id && (
                  <button className="btn btn-ghost" disabled={remove.isPending} aria-label={`Remove every episode of ${p.title.name} from viewing activity`}
                    onClick={() => confirm(`Remove every episode of “${p.title.name}” from your viewing activity?`) && remove.mutate({ entry: p, series: true })}>Remove series</button>
                )}
              </div>
            </li>
          )
        })}
      </ul>
      {q.data?.length >= limit && limit < MAX && <button className="btn btn-ghost mt-4" disabled={q.isFetching} onClick={() => setLimit(MAX)}>Show more</button>}
      {q.data?.length >= MAX && <p className="mt-4 text-xs text-muted">Showing your latest {MAX} entries.</p>}
    </>
  )
}

export default function MyList() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') || 'watchlist'
  useEffect(() => setDocTitle('My list'), [])
  const listParams = new URLSearchParams({ kind: tab })
  const q = usePagedCatalog('/watchlist', listParams, tab !== 'history')
  return (
    <div className="px-4 py-6 sm:px-8">
      <PageTitle>My space</PageTitle>
      <div role="tablist" className="mb-5 flex gap-2">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`btn ${tab === k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setParams({ tab: k })}>{l}</button>)}
      </div>
      {tab === 'history' ? <History /> : <PagedGrid query={q} empty="Nothing here yet. Use “+ My list” on any title." />}
    </div>
  )
}
