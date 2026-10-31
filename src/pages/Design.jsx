import { useEffect, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TitleCard from '../components/TitleCard'
import { RankedCard } from '../components/Row'
import Avatar, { AVATARS, AvatarPicker } from '../components/Avatar'
import SuggestionList from '../components/SuggestionList'
import NotificationBell from '../components/NotificationBell'
import RemindButton from '../components/RemindButton'
import SkipButton from '../components/SkipButton'
import StillWatching from '../components/StillWatching'
import { AuthContext } from '../auth/AuthContext'
import { RatingButtons } from './TitlePage'
import { PinPrompt } from './Profiles'
import { Devices, Invoices, ManagePlan } from './Account'
import { History } from './MyList'
import { Badge, ErrorBox, Field, Notice, PageTitle, setDocTitle } from '../components/ui'

// Development-only gallery of the design-system primitives (route /design, not shipped in production builds).
// The first sections are static. The "newer components" section uses the real components with a private query cache and a made-up signed-in state, so the page still renders without a backend.

const SWATCHES = ['bg', 'surface', 'raised', 'border', 'border-input', 'text', 'text-muted', 'accent', 'accent-hover', 'on-accent', 'accent-text', 'danger', 'success', 'warning']
const SAMPLE = { id: 'x', name: 'A film with a rather long name that has to truncate nicely', year: 2021, type: 'movie', original_language: 'en', poster_url: null, direct: { entitlement: 'registered' } }

const Section = ({ title, children }) => (
  <section className="mb-10" aria-labelledby={`s-${title}`}>
    <h2 id={`s-${title}`} className="mb-3 border-b border-border pb-1 text-lg font-semibold">{title}</h2>
    {children}
  </section>
)


// ---- data-backed components -------------------------------------------------------------------------------------------
// These are the real components. They read from TanStack Query and the auth context, so the gallery gives them a private
// query cache with made-up answers and a made-up signed-in state. Nothing here talks to the API unless you press a button
// that writes (then you see the real error state, because there is no server behind this page).
const GP = 'gallery-profile'
const day = (n) => new Date(Date.now() + n * 86_400_000).toISOString()
const card = (id, name, extra = {}) => ({ id, name, type: 'movie', year: 2024, poster_url: null, backdrop_url: null, genres: ['Drama', 'Mystery'], age_rating: 'PG-13', runtime_minutes: 112, original_language: 'en', direct: null, release_date: null, ...extra })

function makeClient() {
  const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false, refetchOnWindowFocus: false } } })
  qc.setQueryData(['watchlist-ids', GP], { watchlist: ['wl'], favorite: [] })
  qc.setQueryData(['rating', 'rated', GP], { value: 1 })
  qc.setQueryData(['rating', 'unrated', GP], { value: null })
  qc.setQueryData(['reminder-ids', GP], ['remind-on'])
  qc.setQueryData(['notifications', GP], {
    unread: 2,
    items: [
      { id: 'n1', kind: 'new_episode', title: card('a', 'Harbor Nights'), episode_label: 'S2:E3 The Return', created_at: day(0), read_at: null },
      { id: 'n2', kind: 'new_in_list', title: card('b', 'Midnight Run'), created_at: day(-1), read_at: null },
      { id: 'n3', kind: 'reminder_released', title: card('c', 'Coming Soon Alpha', { release_date: day(-2).slice(0, 10) }), created_at: day(-2), read_at: day(-1) },
    ],
  })
  qc.setQueryData(['devices'], [
    { id: 'd1', label: 'Firefox on Linux', ip: '203.0.113.7', created_at: day(-3), last_seen_at: day(0), current: false },
    { id: 'd2', label: 'Safari on iPhone', ip: '198.51.100.20', created_at: day(-9), last_seen_at: day(-2), current: false },
    { id: 'd3', label: 'Chrome on Windows', ip: '192.0.2.4', created_at: day(-1), last_seen_at: day(0), current: true },
  ])
  qc.setQueryData(['plans'], { enabled: true, plans: [
    { code: 'free', name: 'Free', has_ads: false, premium_titles: false, max_streams: 1, price: null, purchasable: false },
    { code: 'ads', name: 'With ads', has_ads: true, premium_titles: true, max_streams: 1, price: { currency: 'USD', amount_cents: 500 }, purchasable: true },
    { code: 'standard', name: 'Standard', has_ads: false, premium_titles: true, max_streams: 2, price: { currency: 'USD', amount_cents: 1000 }, purchasable: true },
    { code: 'premium', name: 'Premium', has_ads: false, premium_titles: true, max_streams: 4, price: { currency: 'USD', amount_cents: 2000 }, purchasable: true },
  ] })
  qc.setQueryData(['invoices'], [
    { id: 'in2', number: 'CV-0002', created: day(-3), total_cents: 2000, currency: 'USD', status: 'paid', url: 'https://invoice.example/2' },
    { id: 'in1', number: 'CV-0001', created: day(-33), total_cents: 1000, currency: 'USD', status: 'open', url: null },
  ])
  qc.setQueryData(['history', GP, 50], [
    { id: 'h1', title: card('x', 'Harbor Nights', { type: 'series', direct: { entitlement: 'registered' } }), episode_id: 'e1', episode_label: 'S1:E2 Night 2', position_seconds: 900, duration_seconds: 3000, completed: false, updated_at: day(0) },
    { id: 'h2', title: card('y', 'A very long film title that has to wrap onto a second line without breaking the layout'), episode_id: null, episode_label: null, position_seconds: 6000, duration_seconds: 6000, completed: true, updated_at: day(-4) },
  ])
  return qc
}

