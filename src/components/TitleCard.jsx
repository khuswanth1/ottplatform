import { memo, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { CheckIcon, PlayIcon, PlusIcon } from './icons'
import { Badge } from './ui'
import { formatRuntime } from '../lib/utils'

function AccessBadge({ direct }) {
  if (!direct) return null
  return direct.entitlement === 'premium' ? (
    <Badge tone="premium" className="text-[10px] sm:text-xs">Premium</Badge>
  ) : (
    <Badge tone="free" className="text-[10px] sm:text-xs">Free here</Badge>
  )
}

const HOVER_DELAY_MS = 600
const CLOSE_GRACE_MS = 120
const canHover = () => typeof window !== 'undefined' && window.matchMedia?.('(hover: hover) and (pointer: fine)').matches
let closeActive = null

function MyListToggle({ id }) {
  const { user, profileId } = useAuth()
  const qc = useQueryClient()
  const ids = useQuery({ queryKey: ['watchlist-ids', profileId], queryFn: () => api('/watchlist/ids'), enabled: !!user && !!profileId })
  const on = !!ids.data?.watchlist?.includes(id)
  const toggle = useMutation({
    mutationFn: () =>
      api(`/watchlist/${id}`, {
        method: on ? 'DELETE' : 'PUT',
        params: on ? { kind: 'watchlist' } : undefined,
        body: on ? undefined : { kind: 'watchlist' },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['watchlist-ids'] })
      qc.invalidateQueries({ queryKey: ['mylist'] })
      qc.invalidateQueries({ queryKey: ['recs'] })
    },
  })
  if (!user) return null
  return (
    <button
      type="button"
      className="btn btn-ghost !px-2.5 !py-1 text-xs"
      aria-pressed={on}
      aria-label={on ? 'Remove from my list' : 'Add to my list'}
      disabled={toggle.isPending}
      onClick={() => toggle.mutate()}
    >
      {on ? <CheckIcon size={14} /> : <PlusIcon size={14} />}
    </button>
  )
}

function Preview({ title, rect, onEnter, onLeave }) {
  const { user } = useAuth()
  const width = Math.max(rect.width * 1.6, 260)
  const left = Math.min(Math.max(8, rect.left + rect.width / 2 - width / 2), window.innerWidth - width - 8)
  const top = Math.max(8, rect.top - 20)
  const meta = [
    title.year,
    title.age_rating,
    title.runtime_minutes && formatRuntime(title.runtime_minutes),
    title.type === 'series' ? 'Series' : 'Movie',
  ].filter(Boolean)
  const art = title.backdrop_url || title.poster_url
  const canPlay = !!title.direct && title.type === 'movie' && !!user

  return createPortal(
    <div
      role="dialog"
      data-hover-preview
      aria-label={`${title.name} preview`}
      style={{ position: 'fixed', left, top, width }}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      className="z-[60] overflow-hidden rounded-xl border border-line bg-surface shadow-2xl motion-safe:animate-[fadein_.15s_ease-out]"
    >
      <Link
        to={`/title/${title.id}`}
        className="block relative aspect-video bg-raised group/preview-art cursor-pointer"
        aria-label={`View details for ${title.name}`}
      >
        {art && (
          <img
            src={art}
            alt=""
            className="h-full w-full object-cover transition-transform duration-300 group-hover/preview-art:scale-105"
          />
        )}
        <div className="absolute inset-0 bg-black/20 opacity-0 group-hover/preview-art:opacity-100 transition-opacity" />
        <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-surface to-transparent" />
      </Link>
      <div className="space-y-2 p-3.5">
        <div className="flex items-center gap-2">
          {canPlay && (
            <Link to={`/watch/${title.id}`} className="btn btn-primary !px-3 !py-1 text-xs" aria-label={`Play ${title.name}`}>
              <PlayIcon size={14} fill /> Play
            </Link>
          )}
          <MyListToggle id={title.id} />
          <Link to={`/title/${title.id}`} className="btn btn-ghost !px-3 !py-1 text-xs ml-auto">
            Details
          </Link>
        </div>
        <Link
          to={`/title/${title.id}`}
          className="block truncate font-semibold text-sm text-white hover:text-brand transition-colors"
        >
          {title.name}
        </Link>
        <div className="flex flex-wrap items-center gap-x-2 text-xs text-muted">
          {meta.map((m, i) => (
            <span key={i}>{m}</span>
          ))}
          <AccessBadge direct={title.direct} />
        </div>
        {title.genres?.length > 0 && (
          <div className="truncate text-xs text-text-muted">{title.genres.slice(0, 3).join(' • ')}</div>
        )}
      </div>
    </div>,
    document.body,
  )
}

