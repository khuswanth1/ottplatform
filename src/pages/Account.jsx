import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Badge, ErrorBox, Field, Notice, PageTitle, Spinner, setDocTitle } from '../components/ui'
import { formatDate, formatMoney } from '../lib/money'
import { activeAgo } from '../lib/utils'
import Avatar from '../components/Avatar'

const LIVE = ['active', 'trialing', 'past_due']
const MAX_POLLS = 8

const WAIT_TRIES = 8

// Change plan, cancel and resume. Stripe does the work and tells us by webhook, so after a request we look again
// every 2 s for a short while instead of pretending the change already happened.
export function ManagePlan({ sub }) {
  const qc = useQueryClient()
  const plans = useQuery({ queryKey: ['plans'], queryFn: () => api('/billing/plans'), staleTime: 5 * 60_000 })
  const [expect, setExpect] = useState(null) // { plan } or { cancel }
  const [tries, setTries] = useState(0)
  const [late, setLate] = useState(false)
  const start = (e) => { setExpect(e); setTries(0); setLate(false) }
  const change = useMutation({ mutationFn: (code) => api('/billing/change-plan', { method: 'POST', body: { plan_code: code } }), onSuccess: (_, code) => start({ plan: code }) })
  const cancel = useMutation({ mutationFn: () => api('/billing/cancel', { method: 'POST' }), onSuccess: () => start({ cancel: true }) })
  const resume = useMutation({ mutationFn: () => api('/billing/resume', { method: 'POST' }), onSuccess: () => start({ cancel: false }) })
  useEffect(() => {
    if (!expect) return undefined
    const met = expect.plan ? sub.plan_code === expect.plan : sub.cancel_at_period_end === expect.cancel
    if (met) { setExpect(null); return undefined }
    if (tries >= WAIT_TRIES) { setExpect(null); setLate(true); return undefined }
    const t = setTimeout(() => { qc.invalidateQueries({ queryKey: ['subscription'] }); setTries((n) => n + 1) }, 2000)
    return () => clearTimeout(t)
  }, [expect, tries, sub, qc])

  const busy = change.isPending || cancel.isPending || resume.isPending || !!expect
  const others = (plans.data?.plans ?? []).filter((p) => p.code !== 'free' && p.code !== sub.plan_code && p.purchasable)
  const end = formatDate(sub.current_period_end)
  return (
    <div className="space-y-3 border-t border-line pt-4">
      <ErrorBox error={change.error || cancel.error || resume.error} />
      {expect && <Notice tone="info">Waiting for the payment provider to confirm. This usually takes a few seconds.</Notice>}
      {late && <Notice>We have not heard back yet. Your change may still be going through; check again in a minute.</Notice>}
      {others.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold">Change plan</h3>
          <ul className="space-y-2">
            {others.map((p) => {
              const price = p.price ? formatMoney(p.price.amount_cents, p.price.currency) : ''
              return (
                <li key={p.code} className="flex flex-wrap items-center gap-3 rounded-lg border border-line p-3">
                  <div className="min-w-0 flex-1 basis-40">
                    <div className="font-medium">{p.name}</div>
                    <div className="text-xs text-muted">{price} / month · {p.max_streams === 1 ? '1 screen' : `${p.max_streams} screens`}</div>
                  </div>
                  <button className="btn btn-ghost" disabled={busy} aria-label={`Switch to ${p.name}`}
                    onClick={() => confirm(`Switch to ${p.name} at ${price} a month? You are charged or credited the difference for the rest of this period right away.`) && change.mutate(p.code)}>
                    Switch
                  </button>
                </li>
              )
            })}
          </ul>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {sub.cancel_at_period_end
          ? <button className="btn btn-primary" disabled={busy} onClick={() => resume.mutate()}>Keep my membership</button>
          : <button className="btn btn-ghost" disabled={busy}
              onClick={() => confirm(`Cancel your membership? You keep your plan until ${end}, then you are on the free plan.`) && cancel.mutate()}>Cancel membership</button>}
      </div>
    </div>
  )
}

const INVOICE_TONE = { paid: 'free', open: 'premium', uncollectible: 'premium' }

// Recent invoices, read from the payment provider each time (nothing is stored here).
export function Invoices() {
  const q = useQuery({ queryKey: ['invoices'], queryFn: () => api('/billing/invoices'), staleTime: 60_000 })
  return (
    <section className="card space-y-3 p-5" aria-labelledby="invoices-h">
      <h2 id="invoices-h" className="text-lg font-semibold">Invoices</h2>
      {q.isLoading && <div className="space-y-2" aria-hidden>{[0, 1].map((i) => <div key={i} className="skeleton h-12" />)}</div>}
      <ErrorBox error={q.error} onRetry={q.refetch} />
      {q.data && !q.data.length && <p className="text-sm text-muted">No invoices yet.</p>}
      <ul className="space-y-2">
        {q.data?.map((i) => (
          <li key={i.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line p-3 text-sm">
            <div className="min-w-0 flex-1 basis-40">
              <div className="font-medium">{formatMoney(i.total_cents, i.currency)}</div>
              <div className="text-xs text-muted">{formatDate(i.created)}{i.number ? ` · ${i.number}` : ''}</div>
            </div>
            <Badge tone={INVOICE_TONE[i.status] || 'neutral'}>{i.status}</Badge>
            {i.url && <a className="btn btn-ghost" href={i.url} target="_blank" rel="noopener noreferrer">View<span className="sr-only"> invoice {i.number || i.id} (opens in a new tab)</span> <span aria-hidden>↗</span></a>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function Membership() {
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const returning = params.get('checkout') === 'success'
  const polls = useRef(0)
  const q = useQuery({
    queryKey: ['subscription'],
    queryFn: () => api('/billing/subscription'),
    // The redirect from checkout can arrive before the payment webhook; look again a few times instead of trusting the URL.
    refetchInterval: (query) => (returning && !LIVE.includes(query.state.data?.status) && ++polls.current < MAX_POLLS ? 2000 : false),
  })
  const portal = useMutation({
    mutationFn: () => api('/billing/portal', { method: 'POST' }),
    onSuccess: (r) => window.location.assign(r.url),
  })
  useEffect(() => { if (q.data && LIVE.includes(q.data.status)) qc.invalidateQueries({ queryKey: ['me'] }) }, [q.data, qc])

  if (q.isLoading) return <Spinner label="Loading membership" />
  if (q.isError) return <ErrorBox error={q.error} onRetry={q.refetch} />
  const s = q.data
  const live = LIVE.includes(s.status)
  const waiting = returning && !live && polls.current < MAX_POLLS

  return (
    <section className="card space-y-4 p-5" aria-labelledby="membership-h">
      <div className="flex flex-wrap items-center gap-3">
        <h2 id="membership-h" className="text-lg font-semibold">Membership</h2>
        <Badge tone={live ? 'free' : 'neutral'}>{s.plan_name}</Badge>
        {s.status === 'past_due' && <Badge tone="premium">Payment needed</Badge>}
      </div>
      {waiting && <Notice tone="info">Confirming your payment. This usually takes a few seconds.</Notice>}
      {returning && !live && !waiting && (
        <Notice>We have not received confirmation of your payment yet. If you were charged, it will show up here shortly; otherwise contact support.</Notice>
      )}
      {s.status === 'past_due' && <Notice>Your last payment did not go through. Update your payment method to keep your plan.</Notice>}
      {live && (
        <p className="text-sm text-muted">
          {s.cancel_at_period_end
            ? <>Your plan ends on <b className="text-text">{formatDate(s.current_period_end)}</b> and will not renew.</>
            : <>Renews on <b className="text-text">{formatDate(s.current_period_end)}</b>.</>}
        </p>
      )}
      {!live && !waiting && s.status === 'cancelled' && <p className="text-sm text-muted">Your plan has ended. You are on the free plan.</p>}
      {!live && !waiting && s.status === 'none' && <p className="text-sm text-muted">You are on the free plan.</p>}
      <ErrorBox error={portal.error} />
      <div className="flex flex-wrap gap-2">
        {s.can_manage && <button className="btn btn-primary" disabled={portal.isPending} onClick={() => portal.mutate()}>{portal.isPending ? 'Opening…' : 'Manage billing'}</button>}
        {!live && <Link to="/plans" className={`btn ${s.can_manage ? 'btn-ghost' : 'btn-primary'}`}>See plans</Link>}
      </div>
      {live && s.can_manage && <ManagePlan sub={s} />}
      {returning && live && <button className="text-xs text-muted underline" onClick={() => setParams({}, { replace: true })}>Dismiss</button>}
    </section>
  )
}

// Every browser or device signed in to this account. Sign one out, or all but this one.
function BillingHistory() {
  const sub = useQuery({ queryKey: ['subscription'], queryFn: () => api('/billing/subscription') })
  return sub.data?.can_manage ? <Invoices /> : null
}

export function Devices() {
  const qc = useQueryClient()
  const [notice, setNotice] = useState('')
  const q = useQuery({ queryKey: ['devices'], queryFn: () => api('/account/devices'), staleTime: 30_000 })
  const done = (msg) => { setNotice(msg); qc.invalidateQueries({ queryKey: ['devices'] }) }
  const one = useMutation({ mutationFn: (d) => api(`/account/devices/${d.id}`, { method: 'DELETE' }), onSuccess: (_, d) => done(`Signed out ${d.label}.`) })
  const others = useMutation({ mutationFn: () => api('/account/sign-out-others', { method: 'POST' }), onSuccess: (r) => done(r.message) })
  const rows = q.data ?? []
  const busy = one.isPending || others.isPending
  return (
    <section className="card space-y-3 p-5" aria-labelledby="devices-h">
      <h2 id="devices-h" className="text-lg font-semibold">Devices</h2>
      <p className="text-sm text-muted">Where you are signed in right now. If you do not recognise one, sign it out and change your password.</p>
      {q.isLoading && <div className="space-y-2" aria-hidden>{[0, 1].map((i) => <div key={i} className="skeleton h-14" />)}</div>}
      <ErrorBox error={q.error || one.error || others.error} onRetry={q.error ? q.refetch : undefined} />
      <p role="status" className="sr-only">{notice}</p>
      {notice && <p className="text-sm text-muted" aria-hidden>{notice}</p>}
      <ul className="space-y-2">
        {rows.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line p-3">
            <div className="min-w-0 flex-1 basis-48">
              <div className="flex flex-wrap items-center gap-2 font-medium">{d.label}{d.current && <Badge tone="free">This device</Badge>}</div>
              <div className="text-xs text-muted">{activeAgo(d.last_seen_at)}{d.ip ? ` · ${d.ip}` : ''}</div>
            </div>
            {!d.current && <button className="btn btn-ghost" disabled={busy} aria-label={`Sign out ${d.label}`} onClick={() => one.mutate(d)}>Sign out</button>}
          </li>
        ))}
      </ul>
      {rows.length > 1 && (
        <button className="btn btn-ghost" disabled={busy} onClick={() => confirm('Sign out of every other device? They will need to sign in again.') && others.mutate()}>
          Sign out of all other devices
        </button>
      )}
    </section>
  )
}

export function AccountProfiles() {
  const q = useQuery({ queryKey: ['profiles'], queryFn: () => api('/profiles') })
  return (
    <section className="card space-y-3 p-5" aria-labelledby="profiles-h">
      <div className="flex items-center justify-between gap-3">
        <h2 id="profiles-h" className="text-lg font-semibold">Profiles</h2>
        <Link to="/profiles" className="btn btn-ghost !py-1 text-sm">Manage profiles</Link>
      </div>
      {q.isLoading && <Spinner />}
      <ErrorBox error={q.error} onRetry={q.refetch} />
      <ul className="space-y-2">
        {q.data?.map((p) => (
          <li key={p.id} className="flex items-center gap-3 text-sm">
            <Avatar name={p.name} avatar={p.avatar} size="h-9 w-9 text-sm" />
            <span className="min-w-0 flex-1 truncate font-medium">{p.name}</span>
            {p.is_kids && <Badge>Kids</Badge>}
            {p.has_pin && <Badge>PIN</Badge>}
          </li>
        ))}
      </ul>
    </section>
  )
}

export function ChangePassword() {
  const [f, setF] = useState({ current: '', next: '', again: '' })
  const mismatch = f.again !== '' && f.next !== f.again
  const change = useMutation({
    mutationFn: () => api('/account/change-password', { method: 'POST', body: { current_password: f.current, new_password: f.next } }),
    onSuccess: () => setF({ current: '', next: '', again: '' }),
  })
  const ready = f.current && f.next.length >= 10 && f.next === f.again
  return (
    <section className="card space-y-3 p-5" aria-labelledby="password-h">
      <h2 id="password-h" className="text-lg font-semibold">Password</h2>
      <p className="text-sm text-muted">Changing it signs you out of every other device. This one stays signed in.</p>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (ready) change.mutate() }}>
        <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={f.current} onChange={(e) => { change.reset(); setF({ ...f, current: e.target.value }) }} /></Field>
        <Field label="New password" hint="At least 10 characters"><input className="input" type="password" autoComplete="new-password" value={f.next} onChange={(e) => { change.reset(); setF({ ...f, next: e.target.value }) }} /></Field>
        <Field label="New password again"><input className="input" type="password" autoComplete="new-password" aria-invalid={mismatch} value={f.again} onChange={(e) => { change.reset(); setF({ ...f, again: e.target.value }) }} /></Field>
        {mismatch && <p role="alert" className="text-xs text-warn">The two new passwords are different.</p>}
        <ErrorBox error={change.error} />
        {change.isSuccess && <p role="status" className="text-sm text-success">Password updated. Your other devices were signed out.</p>}
        <button className="btn btn-primary" disabled={!ready || change.isPending}>{change.isPending ? 'Saving…' : 'Change password'}</button>
      </form>
    </section>
  )
}

export function DeleteAccount() {
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const del = useMutation({
    mutationFn: () => api('/account/delete', { method: 'POST', body: { password } }),
    onSuccess: () => { window.location.assign('/') }, // a full reload drops every cached bit of the old session
  })
  return (
    <section className="card space-y-3 border-danger/40 p-5" aria-labelledby="delete-h">
      <h2 id="delete-h" className="text-lg font-semibold">Delete account</h2>
      <p className="text-sm text-muted">Removes your profiles, lists, history, ratings and sign-ins for good. A paid plan is ended first. This cannot be undone.</p>
      {!open && <button type="button" className="btn btn-ghost text-danger" onClick={() => setOpen(true)}>Delete my account…</button>}
      {open && (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); if (password && confirm('Delete your account permanently? This cannot be undone.')) del.mutate() }}>
          <Field label="Your password, to confirm"><input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <ErrorBox error={del.error} />
          <div className="flex gap-2">
            <button className="btn btn-ghost text-danger" disabled={!password || del.isPending}>{del.isPending ? 'Deleting…' : 'Delete permanently'}</button>
            <button type="button" className="btn btn-ghost" onClick={() => { setOpen(false); setPassword(''); del.reset() }}>Keep my account</button>
          </div>
        </form>
      )}
    </section>
  )
}

export default function Account() {
  const { user } = useAuth()
  useEffect(() => setDocTitle('Account'), [])
  return (
    <div className="mx-auto max-w-2xl space-y-6 px-4 py-10 sm:px-8">
      <PageTitle sub="Your plan, billing and sign-in details.">Account</PageTitle>
      <section className="card p-5" aria-labelledby="signin-h">
        <h2 id="signin-h" className="mb-2 text-lg font-semibold">Sign-in</h2>
        <p className="break-all text-sm text-muted">{user?.email}</p>
      </section>
      <AccountProfiles />
      <Membership />
      <BillingHistory />
      <ChangePassword />
      <Devices />
      <DeleteAccount />
    </div>
  )
}
