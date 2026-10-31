import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { LockIcon } from '../components/icons'
import Avatar, { AvatarPicker } from '../components/Avatar'
import { Badge, ErrorBox, Field, setDocTitle, Spinner } from '../components/ui'
import { LEVELS, isRestricted, levelLabel, levelOf } from '../lib/maturity'

const LANGS = [['en', 'English'], ['hi', 'हिन्दी Hindi'], ['te', 'తెలుగు Telugu'], ['ta', 'தமிழ் Tamil'], ['ml', 'മലയാളം Malayalam'], ['kn', 'ಕನ್ನಡ Kannada'], ['bn', 'বাংলা Bengali'], ['mr', 'मराठी Marathi'], ['es', 'Español'], ['fr', 'Français'], ['de', 'Deutsch'], ['ja', '日本語'], ['ko', '한국어']]

const payload = ({ name, avatar, language, maturity_level }) => ({ name, avatar, language, maturity_level })

// Set, change or remove the 4-digit PIN. Needs the account password; the server never returns the PIN.
function PinSettings({ profileId }) {
  const qc = useQueryClient()
  const { profiles } = useAuth()
  const profile = profiles.find((p) => p.id === profileId) // live copy: the editor's own snapshot goes stale after a save
  const [open, setOpen] = useState(false)
  const [pin, setPin] = useState('')
  const [password, setPassword] = useState('')
  const save = useMutation({
    mutationFn: (clear) => api(`/profiles/${profile.id}/pin`, { method: 'PUT', body: { pin: clear ? null : pin, password } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['profiles'] }); setOpen(false); setPin(''); setPassword('') },
  })
  if (!profile) return null
  return (
    <fieldset className="space-y-2">
      <legend className="mb-1 text-sm text-muted">Profile lock</legend>
      <p className="text-sm">{profile.has_pin ? 'A 4-digit PIN is needed to open this profile.' : 'Anyone can open this profile.'}</p>
      {!open && (
        <div className="flex gap-2">
          <button type="button" className="btn btn-ghost" onClick={() => setOpen(true)}><LockIcon /> {profile.has_pin ? 'Change or remove PIN' : 'Set a PIN'}</button>
        </div>
      )}
      {open && (
        <div className="card space-y-3 p-3">
          <Field label="New 4-digit PIN" hint="Leave empty and choose Remove to turn the lock off.">
            <input className="input" type="password" inputMode="numeric" autoComplete="off" pattern="[0-9]{4}" maxLength={4} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ''))} />
          </Field>
          <Field label="Your account password"><input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <ErrorBox error={save.error} />
          <div className="flex gap-2">
            <button type="button" className="btn btn-primary" disabled={save.isPending || pin.length !== 4 || !password} onClick={() => save.mutate(false)}>Save PIN</button>
            {profile.has_pin && <button type="button" className="btn btn-ghost" disabled={save.isPending || !password} onClick={() => save.mutate(true)}>Remove PIN</button>}
            <button type="button" className="btn btn-ghost" onClick={() => { setOpen(false); save.reset() }}>Cancel</button>
          </div>
        </div>
      )}
    </fieldset>
  )
}

export function PinPrompt({ profile, onUnlocked, onCancel }) {
  const [pin, setPin] = useState('')
  const [reset, setReset] = useState(false)
  const [password, setPassword] = useState('')
  const digits = (e) => setPin(e.target.value.replace(/\D/g, ''))
  const unlock = useMutation({
    mutationFn: () => (reset
      ? api(`/profiles/${profile.id}/pin`, { method: 'PUT', body: { pin, password } }) // also opens the profile for this session
      : api(`/profiles/${profile.id}/unlock`, { method: 'POST', body: { pin } })),
    onSuccess: onUnlocked,
    onError: () => setPin(''),
  })
  return (
    <form className="card mx-auto max-w-sm space-y-4 p-6" onSubmit={(e) => { e.preventDefault(); if (pin.length === 4 && (!reset || password)) unlock.mutate() }}>
      <div className="flex justify-center"><Avatar name={profile.name} avatar={profile.avatar} size="h-16 w-16 text-2xl" /></div>
      <h1 className="text-xl font-bold">{reset ? `Choose a new PIN for ${profile.name}` : `Enter the PIN for ${profile.name}`}</h1>
      <input className="input text-center text-2xl tracking-[0.5em]" aria-label={reset ? 'New PIN' : `PIN for ${profile.name}`} type="password" inputMode="numeric" autoComplete="off"
        autoFocus pattern="[0-9]{4}" maxLength={4} value={pin} onChange={digits} />
      {reset && <Field label="Your account password"><input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>}
      <ErrorBox error={unlock.error} />
      <div className="flex justify-center gap-2">
        <button className="btn btn-primary" disabled={unlock.isPending || pin.length !== 4 || (reset && !password)}>{reset ? 'Save and open' : 'Open profile'}</button>
        <button type="button" className="btn btn-ghost" onClick={onCancel}>Cancel</button>
      </div>
      <button type="button" className="text-xs text-muted underline" onClick={() => { setReset((r) => !r); setPin(''); unlock.reset() }}>
        {reset ? 'I remember the PIN' : 'Forgot the PIN? Reset it with your account password'}
      </button>
    </form>
  )
}

