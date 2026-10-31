import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import Row from '../components/Row'
import { Field, setDocTitle } from '../components/ui'

const BENEFITS = [
  { title: 'See where to watch', body: 'Search any title and get the services that carry it in your region, with a direct link out. No hunting through five apps.' },
  { title: 'Watch the free ones here', body: 'Titles we have verified rights for play in the built-in player. It remembers where you stopped and picks up there next time.' },
  { title: 'Profiles for the whole house', body: 'Up to five profiles, each with its own list and history. Set a profile to kids or an age level and it only shows what fits.' },
  { title: 'Keep a list', body: 'Save anything to My list from any screen. It stays with your profile, whichever device you sign in on.' },
]

const FAQ = [
  { q: 'Is it free?', a: 'Creating an account is free, and so is every title marked "Free here". Some titles are included only with a paid plan, and the plans page shows what that costs in your region.' },
  { q: 'Why do some titles have no Play button?', a: 'We only stream titles we have confirmed the rights to. For everything else we show which licensed service offers it and link you there.' },
  { q: 'What does a paid plan add?', a: 'It unlocks the premium titles that we are licensed to stream. Prices and what each plan includes are on the plans page.' },
  { q: 'How do kids profiles work?', a: 'Pick Kids or an age level when you create a profile. That profile only sees matching titles in browse, search, My list and the player.' },
  { q: 'Can I cancel any time?', a: 'Yes. Open your account, choose Manage billing, and cancel. Your plan runs until the end of the period you have paid for.' },
]

function Teaser() {
  const q = useQuery({ queryKey: ['landing-rows'], queryFn: () => api('/catalog/home'), staleTime: 10 * 60_000, retry: false })
  if (q.isLoading) return <div className="flex gap-3 overflow-hidden px-4 sm:px-12" aria-hidden>{Array.from({ length: 8 }, (_, i) => <div key={i} className="skeleton aspect-[2/3] w-[150px] shrink-0" />)}</div>
  // The teaser is a bonus: if the catalog is down or empty the page still works, so errors stay quiet here.
  const row = q.data?.rows?.find((r) => r.id === 'trending') || q.data?.rows?.[0]
  return row ? <Row title="Popular right now" items={row.items} /> : null
}

export default function Landing() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  useEffect(() => setDocTitle(''), [])
  // The address travels in router state, not in the URL, so it never lands in history, logs or referrers.
  const start = (e) => { e.preventDefault(); nav('/register', { state: { email: email.trim() } }) }

  return (
    <div className="pb-12">
      <section className="relative isolate -mt-36 sm:-mt-16 overflow-hidden px-4 pb-16 pt-52 text-center sm:px-12 sm:pb-24 sm:pt-44">
        <div className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_top,color-mix(in_srgb,var(--color-accent)_40%,transparent),transparent_65%)]" />
        <div className="absolute inset-x-0 bottom-0 -z-10 h-1/3 bg-gradient-to-t from-bg to-transparent" />
        <div className="mx-auto max-w-3xl">
          <h1 className="text-4xl font-black sm:text-6xl">Find what you can actually watch.</h1>
          <p className="mx-auto mt-4 max-w-xl text-lg text-text-muted">
            One place to search every title, see who is streaming it near you, and play the ones that are free and licensed right here.
          </p>
          <form className="mx-auto mt-8 flex max-w-xl flex-col gap-3 text-left sm:flex-row sm:items-end" onSubmit={start}>
            <div className="flex-1">
              <Field label="Email address"><input className="input !py-3" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" /></Field>
            </div>
            <button className="btn btn-primary !px-6 !py-3 !text-base">Create free account</button>
          </form>
          <p className="mt-4 text-sm text-text-muted">Already have one? <Link to="/login" className="text-text underline">Sign in</Link> · <Link to="/plans" className="text-text underline">See plans</Link></p>
        </div>
      </section>

      <div className="relative z-10"><Teaser /></div>

      <section className="mx-auto mt-6 max-w-5xl px-4 sm:px-12" aria-labelledby="why-h">
        <h2 id="why-h" className="mb-6 text-2xl font-bold">What you get</h2>
        <ul className="grid gap-4 sm:grid-cols-2">
          {BENEFITS.map((b) => (
            <li key={b.title} className="card p-5">
              <h3 className="text-lg font-semibold">{b.title}</h3>
              <p className="mt-1 text-sm text-text-muted">{b.body}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="mx-auto mt-12 max-w-3xl px-4 sm:px-12" aria-labelledby="faq-h">
        <h2 id="faq-h" className="mb-4 text-2xl font-bold">Questions</h2>
        <div className="divide-y divide-border rounded-lg border border-border">
          {FAQ.map((f) => (
            <details key={f.q} className="group p-4">
              <summary className="flex cursor-pointer list-none items-center justify-between gap-4 font-medium">
                {f.q}<span aria-hidden className="text-text-muted transition-transform group-open:rotate-45">+</span>
              </summary>
              <p className="mt-2 text-sm text-text-muted">{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="mx-auto mt-12 max-w-xl px-4 text-center sm:px-12">
        <h2 className="text-2xl font-bold">Ready when you are.</h2>
        <p className="mt-2 text-text-muted">It takes a minute to sign up, and the free titles are waiting.</p>
        <Link to="/register" className="btn btn-primary mt-5 !px-6 !py-3 !text-base">Create free account</Link>
      </section>
    </div>
  )
}
