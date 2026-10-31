import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { CheckIcon, FilmIcon, HeartIcon, PlayIcon, PlusIcon, ThumbsDownIcon, ThumbsUpIcon } from '../components/icons'
import Row from '../components/Row'
import { Badge, ErrorBox, Notice, Spinner, setDocTitle } from '../components/ui'
import { COUNTRIES, useCountry } from '../lib/region'
import RemindButton from '../components/RemindButton'
import CastAndCrew from '../components/CastAndCrew'
import { KIND_LABEL, formatDay, formatRuntime, groupExternal, isFuture, isSafeExternalUrl } from '../lib/utils'


function WatchlistButtons({ id }) {
  const { user, profileId } = useAuth()
  const qc = useQueryClient()
  const nav = useNavigate()
  const ids = useQuery({ queryKey: ['watchlist-ids', profileId], queryFn: () => api('/watchlist/ids'), enabled: !!user && !!profileId })
  const toggle = useMutation({
    mutationFn: ({ kind, on }) => api(`/watchlist/${id}`, { method: on ? 'DELETE' : 'PUT', params: on ? { kind } : undefined, body: on ? undefined : { kind } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['watchlist-ids'] }); qc.invalidateQueries({ queryKey: ['mylist'] }); qc.invalidateQueries({ queryKey: ['recs'] }) },
  })
  const btn = (kind, onLabel, offLabel) => {
    const on = ids.data?.[kind]?.includes(id)
    return (
      <button className="btn btn-ghost text-xs sm:text-sm" aria-pressed={!!on} disabled={toggle.isPending}
        onClick={() => (user ? toggle.mutate({ kind, on }) : nav('/login'))}>
        {on ? onLabel : offLabel}
      </button>
    )
  }
  return <>{btn('watchlist', <><CheckIcon size={16} /> In my list</>, <><PlusIcon size={16} /> My list</>)}{btn('favorite', <><HeartIcon size={16} fill /> Favorite</>, <><HeartIcon size={16} /> Favorite</>)}</>
}

export function RatingButtons({ id }) {
  const { user, profileId } = useAuth()
  const qc = useQueryClient()
  const key = ['rating', id, profileId]
  const q = useQuery({ queryKey: key, queryFn: () => api(`/titles/${id}/rating`), enabled: !!user && !!profileId })
  const set = useMutation({
    mutationFn: ({ value, clear }) => api(`/titles/${id}/rating`, clear ? { method: 'DELETE' } : { method: 'PUT', body: { value } }),
    onSuccess: (data) => { qc.setQueryData(key, data); qc.invalidateQueries({ queryKey: ['recs'] }) },
  })
  if (!user) return null
  const current = q.data?.value ?? null
  const opt = (value, label, icon) => (
    <button key={value} className="btn btn-ghost !p-2 text-xs sm:text-sm" aria-pressed={current === value} aria-label={label} title={label}
      disabled={set.isPending || q.isLoading} onClick={() => set.mutate({ value, clear: current === value })}>{icon}</button>
  )
  return (
    <div role="group" aria-label="Rate this title" className="flex gap-1">
      {opt(-1, 'Not for me', <ThumbsDownIcon size={16} fill={current === -1} />)}
      {opt(1, 'I like this', <ThumbsUpIcon size={16} fill={current === 1} />)}
      {set.isError && <span role="alert" className="self-center text-xs text-warn">Could not save your rating.</span>}
    </div>
  )
}

function MoreLikeThis({ id }) {
  const country = useCountry()
  const q = useQuery({ queryKey: ['similar', id, country], queryFn: () => api(`/titles/${id}/similar`, { params: { country } }) })
  if (!q.data?.length) return null
  return <Row title="More like this" items={q.data} />
}

