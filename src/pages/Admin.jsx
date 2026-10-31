import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { Badge, ErrorBox, Field, Notice, PageTitle, Spinner, setDocTitle, useDebounced } from '../components/ui'
import { parseTime } from '../lib/utils'
import { REPORT_KINDS } from '../components/ReportProblem'

const TABS = [['titles', 'Titles'], ['rights', 'Rights review'], ['featured', 'Home billboard'], ['archive', 'Internet Archive'], ['reports', 'Playback reports'], ['audit', 'Audit log']]
const LICENSES = ['public_domain', 'creative_commons', 'owned', 'licensed', 'unknown']

function useAdminMutation(fn, invalidate) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => invalidate.forEach((k) => qc.invalidateQueries({ queryKey: [k] })) })
}

/* ---------------- rights + assets for one title ---------------- */
function RightsPanel({ titleId }) {
  const q = useQuery({ queryKey: ['a-rights', titleId], queryFn: () => api('/admin/title-rights', { params: { title_id: titleId } }) })
  const [f, setF] = useState({ license_type: 'public_domain', territories: '*', entitlement: 'registered', evidence_url: '', expires_at: '', notes: '' })
  const add = useAdminMutation(() => api('/admin/title-rights', { method: 'POST', body: {
    title_id: titleId, license_type: f.license_type, entitlement: f.entitlement, evidence_url: f.evidence_url || null, notes: f.notes || null,
    territories: f.territories.split(',').map((s) => s.trim()).filter(Boolean), expires_at: f.expires_at ? new Date(f.expires_at).toISOString() : null } }), ['a-rights'])
  const act = useAdminMutation(({ id, verify, status }) => (verify ? api(`/admin/title-rights/${id}/verify`, { method: 'POST' }) : api(`/admin/title-rights/${id}`, { method: 'PATCH', body: { status } })), ['a-rights', 'a-review'])
  return (
    <div className="card space-y-3 p-4">
      <h2 className="font-semibold">Content rights</h2>
      <p className="text-xs text-muted">Only <b>verified</b> rights inside their date window and territories allow playback. New rights always start unverified.</p>
      {q.isLoading ? <Spinner /> : q.data?.map((r) => (
        <div key={r.id} className="flex flex-wrap items-center gap-2 rounded border border-line p-2 text-sm">
          <Badge tone={r.status === 'verified' ? 'free' : 'neutral'}>{r.status}</Badge>
          <span>{r.license_type}</span><span className="text-muted">{r.territories.join(', ')}</span>
          {r.entitlement === 'premium' && <Badge tone="premium">premium</Badge>}
          {r.expires_at && <span className="text-xs text-muted">expires {new Date(r.expires_at).toLocaleDateString()}</span>}
          {r.evidence_url && <a className="text-xs underline" href={r.evidence_url} target="_blank" rel="noopener noreferrer">evidence</a>}
          <span className="ml-auto flex gap-1">
            {r.status !== 'verified' && <button className="btn btn-primary !py-1" disabled={act.isPending} onClick={() => act.mutate({ id: r.id, verify: true })}>Verify</button>}
            {r.status === 'verified' && <button className="btn btn-ghost !py-1" disabled={act.isPending} onClick={() => act.mutate({ id: r.id, status: 'revoked' })}>Revoke</button>}
          </span>
        </div>
      ))}
      <ErrorBox error={act.error} />
      <form className="grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
        <Field label="License"><select className="input" value={f.license_type} onChange={(e) => setF({ ...f, license_type: e.target.value })}>{LICENSES.map((l) => <option key={l}>{l}</option>)}</select></Field>
        <Field label="Territories" hint="* for worldwide or ISO codes: US, IN"><input className="input" value={f.territories} onChange={(e) => setF({ ...f, territories: e.target.value })} /></Field>
        <Field label="Who can watch"><select className="input" value={f.entitlement} onChange={(e) => setF({ ...f, entitlement: e.target.value })}><option value="registered">Any signed-in user</option><option value="premium">Premium plan</option></select></Field>
        <Field label="License expiry (optional)"><input className="input" type="date" value={f.expires_at} onChange={(e) => setF({ ...f, expires_at: e.target.value })} /></Field>
        <div className="sm:col-span-2"><Field label="Evidence URL (license page, contract reference)"><input className="input" type="url" value={f.evidence_url} onChange={(e) => setF({ ...f, evidence_url: e.target.value })} /></Field></div>
        <div className="sm:col-span-2 flex items-center gap-2"><button className="btn btn-ghost" disabled={add.isPending}>Add right</button><ErrorBox error={add.error} className="flex-1" /></div>
      </form>
    </div>
  )
}

