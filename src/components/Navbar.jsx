import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import NotificationBell from './NotificationBell'
import Avatar from './Avatar'
import SuggestionList from './SuggestionList'
import { useDebounced } from './ui'
import { COUNTRIES, setCountry, useCountry } from '../lib/region'
import { GlobeIcon, MenuIcon, SearchIcon, XIcon } from './icons'

const navLinkClass = ({ isActive }) =>
  `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
    isActive ? 'text-white bg-white/10 font-semibold shadow-sm' : 'text-text-muted hover:text-white hover:bg-white/5'
  }`

const mobileLinkClass = ({ isActive }) =>
  `flex items-center gap-3 px-4 py-3 rounded-lg text-base font-medium transition-colors ${
    isActive ? 'text-white bg-brand/20 border-l-4 border-brand font-semibold' : 'text-text-muted hover:text-white hover:bg-white/5'
  }`

export default function Navbar() {
  const { user, activeProfile, logout, isAdmin } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const country = useCountry()
  const [q, setQ] = useState(new URLSearchParams(loc.search).get('q') || '')
  const [mobileNav, setMobileNav] = useState(false)
  const [mobileSearch, setMobileSearch] = useState(false)
  const [profileMenu, setProfileMenu] = useState(false)
  const debounced = useDebounced(q, 400)
  const first = useRef(true)
  const headerRef = useRef(null)
  const searchInputRef = useRef(null)
  const mobileInputRef = useRef(null)

  useLayoutEffect(() => {
    const el = headerRef.current
    if (!el) return undefined
    const set = () => {
      const h = Math.ceil(el.getBoundingClientRect().height)
      document.documentElement.style.setProperty('--nav-h', `${h}px`)
    }
    set()
    if (typeof ResizeObserver === 'undefined') return undefined
    const ro = new ResizeObserver(set)
    ro.observe(el)
    return () => ro.disconnect()
  }, [mobileSearch])

  const [scrolled, setScrolled] = useState(false)
  const [focused, setFocused] = useState(false)
  const [active, setActive] = useState(-1)
  const term = debounced.trim()
  const sugg = useQuery({
    queryKey: ['suggest', term],
    queryFn: () => api('/catalog/suggest', { params: { q: term } }),
    enabled: focused && term.length >= 2,
    staleTime: 5 * 60_000,
  })
  const options = focused && term.length >= 2 ? sugg.data || [] : []

  useEffect(() => { setActive(-1) }, [term])

  const onKey = (e) => {
    if (e.key === 'Escape') {
      setFocused(false)
      setMobileSearch(false)
      return
    }
    if (!options.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((a) => (a + 1) % options.length)
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((a) => (a <= 0 ? options.length - 1 : a - 1))
    }
    if (e.key === 'Enter' && active >= 0) {
      e.preventDefault()
      setFocused(false)
      setMobileSearch(false)
      nav(`/title/${options[active].id}`)
    }
  }

  useEffect(() => {
    const f = () => setScrolled(window.scrollY > 10)
    f()
    window.addEventListener('scroll', f, { passive: true })
    return () => window.removeEventListener('scroll', f)
  }, [])

  useEffect(() => {
    if (first.current) { first.current = false; return }
    const t = debounced.trim()
    if (t.length >= 2 && loc.pathname === '/search') {
      nav(`/search?q=${encodeURIComponent(t)}`, { replace: true })
    }
  }, [debounced]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setProfileMenu(false)
    setMobileNav(false)
    setMobileSearch(false)
  }, [loc.pathname])

  useEffect(() => {
    if (mobileSearch) {
      setTimeout(() => mobileInputRef.current?.focus(), 50)
    }
  }, [mobileSearch])

  useEffect(() => {
    if (mobileNav) {
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
    }
    return () => { document.body.style.overflow = '' }
  }, [mobileNav])

  const handleSearchSubmit = (e) => {
    e.preventDefault()
    setFocused(false)
    setMobileSearch(false)
    if (q.trim()) nav(`/search?q=${encodeURIComponent(q.trim())}`)
  }

  return (
    <header
      ref={headerRef}
      className={`fixed inset-x-0 top-0 z-40 transition-all duration-300 ${
        scrolled || mobileSearch || mobileNav ? 'nav-solid shadow-xl' : 'nav-clear'
      }`}
    >
      <div className="mx-auto flex h-14 sm:h-16 max-w-7xl items-center justify-between px-3.5 sm:px-8 gap-2 sm:gap-4">
        {/* Left: Mobile hamburger + Brand + Desktop navigation */}
        <div className="flex items-center gap-2 sm:gap-6 min-w-0">
          <button
            type="button"
            className="md:hidden flex h-10 w-10 items-center justify-center rounded-lg text-text hover:bg-white/10 transition-colors"
            aria-label={mobileNav ? 'Close menu' : 'Open navigation menu'}
            aria-expanded={mobileNav}
            onClick={() => setMobileNav((m) => !m)}
          >
            {mobileNav ? <XIcon size={22} /> : <MenuIcon size={22} />}
          </button>

          <Link to="/" className="logo-text text-xl sm:text-2xl font-black tracking-wider shrink-0" aria-label="CineVerse home">
            CineVerse
          </Link>

          <nav className="hidden md:flex items-center gap-1" aria-label="Main navigation">
            <NavLink to="/" end className={navLinkClass}>Home</NavLink>
            <NavLink to="/browse?type=movie" className={navLinkClass}>Movies</NavLink>
            <NavLink to="/browse?type=series" className={navLinkClass}>Series</NavLink>
            <NavLink to="/browse?type=documentary" className={navLinkClass}>Docs</NavLink>
            <NavLink to="/latest" className={navLinkClass}>New</NavLink>
            {user && <NavLink to="/my-list" className={navLinkClass}>My list</NavLink>}
          </nav>
        </div>

        {/* Center/Right: Desktop search bar */}
        <form
          role="search"
          className="relative hidden md:block w-48 lg:w-64"
          onSubmit={handleSearchSubmit}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false)
          }}
        >
          <div className="relative flex items-center">
            <input
              ref={searchInputRef}
              aria-label="Search titles"
              role="combobox"
              aria-expanded={options.length > 0}
              aria-controls="search-suggestions"
              aria-autocomplete="list"
              aria-activedescendant={active >= 0 ? `sugg-${active}` : undefined}
              className="input !py-1.5 !pl-8 !pr-3 !bg-black/40 hover:!bg-black/60 focus:!bg-black/80 !border-white/20 focus:!border-brand transition-all text-sm rounded-full"
              placeholder="Search titles, people..."
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onFocus={() => setFocused(true)}
              onKeyDown={onKey}
              maxLength={100}
              autoComplete="off"
            />
            <span className="absolute left-2.5 text-muted pointer-events-none">
              <SearchIcon size={15} />
            </span>
          </div>
          <SuggestionList options={options} active={active} onPick={() => setFocused(false)} />
        </form>

        {/* Right tools: Mobile search button, region selector, notifications, profile */}
        <div className="flex items-center gap-1.5 sm:gap-3 shrink-0">
          <button
            type="button"
            className="md:hidden flex h-9 w-9 items-center justify-center rounded-lg text-text hover:bg-white/10 transition-colors"
            aria-label="Toggle search bar"
            onClick={() => setMobileSearch((s) => !s)}
          >
            <SearchIcon size={20} />
          </button>

          <div className="hidden lg:flex items-center gap-1 text-xs text-text-muted bg-surface/80 border border-line rounded-lg px-2 py-1">
            <GlobeIcon size={14} className="text-muted" />
            <select
              aria-label="Streaming availability region"
              className="bg-transparent border-none text-xs text-text focus:outline-none cursor-pointer"
              value={country}
              onChange={(e) => setCountry(e.target.value)}
            >
              {COUNTRIES.map(([c, n]) => (
                <option key={c} value={c} className="bg-surface text-text">
                  {n}
                </option>
              ))}
            </select>
          </div>

          <NotificationBell />

          <div className="relative">
            {user ? (
              <>
                <button
                  type="button"
                  className="flex items-center gap-2 rounded-full p-0.5 hover:ring-2 hover:ring-brand transition-all"
                  aria-haspopup="menu"
                  aria-expanded={profileMenu}
                  onClick={() => setProfileMenu((m) => !m)}
                >
                  <Avatar avatar={activeProfile?.avatar} name={activeProfile?.name || user.email} size="h-8 w-8 text-xs ring-1 ring-white/20" />
                  <span className="hidden xl:inline text-xs font-medium max-w-[100px] truncate">{activeProfile?.name || 'Profile'}</span>
                </button>

                {profileMenu && (
                  <div
                    role="menu"
                    className="absolute right-0 mt-2 w-52 card p-1.5 text-sm shadow-2xl border border-line/80 bg-surface/95 backdrop-blur-md rounded-xl z-50 animate-[fadein_.15s_ease-out]"
                  >
                    <div className="px-3 py-2 border-b border-line mb-1">
                      <div className="text-xs text-muted">Signed in as</div>
                      <div className="font-semibold truncate text-white">{activeProfile?.name || user.email}</div>
                    </div>
                    <Link role="menuitem" className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-raised hover:text-white transition-colors" to="/profiles">
                      Switch profile
                    </Link>
                    <Link role="menuitem" className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-raised hover:text-white transition-colors" to="/my-list?tab=history">
                      Viewing activity
                    </Link>
                    <Link role="menuitem" className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-raised hover:text-white transition-colors" to="/account">
                      Account
                    </Link>
                    <Link role="menuitem" className="block rounded-lg px-3 py-2 text-sm text-text hover:bg-raised hover:text-white transition-colors" to="/plans">
                      Plans
                    </Link>
                    {isAdmin && (
                      <Link role="menuitem" className="block rounded-lg px-3 py-2 text-sm text-brand-text hover:bg-raised transition-colors" to="/admin">
                        Admin dashboard
                      </Link>
                    )}
                    <div className="my-1 border-t border-line" />
                    <button
                      type="button"
                      role="menuitem"
                      className="w-full rounded-lg px-3 py-2 text-left text-sm text-danger hover:bg-raised transition-colors"
                      onClick={async () => {
                        await logout()
                        nav('/')
                      }}
                    >
                      Sign out
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="flex items-center gap-1.5 sm:gap-2">
                <Link to="/login" className="btn btn-ghost !py-1 !px-2.5 sm:!px-3 text-xs sm:text-sm">Sign in</Link>
                <Link to="/register" className="btn btn-primary !py-1 !px-2.5 sm:!px-3 text-xs sm:text-sm hidden xs:inline-flex">Join</Link>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Mobile search bar */}
      {mobileSearch && (
        <div className="md:hidden border-t border-line/60 bg-bg/95 backdrop-blur-xl px-4 py-3 animate-[slideDown_.2s_ease-out]">
          <form
            role="search"
            className="relative"
            onSubmit={handleSearchSubmit}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget)) setFocused(false)
            }}
          >
            <div className="relative flex items-center">
              <input
                ref={mobileInputRef}
                aria-label="Search titles mobile"
                role="combobox"
                aria-expanded={options.length > 0}
                aria-controls="mobile-search-suggestions"
                aria-autocomplete="list"
                className="input !py-2 !pl-9 !pr-9 !bg-black/60 !border-white/30 text-sm rounded-lg"
                placeholder="Search movies, series, actors..."
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onFocus={() => setFocused(true)}
                onKeyDown={onKey}
                maxLength={100}
                autoComplete="off"
              />
              <span className="absolute left-3 text-muted pointer-events-none">
                <SearchIcon size={16} />
              </span>
              {q && (
                <button
                  type="button"
                  className="absolute right-2.5 p-1 text-muted hover:text-white"
                  onClick={() => setQ('')}
                  aria-label="Clear search text"
                >
                  <XIcon size={16} />
                </button>
              )}
            </div>
            <SuggestionList options={options} active={active} onPick={() => { setFocused(false); setMobileSearch(false) }} />
          </form>
        </div>
      )}

      {/* Mobile Drawer */}
      {mobileNav && (
        <div className="fixed inset-0 z-50 md:hidden flex">
          <div
            className="fixed inset-0 bg-black/70 backdrop-blur-sm transition-opacity"
            onClick={() => setMobileNav(false)}
            aria-hidden="true"
          />

          <div className="relative flex-1 max-w-xs w-full bg-surface border-r border-line p-5 shadow-2xl flex flex-col justify-between overflow-y-auto animate-[slideInLeft_.25s_cubic-bezier(.2,.8,.2,1)]">
            <div className="space-y-6">
              <div className="flex items-center justify-between border-b border-line pb-4">
                <Link to="/" className="logo-text text-xl font-black" onClick={() => setMobileNav(false)}>
                  CineVerse
                </Link>
                <button
                  type="button"
                  className="rounded-lg p-1.5 text-text-muted hover:text-white hover:bg-white/10"
                  onClick={() => setMobileNav(false)}
                  aria-label="Close navigation"
                >
                  <XIcon size={20} />
                </button>
              </div>

              {user ? (
                <div className="flex items-center gap-3 p-3 rounded-xl bg-raised border border-line">
                  <Avatar avatar={activeProfile?.avatar} name={activeProfile?.name || user.email} size="h-10 w-10 text-sm" />
                  <div className="min-w-0 flex-1">
                    <div className="text-xs text-muted">Active Profile</div>
                    <div className="font-semibold text-sm truncate text-white">{activeProfile?.name || 'Default'}</div>
                  </div>
                  <Link
                    to="/profiles"
                    className="text-xs text-brand hover:underline shrink-0"
                    onClick={() => setMobileNav(false)}
                  >
                    Switch
                  </Link>
                </div>
              ) : (
                <div className="p-3 rounded-xl bg-raised border border-line flex flex-col gap-2">
                  <div className="text-sm font-semibold text-white">Welcome to CineVerse</div>
                  <div className="text-xs text-muted">Sign in to sync your watchlist, ratings, and progress.</div>
                  <div className="flex gap-2 pt-1">
                    <Link to="/login" className="btn btn-primary flex-1 !py-1 text-xs" onClick={() => setMobileNav(false)}>
                      Sign in
                    </Link>
                    <Link to="/register" className="btn btn-ghost flex-1 !py-1 text-xs" onClick={() => setMobileNav(false)}>
                      Join
                    </Link>
                  </div>
                </div>
              )}

              <nav className="flex flex-col space-y-1" aria-label="Mobile main navigation">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted px-4 mb-1">Browse</div>
                <NavLink to="/" end className={mobileLinkClass} onClick={() => setMobileNav(false)}>Home</NavLink>
                <NavLink to="/browse?type=movie" className={mobileLinkClass} onClick={() => setMobileNav(false)}>Movies</NavLink>
                <NavLink to="/browse?type=series" className={mobileLinkClass} onClick={() => setMobileNav(false)}>TV Series</NavLink>
                <NavLink to="/browse?type=documentary" className={mobileLinkClass} onClick={() => setMobileNav(false)}>Documentaries</NavLink>
                <NavLink to="/latest" className={mobileLinkClass} onClick={() => setMobileNav(false)}>New & Popular</NavLink>
                {user && <NavLink to="/my-list" className={mobileLinkClass} onClick={() => setMobileNav(false)}>My List</NavLink>}
              </nav>

              <div className="px-4 py-2 border-t border-line">
                <div className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">Streaming Region</div>
                <div className="flex items-center gap-2 bg-raised border border-line rounded-lg px-3 py-2">
                  <GlobeIcon size={16} className="text-brand shrink-0" />
                  <select
                    aria-label="Mobile region select"
                    className="w-full bg-transparent border-none text-xs text-text focus:outline-none cursor-pointer"
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                  >
                    {COUNTRIES.map(([c, n]) => (
                      <option key={c} value={c} className="bg-surface text-text">
                        {n}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>

            {user && (
              <div className="border-t border-line pt-4 mt-6 space-y-1">
                <Link to="/account" className="block px-4 py-2 text-sm text-text hover:text-white" onClick={() => setMobileNav(false)}>
                  Account Settings
                </Link>
                <Link to="/plans" className="block px-4 py-2 text-sm text-text hover:text-white" onClick={() => setMobileNav(false)}>
                  Plans & Billing
                </Link>
                {isAdmin && (
                  <Link to="/admin" className="block px-4 py-2 text-sm text-brand-text font-medium" onClick={() => setMobileNav(false)}>
                    Admin Dashboard
                  </Link>
                )}
                <button
                  type="button"
                  className="w-full text-left px-4 py-2 text-sm text-danger hover:underline"
                  onClick={async () => {
                    setMobileNav(false)
                    await logout()
                    nav('/')
                  }}
                >
                  Sign Out
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  )
}