function Trailer({ id, name, seasonNumber, label, open: openProp, onToggle }) {
  const [openState, setOpenState] = useState(false)
  const open = openProp ?? openState
  const toggle = onToggle ?? (() => setOpenState((o) => !o))
  const q = useQuery({
    queryKey: ['trailer', id, seasonNumber],
    queryFn: () => api(`/titles/${id}/trailer`, { params: seasonNumber ? { season_number: seasonNumber } : undefined }),
    enabled: open,
  })
  if (q.isError || (q.data && !q.data.embed_url)) return null
  return (
    <>
      <button className="btn btn-ghost text-xs sm:text-sm flex items-center gap-1.5" aria-expanded={open} onClick={toggle}>
        <FilmIcon size={16} /> {open ? 'Hide trailer' : (label || 'Trailer')}
      </button>
      {open && !q.data?.embed_url && <p className="basis-full text-xs text-muted mt-2">Loading trailer…</p>}
      {open && q.data?.embed_url && (
        <div className="aspect-video w-full max-w-3xl basis-full overflow-hidden rounded-xl border border-line bg-black shadow-2xl mt-3">
          <iframe title={`${name} trailer`} src={`${q.data.embed_url}?rel=0&autoplay=1`} className="h-full w-full" loading="lazy"
            allow="autoplay; fullscreen; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin"
            sandbox="allow-scripts allow-same-origin allow-presentation" />
        </div>
      )}
    </>
  )
}