function useHoverPreview() {
  const ref = useRef(null)
  const [rect, setRect] = useState(null)
  const openTimer = useRef(0)
  const closeTimer = useRef(0)
  const close = useCallback(() => {
    clearTimeout(openTimer.current)
    clearTimeout(closeTimer.current)
    setRect(null)
  }, [])
  const scheduleClose = useCallback(() => {
    clearTimeout(openTimer.current)
    clearTimeout(closeTimer.current)
    closeTimer.current = setTimeout(close, CLOSE_GRACE_MS)
  }, [close])
  const leaveCard = useCallback(
    (e) => {
      if (e.relatedTarget?.closest?.('[data-hover-preview]')) return
      scheduleClose()
    },
    [scheduleClose],
  )
  const leavePanel = useCallback(
    (e) => {
      if (ref.current && ref.current.contains(e.relatedTarget)) return
      scheduleClose()
    },
    [scheduleClose],
  )
  const keepOpen = useCallback(() => clearTimeout(closeTimer.current), [])
  const onEnter = useCallback(() => {
    if (!canHover()) return
    clearTimeout(closeTimer.current)
    clearTimeout(openTimer.current)
    openTimer.current = setTimeout(() => {
      if (!ref.current) return
      closeActive?.()
      closeActive = close
      setRect(ref.current.getBoundingClientRect())
    }, HOVER_DELAY_MS)
  }, [close])

  useEffect(() => {
    if (!rect) return
    const esc = (e) => e.key === 'Escape' && close()
    window.addEventListener('keydown', esc)
    window.addEventListener('scroll', close, { passive: true, capture: true })
    return () => {
      window.removeEventListener('keydown', esc)
      window.removeEventListener('scroll', close, { capture: true })
      if (closeActive === close) closeActive = null
    }
  }, [rect, close])

  useEffect(() => close, [close])
  return { ref, rect, onEnter, leaveCard, leavePanel, keepOpen }
}

export default memo(function TitleCard({ title, className = '', rank }) {
  const { ref, rect, onEnter, leaveCard, leavePanel, keepOpen } = useHoverPreview()
  return (
    <>
      <Link
        ref={ref}
        to={`/title/${title.id}`}
        className={`tile group relative block shrink-0 ${className}`}
        onMouseEnter={onEnter}
        onMouseLeave={leaveCard}
      >
        <div className="relative aspect-[2/3] overflow-hidden rounded-lg bg-surface border border-line/60 shadow-md transition-shadow group-hover:shadow-xl">
          {title.poster_url ? (
            <img
              src={title.poster_url}
              alt=""
              loading="lazy"
              decoding="async"
              className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            />
          ) : (
            <div className="flex h-full items-center justify-center p-3 text-center text-xs text-muted">
              {title.name}
            </div>
          )}
          <div className="absolute left-1.5 top-1.5 flex flex-col gap-1">
            <AccessBadge direct={title.direct} />
          </div>
        </div>
        <div className="mt-1.5 px-0.5 space-y-0.5">
          {rank && <span className="sr-only">Number {rank}: </span>}
          <div className="truncate text-xs sm:text-sm font-semibold text-text group-hover:text-white transition-colors">
            {title.name}
          </div>
          <div className="text-[11px] sm:text-xs text-muted">
            {[title.year, title.type === 'series' ? 'Series' : 'Movie', title.original_language?.toUpperCase()]
              .filter(Boolean)
              .join(' • ')}
          </div>
        </div>
      </Link>
      {rect && <Preview title={title} rect={rect} onEnter={keepOpen} onLeave={leavePanel} />}
    </>
  )
})