const FAKE_AUTH = { user: { id: 'u1', email: 'demo@example.com', role: 'user' }, profileId: GP, profiles: [], activeProfile: { id: GP, name: 'Demo', is_kids: false }, isAdmin: false, loading: false, profilesLoading: false, selectProfile: () => {}, login: async () => {}, logout: async () => {} }
const SUGGESTIONS = [{ id: 's1', name: 'Midnight Harbor', year: 2019 }, { id: 's2', name: 'Midnight Run Again', year: 2021 }, { id: 's3', name: 'Midway Mirage', year: 2017 }]
const Frame = ({ children, className = '' }) => <div className={`relative overflow-hidden rounded-lg border border-border bg-black ${className}`}>{children}</div>

function NewerComponents() {
  const [client] = useState(makeClient)
  const [avatarPick, setAvatarPick] = useState('avatar-3')
  return (
    <QueryClientProvider client={client}>
      <AuthContext.Provider value={FAKE_AUTH}>
        <p className="mb-6 text-sm text-text-muted">The components below were added after the first design pass. They are the real ones, fed made-up data.</p>

        <Section title="Avatars and picker">
          <ul className="mb-4 flex flex-wrap gap-3">{AVATARS.map((a) => <li key={a.id} className="text-center text-xs text-text-muted"><Avatar avatar={a.id} size="h-16 w-16" /><span className="mt-1 block">{a.name}</span></li>)}<li className="text-center text-xs text-text-muted"><Avatar avatar="avatar-99" name="Demo" size="h-16 w-16 text-2xl" /><span className="mt-1 block">Fallback</span></li></ul>
          <div className="card max-w-md p-4"><AvatarPicker value={avatarPick} onChange={setAvatarPick} name="gallery-avatar" /></div>
        </Section>

        <Section title="Hover preview card">
          <p className="mb-2 text-xs text-text-muted">Rest the mouse on the card for about 0.6 s (touch and keyboard users get the title page instead).</p>
          <div className="w-[150px]"><TitleCard title={card('h', 'Harbor Nights', { backdrop_url: null, direct: { entitlement: 'registered' } })} /></div>
        </Section>

        <Section title="Ranked card (Top 10)">
          <div className="flex gap-2 overflow-x-auto pb-2">{[1, 2, 10].map((r) => <RankedCard key={r} rank={r} title={card(`r${r}`, `Ranked title ${r}`)} />)}</div>
        </Section>

        <Section title="Rating buttons">
          <div className="space-y-2">
            <div><p className="mb-1 text-xs text-text-muted">Liked</p><RatingButtons id="rated" /></div>
            <div><p className="mb-1 text-xs text-text-muted">Not rated</p><RatingButtons id="unrated" /></div>
          </div>
        </Section>

        <Section title="Search suggestions">
          <div className="relative max-w-sm">
            <input className="input" aria-label="Search titles (gallery)" defaultValue="mid" readOnly />
            <SuggestionList options={SUGGESTIONS} active={1} />
          </div>
          <div className="h-44" aria-hidden />
        </Section>

        <Section title="Notification bell">
          <p className="mb-2 text-xs text-text-muted">Press the bell. Three kinds: new episode, now available from your list, reminded title is out.</p>
          <div className="flex min-h-[22rem] items-start"><NotificationBell /></div>
        </Section>

        <Section title="Remind me button">
          <div className="flex flex-wrap gap-2"><RemindButton id="remind-on" /><RemindButton id="remind-off" /></div>
        </Section>

        <Section title="Skip marker button">
          <Frame className="aspect-video max-w-xl"><SkipButton label="Skip intro" onClick={() => {}} /></Frame>
        </Section>

        <Section title="Still watching dialog">
          <Frame className="aspect-video max-w-xl"><StillWatching autoFocus={false} className="absolute inset-0" onContinue={() => {}} onStop={() => {}} /></Frame>
        </Section>

        <Section title="PIN prompt">
          <PinPrompt profile={{ id: GP, name: 'Demo', avatar: 'avatar-2' }} onUnlocked={() => {}} onCancel={() => {}} />
        </Section>

        <Section title="Devices card"><div className="max-w-2xl"><Devices /></div></Section>

        <Section title="Change plan and cancel">
          <div className="card max-w-2xl p-5"><ManagePlan sub={{ plan_code: 'standard', cancel_at_period_end: false, current_period_end: day(20) }} /></div>
        </Section>

        <Section title="Invoices"><div className="max-w-2xl"><Invoices /></div></Section>

        <Section title="Viewing activity list"><div className="max-w-2xl"><History /></div></Section>
      </AuthContext.Provider>
    </QueryClientProvider>
  )
}