function ExternalOptions({ id }) {
  const country = useCountry()
  const q = useQuery({ queryKey: ['availability', id, country], queryFn: () => api(`/titles/${id}/availability`, { params: { country } }), staleTime: 30 * 60_000 })
  if (q.isLoading) return <div className="skeleton h-24 rounded-xl" aria-hidden />
  if (q.isError) return <ErrorBox error={q.error} onRetry={q.refetch} />
  const a = q.data
  const groups = groupExternal(a.external)
  return (
    <section aria-label="Where to watch" className="card p-4 sm:p-5 rounded-xl border border-line">
      <h2 className="mb-1 text-base sm:text-lg font-bold text-white">Where to watch <span className="text-xs sm:text-sm font-normal text-muted">({COUNTRIES.find(([c]) => c === a.country)?.[1] || a.country})</span></h2>
      {a.viewer_country && a.viewer_country !== a.country && <p className="mb-2 text-xs text-muted">Showing options for {a.country}. Direct playback is decided by your actual location ({a.viewer_country}), not this selection.</p>}
      {a.direct_unavailable_reason && <p className="mb-2 text-xs sm:text-sm text-warn font-medium">Not playable here: {a.direct_unavailable_reason}</p>}
      {a.degraded && <p className="mb-2 text-xs text-warn">Availability could not be refreshed right now; showing the last known options.</p>}
      {!groups.length && <p className="text-xs sm:text-sm text-muted">No streaming options were found for this region.</p>}
      {groups.map((g) => (
        <div key={g.kind} className="mt-3">
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wider text-muted">{KIND_LABEL[g.kind]}</div>
          <ul className="flex flex-wrap gap-2">
            {g.items.map((o) => (
              <li key={o.provider + o.kind}>
                {o.web_url && isSafeExternalUrl(o.web_url) ? (
                  <a className="btn btn-ghost text-xs sm:text-sm !py-1.5 !px-3" href={o.web_url} target="_blank" rel="noopener noreferrer nofollow">
                    {o.provider}{o.price ? ` • $${o.price.toFixed(2)}` : ''}{o.format ? ` • ${o.format}` : ''} <span aria-hidden className="text-xs opacity-70">↗</span>
                    <span className="sr-only">(opens external site)</span>
                  </a>
                ) : <span className="btn btn-ghost opacity-70 text-xs sm:text-sm !py-1.5 !px-3">{o.provider}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
      {a.attribution?.length > 0 && <p className="mt-3 text-[11px] text-muted">{a.attribution.join(' ')}</p>}
    </section>
  )
}

function Episodes({ title }) {
  const seasons = title.seasons
  const [season, setSeason] = useState(seasons[0]?.number ?? 1)
  const q = useQuery({ queryKey: ['episodes', title.id, season], queryFn: () => api(`/titles/${title.id}/episodes`, { params: { season } }), enabled: seasons.length > 0 })
  if (!seasons.length) return null
  return (
    <section aria-label="Episodes" className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h2 className="text-base sm:text-xl font-bold text-white">Episodes</h2>
        <div className="flex items-center gap-2">
          <Trailer id={title.id} name={`${title.name} Season ${season}`} seasonNumber={season} label={`Season ${season} Trailer`} />
          <select aria-label="Season selector" className="input !w-auto !py-1.5 text-xs sm:text-sm font-medium bg-surface" value={season} onChange={(e) => setSeason(Number(e.target.value))}>
            {seasons.map((s) => <option key={s.id} value={s.number}>{s.name || `Season ${s.number}`}</option>)}
          </select>
        </div>
      </div>
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} onRetry={q.refetch} />
      <ol className="space-y-2.5">
        {q.data?.map((e) => (
          <li key={e.id} className="card flex flex-col sm:flex-row gap-3 p-3.5 rounded-xl border border-line/70 hover:border-brand/50 transition-colors">
            {e.still_url && <img src={e.still_url} alt="" loading="lazy" className="h-32 sm:h-20 w-full sm:w-36 rounded-lg object-cover shrink-0" />}
            <div className="min-w-0 flex-1 space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold text-sm sm:text-base text-white truncate">{e.number}. {e.name}</span>
                {e.runtime_minutes && <span className="text-xs text-muted shrink-0">{formatRuntime(e.runtime_minutes)}</span>}
              </div>
              <p className="text-xs sm:text-sm text-text-muted line-clamp-2">{e.overview || 'No description provided.'}</p>
            </div>
            {title.id && (
              <div className="self-end sm:self-center shrink-0 flex items-center gap-2">
                <Link to={`/watch/${title.id}?episode=${e.id}`} className="btn btn-primary !py-1.5 !px-3 text-xs sm:text-sm font-semibold flex items-center gap-1">
                  <PlayIcon size={14} fill /> Play
                </Link>
              </div>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}

export default function TitlePage() {
  const { id } = useParams()
  const { user, activeProfile } = useAuth()
  const q = useQuery({ queryKey: ['title', id, activeProfile?.id], queryFn: () => api(`/titles/${id}`) })
  const progressQuery = useQuery({
    queryKey: ['title-progress', id, activeProfile?.id],
    queryFn: () => api(`/watch-progress/title/${id}`),
    enabled: !!user && !!activeProfile?.id,
  })
  const [trailerOpen, setTrailerOpen] = useState(() => new URLSearchParams(window.location.search).get('trailer') === '1')
  const t = q.data
  useEffect(() => { if (t) setDocTitle(t.name) }, [t])

  if (q.isLoading) return <Spinner />
  if (q.isError) return <div className="p-6"><ErrorBox error={q.error} onRetry={q.refetch} /><Link to="/" className="btn btn-ghost mt-4">← Home</Link></div>

  const progress = progressQuery.data
  const isWatched = progress && progress.position_seconds > 5 && !progress.completed
  const resumeEpisodeId = progress?.episode_id
  // a series without history has no episode in the address: the server starts at season 1 episode 1
  const watchLink = t.type === 'series' && resumeEpisodeId
    ? `/watch/${t.id}?episode=${resumeEpisodeId}`
    : `/watch/${t.id}`
  return (
    <article className="min-h-screen">
      <div className="relative isolate -mt-[var(--nav-h,3.5rem)] sm:-mt-[var(--nav-h,4.25rem)] overflow-hidden">
        {t.backdrop_url && <img src={t.backdrop_url} alt="" className="absolute inset-0 -z-10 h-full w-full object-cover opacity-30 scale-105" />}
        <div className="absolute inset-0 -z-10 bg-gradient-to-t from-bg via-bg/80 to-bg/40" />

        <div className="mx-auto max-w-7xl flex flex-col sm:flex-row gap-6 px-4 pb-8 pt-24 sm:pt-28 sm:px-8">
          {t.poster_url && (
            <div className="w-36 xs:w-44 sm:w-56 shrink-0 mx-auto sm:mx-0">
              <img src={t.poster_url} alt={`${t.name} poster`} className="w-full rounded-xl border border-line shadow-2xl aspect-[2/3] object-cover" />
            </div>
          )}

          <div className="min-w-0 flex-1 space-y-3.5 text-center sm:text-left">
            <h1 className="text-2xl xs:text-3xl sm:text-5xl font-black text-white tracking-tight">{t.name}</h1>
            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2 text-xs sm:text-sm text-muted">
              {t.year && <span className="font-medium text-white">{t.year}</span>}
              {isFuture(t.release_date) && <Badge tone="premium">Arrives {formatDay(t.release_date)}</Badge>}
              {t.age_rating && <Badge>{t.age_rating}</Badge>}
              {t.runtime_minutes && <span>{formatRuntime(t.runtime_minutes)}</span>}
              {t.vote_average > 0 && <span className="text-amber-400 font-semibold">★ {t.vote_average.toFixed(1)}</span>}
              <span>{t.type === 'series' ? 'Series' : 'Movie'}</span>
              {t.original_language && <span>{t.original_language.toUpperCase()}</span>}
              {t.direct ? <Badge tone={t.direct.entitlement === 'premium' ? 'premium' : 'free'}>{t.direct.label}</Badge> : <Badge>Not playable directly</Badge>}
            </div>

            <div className="flex flex-wrap justify-center sm:justify-start gap-1.5">
              {t.genres.map((g) => <Badge key={g}>{g}</Badge>)}
            </div>

            <p className="max-w-3xl text-sm sm:text-base text-text-muted leading-relaxed">{t.synopsis || 'No synopsis available.'}</p>

            <div className="flex flex-wrap items-center justify-center sm:justify-start gap-2 pt-2">
              <div className="flex flex-col items-start gap-1">
                <Link
                  to={user ? watchLink : '/login'}
                  state={user ? undefined : { from: watchLink }}
                  className="btn btn-primary !py-2 !px-5 text-sm sm:text-base font-bold shadow-lg flex items-center gap-2 hover:scale-[1.02] active:scale-[0.98] transition-transform"
                  title={isWatched ? 'Resume playback' : 'Start watching'}
                >
                  <PlayIcon size={18} fill />
                  <span>{isWatched ? (progress.episode_label ? `Resume ${progress.episode_label}` : 'Resume') : 'Play'}</span>
                </Link>
                {isWatched && progress.duration_seconds > 0 && (
                  <div className="w-full max-w-[140px] px-0.5">
                    <div className="h-1 w-full bg-white/20 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-brand rounded-full transition-all"
                        style={{ width: `${Math.min(100, Math.max(5, Math.round((progress.position_seconds / progress.duration_seconds) * 100)))}%` }}
                      />
                    </div>
                    <span className="text-[10px] text-muted block mt-0.5">
                      {Math.max(1, Math.round((progress.duration_seconds - progress.position_seconds) / 60))}m left
                    </span>
                  </div>
                )}
              </div>
              <WatchlistButtons id={t.id} />
              <RatingButtons id={t.id} />
              {isFuture(t.release_date) && <RemindButton id={t.id} />}
              <Trailer id={t.id} name={t.name} open={trailerOpen} onToggle={() => setTrailerOpen((o) => !o)} />
            </div>

            {t.audio_languages.length > 0 && (
              <p className="text-xs sm:text-sm text-muted">
                Audio: {t.audio_languages.join(', ')}{t.subtitle_languages.length ? ` • Subtitles: ${t.subtitle_languages.join(', ')}` : ''}
              </p>
            )}
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl grid gap-8 px-4 pb-12 sm:px-8 lg:grid-cols-[1fr_360px]">
        <div className="space-y-8">
          {t.type === 'series' && <Episodes title={t} />}
          <CastAndCrew cast={t.cast} crew={t.crew} />
        </div>

        <div className="space-y-4">
          <ExternalOptions id={t.id} />
          {!t.direct && <Notice>This title cannot be streamed directly on CineVerse. Use an authorized provider above to stream.</Notice>}
        </div>
      </div>

      <div className="mx-auto max-w-7xl pb-6">
        <MoreLikeThis id={t.id} />
      </div>

      {t.attribution.length > 0 && (
        <p className="mx-auto max-w-7xl px-4 pb-8 text-[11px] text-muted sm:px-8">{t.attribution.join(' ')}</p>
      )}
    </article>
  )
}