function Editor({ profile, onDone }) {
  const qc = useQueryClient()
  const [f, setF] = useState(profile ? { ...profile, maturity_level: levelOf(profile) } : { name: '', avatar: 'avatar-1', language: 'en', maturity_level: 'all' })
  const save = useMutation({
    mutationFn: () => (profile ? api(`/profiles/${profile.id}`, { method: 'PATCH', body: payload(f) }) : api('/profiles', { method: 'POST', body: payload(f) })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['profiles'] }); onDone() },
  })
  const del = useMutation({
    mutationFn: () => api(`/profiles/${profile.id}`, { method: 'DELETE' }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['profiles'] }); onDone() },
  })
  return (
    <form className="card mx-auto max-w-md space-y-4 p-6" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
      <h1 className="text-xl font-bold">{profile ? 'Edit profile' : 'Add profile'}</h1>
      <Field label="Name"><input className="input" required maxLength={40} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <AvatarPicker value={f.avatar} onChange={(avatar) => setF({ ...f, avatar })} />
      <Field label="Preferred language" hint="Used for titles, descriptions and the “Popular in…” row.">
        <select className="input" value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}>{LANGS.map(([c, l]) => <option key={c} value={c}>{l}</option>)}</select>
      </Field>
      <fieldset>
        <legend className="mb-1 text-sm text-muted">What can this profile watch?</legend>
        <div className="space-y-1">
          {LEVELS.map((l) => (
            <label key={l.id} className={`flex cursor-pointer items-start gap-3 rounded-lg border p-2 text-sm ${f.maturity_level === l.id ? 'border-accent-text bg-raised' : 'border-border'}`}>
              <input type="radio" name="maturity" className="mt-1" checked={f.maturity_level === l.id} onChange={() => setF({ ...f, maturity_level: l.id })} />
              <span><span className="font-medium">{l.label}</span><span className="block text-xs text-muted">{l.hint}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      {profile && <PinSettings profileId={profile.id} />}
      <ErrorBox error={save.error || del.error} />
      <div className="flex gap-2">
        <button className="btn btn-primary" disabled={save.isPending}>Save</button>
        <button type="button" className="btn btn-ghost" onClick={onDone}>Cancel</button>
        {profile && <button type="button" className="btn btn-ghost ml-auto text-danger" disabled={del.isPending} onClick={() => confirm(`Delete “${profile.name}”? Its list and history will be removed.`) && del.mutate()}>Delete</button>}
      </div>
    </form>
  )
}

export default function Profiles() {
  const { profiles, profilesLoading, selectProfile } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [mode, setMode] = useState('pick') // pick | manage
  const [editing, setEditing] = useState(null) // profile | 'new' | null
  const [asking, setAsking] = useState(null) // the locked profile whose PIN is being asked
  useEffect(() => setDocTitle('Who’s watching?'), [])
  if (profilesLoading) return <Spinner />
  if (editing) return <div className="px-4 py-10"><Editor profile={editing === 'new' ? null : editing} onDone={() => setEditing(null)} /></div>
  const open = (p) => { if (mode === 'manage') setEditing(p); else { selectProfile(p.id); nav(loc.state?.from || '/', { replace: true }) } }
  const choose = (p) => (p.has_pin ? setAsking(p) : open(p))
  if (asking) return <div className="px-4 py-10"><PinPrompt profile={asking} onCancel={() => setAsking(null)} onUnlocked={() => { const p = asking; setAsking(null); open(p) }} /></div>
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 text-center">
      <h1 className="mb-8 text-3xl font-bold">{mode === 'manage' ? 'Manage profiles' : 'Who’s watching?'}</h1>
      <ul className="flex flex-wrap justify-center gap-6">
        {profiles.map((p) => (
          <li key={p.id}>
            <button className="group flex flex-col items-center gap-2" onClick={() => choose(p)}>
              <span className="rounded-lg ring-white transition group-hover:ring-2 group-focus-visible:ring-2"><Avatar name={p.name} avatar={p.avatar} /></span>
              <span className="text-sm">{p.has_pin && <LockIcon size={14} />}{p.has_pin && <span className="sr-only">Locked. </span>} {p.name}</span>
              {isRestricted(p) && <Badge tone={p.is_kids ? 'kids' : 'neutral'}>{levelLabel(p)}</Badge>}
              {mode === 'manage' && <span className="text-xs text-muted">Edit</span>}
            </button>
          </li>
        ))}
        {profiles.length < 5 && (
          <li><button className="flex flex-col items-center gap-2" onClick={() => setEditing('new')}>
            <span className="grid h-24 w-24 place-items-center rounded-lg border border-dashed border-line text-3xl text-muted hover:text-white">+</span>
            <span className="text-sm text-muted">Add profile</span></button></li>
        )}
      </ul>
      <button className="btn btn-ghost mt-10" onClick={() => setMode(mode === 'pick' ? 'manage' : 'pick')}>{mode === 'pick' ? 'Manage profiles' : 'Done'}</button>
    </div>
  )
}