function AssetsPanel({ titleId, isSeries }) {
  const q = useQuery({ queryKey: ['a-assets', titleId], queryFn: () => api('/admin/media-assets', { params: { title_id: titleId } }) })
  const [f, setF] = useState({ kind: 'hls', url: '', episode_id: '', requires_signing: false, subtitle: '' })
  const add = useAdminMutation(() => api('/admin/media-assets', { method: 'POST', body: {
    title_id: titleId, kind: f.kind, url: f.url, episode_id: f.episode_id || null, requires_signing: f.requires_signing,
    subtitles: f.subtitle ? [{ lang: 'en', label: 'English', url: f.subtitle }] : [] } }), ['a-assets'])
  const upd = useAdminMutation(({ id, body, del }) => (del ? api(`/admin/media-assets/${id}`, { method: 'DELETE' }) : api(`/admin/media-assets/${id}`, { method: 'PATCH', body })), ['a-assets'])
  return (
    <div className="card space-y-3 p-4">
      <h2 className="font-semibold">Media assets</h2>
      {q.data?.map((a) => (
        <div key={a.id} className="flex flex-wrap items-center gap-2 rounded border border-line p-2 text-sm">
          <Badge>{a.kind}</Badge><span className="min-w-0 flex-1 truncate" title={a.url}>{a.url}</span>
          {a.episode_id && <span className="text-xs text-muted">episode</span>}
          <button className="btn btn-ghost !py-1" onClick={() => upd.mutate({ id: a.id, body: { is_active: !a.is_active } })}>{a.is_active ? 'Disable' : 'Enable'}</button>
          <button className="btn btn-ghost !py-1 text-danger" onClick={() => confirm('Delete this asset?') && upd.mutate({ id: a.id, del: true })}>Delete</button>
        </div>
      ))}
      <ErrorBox error={upd.error} />
      <form className="grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); add.mutate() }}>
        <Field label="Type"><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{['hls', 'dash', 'mp4', 'embed'].map((k) => <option key={k}>{k}</option>)}</select></Field>
        {isSeries && <Field label="Episode ID"><input className="input" value={f.episode_id} onChange={(e) => setF({ ...f, episode_id: e.target.value })} placeholder="required for series" /></Field>}
        <div className="sm:col-span-2"><Field label="HTTPS URL" hint="Embed URLs must be on an approved host (EMBED_ALLOWED_HOSTS)."><input className="input" type="url" required value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} /></Field></div>
        <div className="sm:col-span-2"><Field label="English subtitle URL (.vtt, optional)"><input className="input" type="url" value={f.subtitle} onChange={(e) => setF({ ...f, subtitle: e.target.value })} /></Field></div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.requires_signing} onChange={(e) => setF({ ...f, requires_signing: e.target.checked })} /> Sign URLs for CDN</label>
        <div className="flex items-center gap-2 sm:col-span-2"><button className="btn btn-ghost" disabled={add.isPending}>Add asset</button><ErrorBox error={add.error} className="flex-1" /></div>
      </form>
    </div>
  )
}

/* ---------------- tabs ---------------- */
/* ---------------- skip intro / recap / credits markers ---------------- */
const MARKER_KINDS = [['intro', 'Intro'], ['recap', 'Recap'], ['credits', 'Credits']]
const clock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

