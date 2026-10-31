import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Player from '../components/Player'
import StillWatching from '../components/StillWatching'
import { askAfterEpisode } from '../lib/stillWatching'
import { ErrorBox, Spinner, setDocTitle } from '../components/ui'
import { formatRuntime, groupExternal, isSafeExternalUrl, KIND_LABEL } from '../lib/utils'

function Unavailable({ error, titleId }) {
  const avail = useQuery({ queryKey: ['availability', titleId], queryFn: () => api(`/titles/${titleId}/availability`), staleTime: 30 * 60_000 })
  const groups = groupExternal(avail.data?.external)
  // no full video here: show the studio's own YouTube trailer, clearly labelled, rather than a dead end
  const trailer = useQuery({ queryKey: ['trailer', titleId, undefined], queryFn: () => api(`/titles/${titleId}/trailer`), staleTime: 30 * 60_000, retry: false })
  const embed = trailer.data?.embed_url
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-4 sm:p-6">
      <div role="alert" className="card border-brand/40 p-5 rounded-xl">
        <h1 className="mb-1 text-lg sm:text-xl font-bold text-white">
          {error.code === 'stream_limit' ? 'All your screens are in use' : "This title cannot be played here"}
        </h1>
        <p className="text-sm text-text-muted">{error.message}</p>
        {error.code === 'stream_limit' && <Link to="/plans" className="btn btn-primary mt-3">See plans</Link>}
      </div>
      {error.code !== 'stream_limit' && embed && (
        <div className="space-y-2">
          <p className="text-sm text-muted">The full video is not available here. This is the trailer.</p>
          <div className="aspect-video w-full overflow-hidden rounded-xl border border-line bg-black shadow-2xl">
            <iframe title="Trailer" src={`${embed}?rel=0&autoplay=1&playsinline=1`} className="h-full w-full" allow="autoplay; fullscreen; picture-in-picture"
              allowFullScreen sandbox="allow-scripts allow-same-origin allow-presentation" referrerPolicy="strict-origin-when-cross-origin" />
          </div>
        </div>
      )}
      {groups.length > 0 && (
        <div className="card p-4 sm:p-5 rounded-xl">
          <h2 className="mb-2 font-semibold text-white">Watch it on an authorized service</h2>
          {groups.map((g) => (
            <div key={g.kind} className="mb-2">
              <div className="text-xs uppercase tracking-wide text-muted">{KIND_LABEL[g.kind]}</div>
              <div className="mt-1 flex flex-wrap gap-2">
                {g.items.filter((o) => o.web_url && isSafeExternalUrl(o.web_url)).map((o) => (
                  <a key={o.provider + o.kind} className="btn btn-ghost text-xs sm:text-sm !py-1.5" href={o.web_url} target="_blank" rel="noopener noreferrer nofollow">
                    {o.provider} ↗
                  </a>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {!embed && <Link to={`/title/${titleId}?trailer=1`} className="btn btn-primary text-xs sm:text-sm">Watch the trailer instead</Link>}
        <Link to={`/title/${titleId}`} className="btn btn-ghost text-xs sm:text-sm">← Back to title</Link>
      </div>
    </div>
  )
}

const AUTOPLAY_KEY = 'ott.autoplayNext'
const readAutoplay = () => { try { return localStorage.getItem(AUTOPLAY_KEY) === '1' } catch { return false } }

export default function Watch() {
  const { id } = useParams()
  const [params] = useSearchParams()
  const episodeId = params.get('episode') || null
  const nav = useNavigate()
  const sessionId = useRef(null)
  const [ended, setEnded] = useState(false)
  const [askNext, setAskNext] = useState(false)
  const unattended = useRef(0)
  const [autoplay, setAutoplay] = useState(readAutoplay)

  const start = useMutation({
    mutationFn: () => api('/playback/sessions', { method: 'POST', body: { title_id: id, episode_id: episodeId } }),
    onSuccess: (s) => {
      sessionId.current = s.session_id
      setDocTitle(s.title.name)
      if (!episodeId && s.episode_id) nav(`/watch/${id}?episode=${s.episode_id}`, { replace: true })
    },
  })
  const { mutate } = start

  useEffect(() => {
    const reset = () => { unattended.current = 0 }
    const events = ['pointerdown', 'keydown', 'touchstart']
    events.forEach((e) => document.addEventListener(e, reset, { passive: true }))
    return () => events.forEach((e) => document.removeEventListener(e, reset))
  }, [])

  useEffect(() => { sessionId.current = null; setEnded(false); setAskNext(false); mutate() }, [id, episodeId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => { if (sessionId.current) api(`/playback/sessions/${sessionId.current}`, { method: 'DELETE', keepalive: true }).catch(() => {}) }, [id, episodeId])

  if (start.isPending || start.isIdle) return <Spinner label="Preparing playback..." />
  if (start.isError) {
    return start.error.status === 401 || start.error.status === 0
      ? <div className="p-4 sm:p-6"><ErrorBox error={start.error} onRetry={() => mutate()} /></div>
      : <Unavailable error={start.error} titleId={id} />
  }
  const s = start.data
  if (s.title.id !== id || (episodeId && s.episode_id !== episodeId) || (!episodeId && s.episode_id && s.title.type !== 'series')) {
    return (
      <div className="p-4 sm:p-6">
        <ErrorBox error={{ message: 'The video returned did not match the title you selected. Please go back and try again.' }} onRetry={() => mutate()} />
      </div>
    )
  }
  const go = (ep) => nav(`/watch/${id}?episode=${ep}`)
  const toggleAutoplay = (on) => { setAutoplay(on); try { localStorage.setItem(AUTOPLAY_KEY, on ? '1' : '0') } catch { /* ignore */ } }
  const handleEnded = () => {
    if (!(s.next_episode_id && autoplay)) { setEnded(true); return }
    if (askAfterEpisode(unattended.current)) { setAskNext(true); return }
    unattended.current += 1
    go(s.next_episode_id)
  }

  return (
    <div className="mx-auto max-w-6xl space-y-3 px-3 sm:px-6 py-2 sm:py-4">
      <div className="flex items-center justify-between">
        <Link to={`/title/${id}`} className="text-xs sm:text-sm font-medium text-text-muted hover:text-white flex items-center gap-1">
          ← <span className="truncate max-w-[200px] sm:max-w-md">{s.title.name}</span>
        </Link>
        <div className="flex items-center gap-2">
          <span className="text-[11px] sm:text-xs text-brand font-semibold px-2 py-0.5 rounded bg-brand/10 border border-brand/20">
            HD Cinema
          </span>
        </div>
      </div>

      <div className="relative">
        <Player
          key={s.session_id}
          session={s}
          titleId={id}
          episodeId={episodeId}
          onStop={() => nav(`/title/${id}`)}
          onNext={s.next_episode_id ? () => go(s.next_episode_id) : undefined}
          onPrev={s.previous_episode_id ? () => go(s.previous_episode_id) : undefined}
          onEnded={handleEnded}
        />
        {askNext && (
          <StillWatching
            className="absolute inset-0 z-30 rounded-xl border border-line"
            onContinue={() => { unattended.current = 0; setAskNext(false); go(s.next_episode_id) }}
            onStop={() => nav(`/title/${id}`)}
          />
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <div className="flex items-center gap-3">
          <h1 className="text-base sm:text-xl font-bold text-white truncate">{s.title.name}</h1>
          {s.title.runtime_minutes && <span className="text-xs text-muted">{formatRuntime(s.title.runtime_minutes)}</span>}
        </div>

        {s.next_episode_id && (
          <label className="flex items-center gap-2 text-xs sm:text-sm text-muted cursor-pointer select-none">
            <input type="checkbox" className="accent-brand rounded" checked={autoplay} onChange={(e) => toggleAutoplay(e.target.checked)} />
            Autoplay next episode
          </label>
        )}
      </div>

      {ended && (
        <div role="status" className="card flex flex-wrap items-center justify-between gap-3 p-4 rounded-xl border border-line/80">
          <span className="text-sm text-white font-medium">{s.next_episode_id ? 'Episode finished.' : 'You have finished watching.'}</span>
          <span className="flex gap-2">
            {s.next_episode_id && <button className="btn btn-primary text-xs sm:text-sm" onClick={() => go(s.next_episode_id)}>Play next episode</button>}
            <Link to={`/title/${id}`} className="btn btn-ghost text-xs sm:text-sm">Back to title</Link>
          </span>
        </div>
      )}
    </div>
  )
}
