import { useEffect, useState } from 'react'

export function Spinner({ label = 'Loading' }) {
  return (
    <div role="status" aria-label={label} className="flex justify-center py-20">
      <div className="h-8 w-8 rounded-full border-2 border-line border-t-brand animate-spin" />
    </div>
  )
}

export function ErrorBox({ error, onRetry, className = '' }) {
  if (!error) return null
  return (
    <div role="alert" className={`card border-brand/40 p-4 text-sm flex items-center justify-between gap-4 ${className}`}>
      <span>{error.message || String(error)}</span>
      {onRetry && <button className="btn btn-ghost" onClick={onRetry}>Retry</button>}
    </div>
  )
}

export function Notice({ children, tone = 'warn' }) {
  const color = tone === 'warn' ? 'border-warn/40 text-warn' : tone === 'info' ? 'border-line text-muted' : 'border-ok/40 text-ok'
  return <div role="status" className={`rounded-lg border ${color} bg-surface px-4 py-2 text-sm`}>{children}</div>
}

const BADGE = {
  free: 'bg-ok/15 text-ok border-ok/40',
  premium: 'bg-warn/15 text-warn border-warn/40',
  neutral: 'bg-raised text-muted border-line',
  kids: 'bg-sky-500/15 text-sky-300 border-sky-500/40',
}
export function Badge({ tone = 'neutral', children }) {
  return <span className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-semibold leading-none ${BADGE[tone]}`}>{children}</span>
}

export function Field({ label, children, hint }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  )
}

export function useDebounced(value, ms = 350) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function PageTitle({ children, sub }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl sm:text-3xl font-bold">{children}</h1>
      {sub && <p className="mt-1 text-muted text-sm">{sub}</p>}
    </div>
  )
}

export function setDocTitle(t) { document.title = t ? `${t} — CineVerse` : 'CineVerse' }