function MarkersPanel({ titleId, isSeries }) {
  const q = useQuery({ queryKey: ['a-markers', titleId], queryFn: () => api('/admin/markers', { params: { title_id: titleId } }) })
  const [f, setF] = useState({ kind: 'intro', episode_id: '', start: '', end: '' })
  const start = parseTime(f.start)
  const end = parseTime(f.end)
  const valid = start !== null && end !== null && end > start && (!isSeries || f.episode_id.trim())
  const save = useAdminMutation(() => api('/admin/markers', { method: 'PUT', body: { title_id: titleId, kind: f.kind, episode_id: isSeries ? f.episode_id.trim() : null, start_s: start, end_s: end } }), ['a-markers'])
  const del = useAdminMutation((id) => api(`/admin/markers/${id}`, { method: 'DELETE' }), ['a-markers'])
  return (
    <div className="card space-y-3 p-4">
      <h2 className="font-semibold">Skip markers</h2>
      <p className="text-xs text-muted">The player offers “Skip intro”, “Skip recap” or “Next episode” inside these ranges. Times as seconds or m:ss.</p>
      {q.data?.length === 0 && <p className="text-sm text-muted">None yet.</p>}
      {q.data?.map((m) => (
        <div key={m.id} className="flex flex-wrap items-center gap-2 rounded border border-line p-2 text-sm">
          <Badge>{m.kind}</Badge><span className="tabular-nums">{clock(m.start_s)} – {clock(m.end_s)}</span>
          {m.episode_id && <span className="min-w-0 flex-1 truncate text-xs text-muted" title={m.episode_id}>episode {m.episode_id.slice(0, 8)}</span>}
          <button className="btn btn-ghost !py-1 ml-auto text-danger" disabled={del.isPending} aria-label={`Delete ${m.kind} marker`} onClick={() => del.mutate(m.id)}>Delete</button>
        </div>
      ))}
      <ErrorBox error={del.error} />
      <form className="grid gap-2 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); if (valid) save.mutate() }}>
        <Field label="Kind"><select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{MARKER_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="From"><input className="input" inputMode="numeric" placeholder="0:30" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></Field>
        <Field label="To"><input className="input" inputMode="numeric" placeholder="1:45" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></Field>
        {isSeries && <div className="sm:col-span-3"><Field label="Episode ID"><input className="input" value={f.episode_id} onChange={(e) => setF({ ...f, episode_id: e.target.value })} placeholder="required for series" /></Field></div>}
        <div className="flex items-center gap-2 sm:col-span-3">
          <button className="btn btn-ghost" disabled={!valid || save.isPending}>Save marker</button>
          {f.start && f.end && end !== null && start !== null && end <= start && <span className="text-xs text-warn">“To” must be after “From”.</span>}
          <ErrorBox error={save.error} className="flex-1" />
        </div>
      </form>
    </div>
  )
}

function Titles() {
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [sel, setSel] = useState(null)
  const dq = useDebounced(q)
  const list = useQuery({ queryKey: ['a-titles', dq, status], queryFn: () => api('/admin/titles', { params: { q: dq, status } }) })
  const setStatusM = useAdminMutation(({ id, status: s }) => api(`/admin/titles/${id}`, { method: 'PATCH', body: { status: s } }), ['a-titles'])
  const [nt, setNt] = useState({ type: 'movie', name: '', status: 'draft' })
  const create = useAdminMutation(() => api('/admin/titles', { method: 'POST', body: nt }), ['a-titles'])
  const [imp, setImp] = useState({ provider: 'tmdb', external_id: '', type: 'movie' })
  const doImport = useAdminMutation(() => api('/admin/titles/import', { method: 'POST', body: imp }), ['a-titles'])
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_1fr]">
      <div className="space-y-4">
        <div className="flex gap-2"><input className="input" placeholder="Search titles…" value={q} onChange={(e) => setQ(e.target.value)} />
          <select className="input !w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">All</option>{['draft', 'published', 'archived'].map((s) => <option key={s}>{s}</option>)}</select></div>
        {list.isLoading ? <Spinner /> : (
          <ul className="space-y-2">
            {list.data?.items.map((t) => (
              <li key={t.id} className={`card flex items-center gap-2 p-2 text-sm ${sel?.id === t.id ? 'border-brand' : ''}`}>
                <button className="min-w-0 flex-1 truncate text-left font-medium hover:underline" onClick={() => setSel(t)}>{t.name} <span className="text-xs text-muted">{t.year} · {t.type} · {t.source}</span></button>
                <select aria-label={`Status of ${t.name}`} className="input !w-auto !py-1" value={t.status} onChange={(e) => setStatusM.mutate({ id: t.id, status: e.target.value })}>{['draft', 'published', 'archived'].map((s) => <option key={s}>{s}</option>)}</select>
              </li>
            ))}
          </ul>
        )}
        <ErrorBox error={list.error || setStatusM.error} />
        <div className="card space-y-2 p-4">
          <h2 className="font-semibold">Create title</h2>
          <div className="flex gap-2"><select aria-label="Type" className="input !w-auto" value={nt.type} onChange={(e) => setNt({ ...nt, type: e.target.value })}><option>movie</option><option>series</option></select>
            <input className="input" placeholder="Name" value={nt.name} onChange={(e) => setNt({ ...nt, name: e.target.value })} /></div>
          <button className="btn btn-ghost" disabled={!nt.name || create.isPending} onClick={() => create.mutate()}>Create draft</button><ErrorBox error={create.error} />
        </div>
        <div className="card space-y-2 p-4">
          <h2 className="font-semibold">Import from provider</h2>
          <div className="flex flex-wrap gap-2">
            <select aria-label="Provider" className="input !w-auto" value={imp.provider} onChange={(e) => setImp({ ...imp, provider: e.target.value })}><option value="tmdb">TMDB id</option><option value="archive">Archive identifier</option></select>
            {imp.provider === 'tmdb' && <select aria-label="Kind" className="input !w-auto" value={imp.type} onChange={(e) => setImp({ ...imp, type: e.target.value })}><option>movie</option><option>series</option></select>}
            <input className="input flex-1" placeholder="External id" value={imp.external_id} onChange={(e) => setImp({ ...imp, external_id: e.target.value })} />
          </div>
          <button className="btn btn-ghost" disabled={!imp.external_id || doImport.isPending} onClick={() => doImport.mutate()}>Import</button><ErrorBox error={doImport.error} />
          {doImport.isSuccess && <Notice tone="ok">Imported ({doImport.data.status}).</Notice>}
        </div>
      </div>
      <div className="space-y-4">
        {sel ? (<>
          <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">{sel.name}</h2><Link className="text-sm underline" to={`/title/${sel.id}`}>Open page</Link></div>
          <RightsPanel titleId={sel.id} /><AssetsPanel titleId={sel.id} isSeries={sel.type === 'series'} /><MarkersPanel titleId={sel.id} isSeries={sel.type === 'series'} />
        </>) : <p className="text-muted">Select a title to manage its rights and media assets.</p>}
      </div>
    </div>
  )
}

