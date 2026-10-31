import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { BellIcon } from './icons'
import { describeNotification } from '../lib/utils'

// Bell with an unread count. Polls once a minute (only while the tab is visible) and opens a short list.
export default function NotificationBell() {
  const { user, profileId } = useAuth()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [alignLeft, setAlignLeft] = useState(false)
  const box = useRef(null)
  const q = useQuery({ queryKey: ['notifications', profileId], queryFn: () => api('/notifications'), enabled: !!user && !!profileId, refetchInterval: 60_000, staleTime: 30_000 })
  const read = useMutation({
    mutationFn: (body) => api('/notifications/read', { method: 'POST', body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  useEffect(() => {
    if (!open) return
    const away = (e) => { if (box.current && !box.current.contains(e.target)) setOpen(false) }
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', away); document.removeEventListener('keydown', esc) }
  }, [open])
  if (!user || !profileId) return null
  const unread = q.data?.unread ?? 0
  const items = q.data?.items ?? []
  return (
    <div className="relative" ref={box}>
      <button type="button" className="btn btn-ghost relative !px-2 !py-1.5" aria-haspopup="true" aria-expanded={open}
        aria-label={unread ? `Notifications, ${unread} unread` : 'Notifications'} onClick={() => {
          // the header wraps, so the bell can sit at the left edge: open the list toward the free side
          if (!open && box.current) setAlignLeft(box.current.getBoundingClientRect().right < Math.min(352, window.innerWidth * 0.92))
          setOpen((o) => !o)
        }}>
        <BellIcon size={20} />
        {unread > 0 && <span aria-hidden className="absolute -right-1 -top-1 grid min-w-[18px] place-items-center rounded-full bg-brand px-1 text-[11px] font-bold leading-[18px] text-on-accent">{unread > 9 ? '9+' : unread}</span>}
      </button>
      {open && (
        <div className={`absolute z-50 mt-2 w-[min(92vw,22rem)] card p-2 text-sm shadow-xl ${alignLeft ? 'left-0' : 'right-0'}`} aria-label="Notifications">
          <div className="flex items-center justify-between px-2 pb-1">
            <span className="font-semibold">Notifications</span>
            {unread > 0 && <button type="button" className="text-xs underline text-muted" disabled={read.isPending} onClick={() => read.mutate({ all: true })}>Mark all as read</button>}
          </div>
          {q.isError && <p className="px-2 py-3 text-warn">Could not load notifications.</p>}
          {!q.isError && !items.length && <p className="px-2 py-3 text-muted">Nothing yet. Use “Remind me” on a coming-soon title and you will hear here when it is out.</p>}
          <ul className="max-h-96 space-y-1 overflow-y-auto">
            {items.map((n) => (
              <li key={n.id}>
                <Link to={`/title/${n.title.id}`} onClick={() => { setOpen(false); if (!n.read_at) read.mutate({ ids: [n.id] }) }}
                  className={`flex items-center gap-3 rounded p-2 hover:bg-raised ${n.read_at ? '' : 'bg-raised/60'}`}>
                  {n.title.poster_url ? <img src={n.title.poster_url} alt="" className="h-14 w-10 shrink-0 rounded object-cover" /> : <span className="h-14 w-10 shrink-0 rounded bg-surface" aria-hidden />}
                  <span className="min-w-0 flex-1">
                    <span className="block break-words font-medium">{describeNotification(n).headline}</span>
                    <span className="block text-xs text-muted">{describeNotification(n).detail}{n.read_at ? '' : ' · unread'}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
