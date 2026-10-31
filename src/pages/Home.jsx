import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import Row from '../components/Row'
import { Badge, ErrorBox, Notice, setDocTitle } from '../components/ui'
import { useEffect } from 'react'
import Billboard from '../components/Billboard'
import Landing from './Landing'
import { isRestricted, levelLabel } from '../lib/maturity'

function EmptyHero() {
  return (
    <section className="relative isolate -mt-36 sm:-mt-16 grid min-h-[70vh] place-items-center overflow-hidden px-6 text-center">
      <img src="https://image.tmdb.org/t/p/w500/1E5baAaEse26fej7uHcjOgEE2t2.jpg" alt="" className="absolute inset-0 -z-20 h-full w-full object-cover opacity-30 blur-sm" />
      <div className="absolute inset-0 -z-10 bg-gradient-to-t from-bg via-black/60 to-black/70" />
      <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,color-mix(in_srgb,var(--color-accent)_35%,transparent),transparent_60%)]" />
      <div className="max-w-2xl">
        <h1 className="text-4xl font-black sm:text-6xl">Find something worth watching.</h1>
        <p className="mt-4 text-lg text-text">The catalog is empty. Add a TMDB key to <code>backend/.env</code> or publish titles from the admin dashboard.</p>
        <div className="mt-6 flex justify-center gap-3">
          <Link to="/register" className="btn btn-primary !px-6 !py-3 !text-base">Get started</Link>
          <Link to="/login" className="btn btn-dim !px-6 !py-3 !text-base">Sign in</Link>
        </div>
      </div>
    </section>
  )
}

function ContinueRow() {
  const { user, profileId } = useAuth()
  const q = useQuery({ queryKey: ['continue', profileId], queryFn: () => api('/watch-progress', { params: { limit: 12 } }), enabled: !!user && !!profileId })
  if (!q.data?.length) return null
  return (
    <section className="mb-8" aria-label="Continue watching">
      <h2 className="mb-2 px-4 text-lg font-semibold sm:px-12 sm:text-xl">Continue watching</h2>
      <div className="no-scrollbar flex gap-3 overflow-x-auto px-4 pb-2 sm:px-12">
        {q.data.map((p) => {
          const pct = p.duration_seconds ? Math.min(100, (p.position_seconds / p.duration_seconds) * 100) : 0
          return (
            <Link
              key={`${p.title.id}-${p.episode_id || ''}`}
              to={`/title/${p.title.id}`}
              className="group relative w-[220px] shrink-0 block"
            >
              <div className="relative aspect-video overflow-hidden rounded-lg bg-surface border border-line/60 shadow-md transition-all duration-300 group-hover:scale-105 group-hover:shadow-xl">
                {(p.title.backdrop_url || p.title.poster_url) && (
                  <img
                    src={p.title.backdrop_url || p.title.poster_url}
                    alt=""
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                )}
                <div className="absolute inset-x-0 bottom-0 h-1 bg-black/60">
                  <div className="h-full bg-brand" style={{ width: `${pct}%` }} />
                </div>
              </div>
              <div className="mt-1.5 truncate text-sm font-medium text-text group-hover:text-white transition-colors">
                {p.title.name}
              </div>
              {p.episode_label && <div className="truncate text-xs text-muted">{p.episode_label}</div>}
            </Link>
          )
        })}
      </div>
    </section>
  )
}

// Picks from this profile's own history, ratings and lists; the server returns nothing until there is something to go on.
function PickedRow() {
  const { user, profileId } = useAuth()
  const q = useQuery({ queryKey: ['recs', profileId], queryFn: () => api('/catalog/recommended'), enabled: !!user && !!profileId, staleTime: 5 * 60_000 })
  return <Row title="Picked for you" items={q.data} />
}

function MemberHome() {
  const { profileId, activeProfile } = useAuth()
  const q = useQuery({ queryKey: ['home', profileId], queryFn: () => api('/catalog/home'), staleTime: 5 * 60_000 })
  useEffect(() => setDocTitle(''), [])
  const featured = useQuery({ queryKey: ['featured', profileId], queryFn: () => api('/catalog/featured'), staleTime: 5 * 60_000 })
  const rows = q.data?.rows ?? []
  const trendingHero = rows.find((r) => r.id === 'trending')?.items?.find((t) => t.backdrop_url)
  // curated titles first; a failed or empty featured call must never blank the hero, so fall back to trending
  const hero = featured.data?.some((t) => t.backdrop_url) ? featured.data : trendingHero ? [trendingHero] : []

  return (
    <div className="pb-10">
      <h1 className="sr-only">Home</h1>
      {q.isLoading && <div className="skeleton -mt-36 sm:-mt-16 mb-8 h-[60vh]" aria-hidden />}
      <Billboard titles={hero} />
      <div className="relative z-10 space-y-3 px-4 sm:px-12">
        {q.isError && <ErrorBox error={q.error} onRetry={q.refetch} />}
        {q.data?.degraded && <Notice>Some catalog sources are temporarily unavailable. You may be seeing partial or cached results.</Notice>}
        {q.data && !q.data.providers?.tmdb && <Notice>Discovery needs a TMDB key on the server (TMDB_READ_TOKEN). Only locally curated titles are shown.</Notice>}
        {isRestricted(activeProfile) && <Badge tone={activeProfile.is_kids ? 'kids' : 'neutral'}>{levelLabel(activeProfile)} profile</Badge>}
      </div>
      <div className="relative z-10 -mt-12"><ContinueRow /></div>
      <div className="relative z-10"><PickedRow /></div>
      <div className="relative z-10">{rows.map((r) => <Row key={r.id} title={r.title} items={r.items} ranked={!!r.ranked} />)}</div>
      {q.isLoading && <div className="px-4 sm:px-12 flex gap-3 overflow-hidden" aria-hidden>{Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton aspect-[2/3] w-[150px] shrink-0" />)}</div>}
      {q.data && !rows.length && !q.isError && <EmptyHero />}
    </div>
  )
}

// Signed-out visitors get the landing page; members get their personalised home. While we do not yet know which,
// show a placeholder so the wrong page never flashes.
export default function Home() {
  const { user, loading } = useAuth()
  if (loading) return <div className="skeleton -mt-36 sm:-mt-16 h-[60vh]" aria-hidden />
  return user ? <MemberHome /> : <Landing />
}