function RightsReview() {
  const q = useQuery({ queryKey: ['a-review'], queryFn: () => api('/admin/title-rights', { params: { status: 'unverified' } }) })
  const act = useAdminMutation(({ id }) => api(`/admin/title-rights/${id}/verify`, { method: 'POST' }), ['a-review'])
  if (q.isLoading) return <Spinner />
  return (
    <div className="space-y-2">
      <p className="text-sm text-muted">{q.data?.length || 0} unverified right(s). Confirm the evidence yourself before verifying.</p>
      {q.data?.map((r) => (
        <div key={r.id} className="card flex flex-wrap items-center gap-2 p-3 text-sm">
          <span className="font-mono text-xs">{r.title_id.slice(0, 8)}</span><Badge>{r.license_type}</Badge><span className="text-muted">{r.source}</span>
          {r.evidence_url && <a className="underline" href={r.evidence_url} target="_blank" rel="noopener noreferrer">evidence ↗</a>}
          <button className="btn btn-primary ml-auto !py-1" disabled={act.isPending} onClick={() => act.mutate({ id: r.id })}>Verify</button>
        </div>
      ))}
      <ErrorBox error={act.error || q.error} />
    </div>
  )
}

function Archive() {
  const [q, setQ] = useState('')
  const [term, setTerm] = useState('')
  const [open, setOpen] = useState(null)
  const res = useQuery({ queryKey: ['a-archive', term], queryFn: () => api('/admin/archive/search', { params: { q: term } }), enabled: term.length >= 2 })
  const files = useQuery({ queryKey: ['a-archive-files', open], queryFn: () => api(`/admin/archive/${open}/files`), enabled: !!open })
  const imp = useAdminMutation((identifier) => api('/admin/titles/import', { method: 'POST', body: { provider: 'archive', external_id: identifier } }), ['a-titles', 'a-review'])
  return (
    <div className="space-y-4">
      <Notice>Internet Archive uploads are user-submitted and are often <b>not</b> public domain. Results are candidates only — import creates a draft with unverified rights.</Notice>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setTerm(q) }}><input className="input" placeholder="Search archive.org films…" value={q} onChange={(e) => setQ(e.target.value)} /><button className="btn btn-ghost">Search</button></form>
      <ErrorBox error={res.error} />
      {res.isFetching && <Spinner />}
      <ul className="space-y-2">{res.data?.map((c) => (
        <li key={c.identifier} className="card p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{c.title}</span><span className="text-muted">{c.year}</span><code className="text-xs text-muted">{c.identifier}</code>
            <span className="ml-auto flex gap-1"><button className="btn btn-ghost !py-1" onClick={() => setOpen(open === c.identifier ? null : c.identifier)}>Inspect</button>
              <button className="btn btn-primary !py-1" disabled={imp.isPending} onClick={() => imp.mutate(c.identifier)}>Import draft</button></span></div>
          {open === c.identifier && (files.isLoading ? <Spinner /> : files.data && (
            <div className="mt-2 space-y-1 text-xs text-muted">
              <div>License URL: {files.data.license_url || 'none declared'} · suggested: <b>{files.data.suggested_license_type || 'unknown'}</b></div>
              <div>Embed: {files.data.embed_url}</div>
              <ul>{files.data.files.slice(0, 8).map((f) => <li key={f.name} className="truncate">{f.format} — {f.url}</li>)}</ul>
            </div>))}
        </li>))}</ul>
      <ErrorBox error={imp.error} />
      {imp.isSuccess && <Notice tone="ok">Imported as draft. Open it in Titles to review rights and add the asset.</Notice>}
    </div>
  )
}