export default function Design() {
  const [level, setLevel] = useState('7+')
  useEffect(() => setDocTitle('Design system'), [])
  return (
    <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8">
      <PageTitle sub="Tokens and primitives. Edit replica/design/tokens.json, regenerate tokens.css, and look here first.">Design system</PageTitle>

      <Section title="Colour roles">
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {SWATCHES.map((n) => (
            <li key={n} className="text-xs">
              <span className="block h-12 rounded-md border border-border" style={{ background: `var(--color-${n})` }} />
              <span className="mt-1 block text-text-muted">{n}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title="Type">
        <div className="space-y-1">
          <p className="text-4xl font-bold">Display 40</p><p className="text-3xl font-bold">Title 28</p>
          <p className="text-xl font-semibold">Heading 20</p><p>Body 16 with <a className="underline" href="#s-Type">a link</a>.</p>
          <p className="text-sm text-text-muted">Small muted 14</p><p className="text-xs font-medium">Caption 12</p>
        </div>
      </Section>

      <Section title="Buttons">
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn btn-primary">Primary</button>
          <button className="btn btn-ghost">Ghost</button>
          <button className="btn btn-light">Light</button>
          <button className="btn btn-dim">Dim</button>
          <button className="btn btn-primary" disabled>Disabled</button>
          <button className="btn btn-primary" aria-busy="true" disabled>Saving…</button>
        </div>
        <p className="mt-2 text-xs text-text-muted">Press Tab to check the focus ring on each.</p>
      </Section>

      <Section title="Form fields">
        <form className="grid max-w-xl gap-3" onSubmit={(e) => e.preventDefault()}>
          <Field label="Email" hint="We only use it to sign you in."><input className="input" type="email" placeholder="you@example.com" /></Field>
          <Field label="Name (error)"><input className="input !border-danger" aria-invalid="true" defaultValue="" /></Field>
          <Field label="Disabled"><input className="input opacity-50" disabled defaultValue="Locked" /></Field>
          <fieldset>
            <legend className="mb-1 text-sm text-text-muted">Radio group</legend>
            {['kids', '7+', '13+', 'all'].map((l) => (
              <label key={l} className={`mb-1 flex cursor-pointer items-center gap-3 rounded-lg border p-2 text-sm ${level === l ? 'border-accent-text bg-raised' : 'border-border'}`}>
                <input type="radio" name="lvl" checked={level === l} onChange={() => setLevel(l)} /> {l}
              </label>
            ))}
          </fieldset>
        </form>
      </Section>

      <Section title="Badges and notices">
        <div className="mb-3 flex flex-wrap gap-2"><Badge>Neutral</Badge><Badge tone="free">Free here</Badge><Badge tone="premium">Premium</Badge><Badge tone="kids">Kids</Badge></div>
        <div className="space-y-2">
          <Notice tone="info">Info notice in muted text.</Notice><Notice>Warning notice that needs attention.</Notice><Notice tone="ok">Success notice.</Notice>
          <ErrorBox error={new Error('Something went wrong. Please try again.')} onRetry={() => {}} />
        </div>
      </Section>

      <Section title="Cards and tiles">
        <div className="flex flex-wrap gap-4">
          <div className="w-[150px]"><TitleCard title={SAMPLE} /></div>
          <div className="w-[150px]"><TitleCard title={{ ...SAMPLE, id: 'y', name: 'Short', direct: null }} /></div>
          <div className="card w-64 p-4"><h3 className="font-semibold">Plain card</h3><p className="text-sm text-text-muted">Surface with border, radius md.</p></div>
        </div>
      </Section>

      <Section title="Loading">
        <div className="flex gap-3" aria-hidden>{[0, 1, 2].map((i) => <div key={i} className="skeleton aspect-[2/3] w-[120px]" />)}</div>
      </Section>

      <NewerComponents />
    </div>
  )
}