function Audit() {
  const q = useQuery({ queryKey: ['a-audit'], queryFn: () => api('/admin/audit-logs', { params: { limit: 100 } }) })
  if (q.isLoading) return <Spinner />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="text-xs uppercase text-muted"><tr><th className="p-2">When</th><th className="p-2">Action</th><th className="p-2">Entity</th><th className="p-2">Detail</th></tr></thead>
        <tbody>{q.data?.map((a) => (
          <tr key={a.id} className="border-t border-line"><td className="p-2 whitespace-nowrap">{new Date(a.created_at).toLocaleString()}</td><td className="p-2">{a.action}</td>
            <td className="p-2 font-mono text-xs">{a.entity_type}:{a.entity_id?.slice(0, 8)}</td><td className="p-2 text-xs text-muted">{a.detail ? JSON.stringify(a.detail) : ''}</td></tr>))}</tbody>
      </table>
      <ErrorBox error={q.error} />
    </div>
  )
}

/* ---------------- playback problem reports ---------------- */
function Reports() {
  const [status, setStatus] = useState('open')
  const [page, setPage] = useState(1)
  const q = useQuery({ queryKey: ['a-reports', status, page], queryFn: () => api('/admin/playback-reports', { params: { status, page } }) })
  const resolve = useAdminMutation((id) => api(`/admin/playback-reports/${id}/resolve`, { method: 'POST' }), ['a-reports'])
  const label = Object.fromEntries(REPORT_KINDS)
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Show"><select className="input" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }}>
          <option value="open">Open</option><option value="resolved">Resolved</option><option value="all">All</option></select></Field>
        {q.data && <span className="pb-2 text-sm text-muted">{q.data.total} report{q.data.total === 1 ? '' : 's'}</span>}
      </div>
      {q.isLoading ? <Spinner /> : q.data?.items.length === 0 ? <Notice tone="info">No reports here.</Notice> : q.data?.items.map((r) => (
        <div key={r.id} className="card space-y-1 p-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Link className="font-semibold hover:underline" to={`/title/${r.title_id}`}>{r.title}</Link>
            {r.episode && <Badge>{r.episode}</Badge>}
            <Badge>{label[r.kind] || r.kind}</Badge>
            {r.position_seconds != null && <span className="tabular-nums text-muted">at {clock(r.position_seconds)}</span>}
            <span className="ml-auto text-xs text-muted">{new Date(r.created_at).toLocaleString()}</span>
          </div>
          {r.note && <p className="whitespace-pre-wrap break-words">{r.note}</p>}
          {r.user_agent && <p className="truncate text-xs text-muted" title={r.user_agent}>{r.user_agent}</p>}
          {r.status === 'open'
            ? <button className="btn btn-ghost !py-1" disabled={resolve.isPending} onClick={() => resolve.mutate(r.id)} aria-label={`Mark the report on ${r.title} resolved`}>Mark resolved</button>
            : <Badge>resolved</Badge>}
        </div>
      ))}
      <ErrorBox error={q.error || resolve.error} />
      {q.data && q.data.total > 30 && (
        <div className="flex gap-2">
          <button className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button>
          <button className="btn btn-ghost" disabled={page * 30 >= q.data.total} onClick={() => setPage(page + 1)}>Next</button>
        </div>
      )}
    </div>
  )
}

/* ---------------- home billboard ---------------- */
function Featured() {
  const [q, setQ] = useState('')
  const [country, setCountry] = useState('*')
  const [position, setPosition] = useState(0)
  const dq = useDebounced(q)
  const cur = useQuery({ queryKey: ['a-featured'], queryFn: () => api('/admin/featured') })
  const found = useQuery({ queryKey: ['a-titles', dq, 'published'], queryFn: () => api('/admin/titles', { params: { q: dq, status: 'published' } }), enabled: dq.length > 1 })
  const add = useAdminMutation((id) => api('/admin/featured', { method: 'POST', body: { title_id: id, country: country.trim() || '*', position: Number(position) || 0 } }), ['a-featured'])
  const del = useAdminMutation((id) => api(`/admin/featured/${id}`, { method: 'DELETE' }), ['a-featured'])
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div className="space-y-3">
        <h2 className="font-semibold">On the billboard</h2>
        <p className="text-xs text-muted">Shown in position order, lowest first. When nothing is listed here the home page uses a trending title instead.</p>
        {cur.isLoading ? <Spinner /> : cur.data?.length === 0 ? <Notice tone="info">Nothing curated yet.</Notice> : cur.data?.map((f) => (
          <div key={f.id} className="card flex items-center gap-3 p-2 text-sm">
            <span className="w-6 text-center text-muted">{f.position}</span>
            <span className="min-w-0 flex-1 truncate">{f.title.name}</span>
            <Badge>{f.country === '*' ? 'everywhere' : f.country}</Badge>
            <button className="btn btn-ghost !py-1" disabled={del.isPending} onClick={() => del.mutate(f.id)} aria-label={`Remove ${f.title.name} from billboard`}>Remove</button>
          </div>
        ))}
        <ErrorBox error={cur.error || del.error} />
      </div>
      <div className="space-y-3">
        <h2 className="font-semibold">Add a published title</h2>
        <div className="grid gap-2 sm:grid-cols-3">
          <div className="sm:col-span-3"><Field label="Search"><input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type at least 2 letters" /></Field></div>
          <Field label="Country" hint="* or ISO code"><input className="input" value={country} maxLength={2} onChange={(e) => setCountry(e.target.value)} /></Field>
          <Field label="Position"><input className="input" type="number" min={0} max={100} value={position} onChange={(e) => setPosition(e.target.value)} /></Field>
        </div>
        {found.isFetching && <Spinner />}
        {found.data?.items.length === 0 && <Notice tone="info">No published titles match.</Notice>}
        {found.data?.items.map((t) => (
          <div key={t.id} className="card flex items-center gap-3 p-2 text-sm">
            <span className="min-w-0 flex-1 truncate">{t.name} <span className="text-muted">{t.year}</span></span>
            {!t.backdrop_url && <Badge>no backdrop</Badge>}
            <button className="btn btn-primary !py-1" disabled={add.isPending} onClick={() => add.mutate(t.id)}>Feature</button>
          </div>
        ))}
        <ErrorBox error={add.error} />
      </div>
    </div>
  )
}

export default function Admin() {
  const [tab, setTab] = useState('titles')
  useEffect(() => setDocTitle('Admin'), [])
  const View = { titles: Titles, rights: RightsReview, featured: Featured, archive: Archive, reports: Reports, audit: Audit }[tab]
  return (
    <div className="px-4 py-6 sm:px-8">
      <PageTitle sub="Manage titles, content rights and media assets. Every change is audit-logged.">Admin dashboard</PageTitle>
      <div role="tablist" className="mb-6 flex flex-wrap gap-2">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={`btn ${tab === k ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <View />
    </div>
  )
}
