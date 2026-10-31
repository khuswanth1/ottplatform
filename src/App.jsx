import { lazy, Suspense } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { useAuth } from './auth/AuthContext'
import Navbar from './components/Navbar'
import Footer from './components/Footer'
import { Spinner } from './components/ui'
import Home from './pages/Home'

// Route-level code splitting keeps the first load small (player, admin and forms load on demand).
const Browse = lazy(() => import('./pages/Browse'))
const Search = lazy(() => import('./pages/Search'))
const TitlePage = lazy(() => import('./pages/TitlePage'))
const Watch = lazy(() => import('./pages/Watch'))
const Latest = lazy(() => import('./pages/Latest'))
const MyList = lazy(() => import('./pages/MyList'))
const Profiles = lazy(() => import('./pages/Profiles'))
const Admin = lazy(() => import('./pages/Admin'))
const Design = import.meta.env.DEV ? lazy(() => import('./pages/Design')) : null // dev-only primitives gallery
const Plans = lazy(() => import('./pages/Plans'))
const Account = lazy(() => import('./pages/Account'))
const { Login, Register, VerifyEmail, ForgotPassword, ResetPassword } = {
  Login: lazy(() => import('./pages/Auth').then((m) => ({ default: m.Login }))),
  Register: lazy(() => import('./pages/Auth').then((m) => ({ default: m.Register }))),
  VerifyEmail: lazy(() => import('./pages/Auth').then((m) => ({ default: m.VerifyEmail }))),
  ForgotPassword: lazy(() => import('./pages/Auth').then((m) => ({ default: m.ForgotPassword }))),
  ResetPassword: lazy(() => import('./pages/Auth').then((m) => ({ default: m.ResetPassword }))),
}

function RequireAuth({ admin = false, needProfile = true }) {
  const { user, loading, profileId, profiles, profilesLoading, isAdmin } = useAuth()
  const loc = useLocation()
  if (loading || (user && profilesLoading)) return <Spinner />
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname + loc.search }} replace />
  if (admin && !isAdmin) return <Navigate to="/" replace />
  if (needProfile && !profileId && profiles.length > 0) return <Navigate to="/profiles" state={{ from: loc.pathname + loc.search }} replace />
  return <Outlet />
}

function Layout() {
  const { activeProfile } = useAuth()
  return (
    <div className="min-h-screen flex flex-col" data-kids={activeProfile?.is_kids ? 'true' : undefined}>
      <Navbar />
      <main className="flex-1 pt-[var(--nav-h,3.5rem)] sm:pt-[var(--nav-h,4rem)]">
        <Suspense fallback={<Spinner />}><Outlet /></Suspense>
      </main>
      <Footer />
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="browse" element={<Browse />} />
        <Route path="search" element={<Search />} />
        <Route path="title/:id" element={<TitlePage />} />
        <Route path="latest" element={<Latest />} />
        <Route path="plans" element={<Plans />} />
        {Design && <Route path="design" element={<Design />} />}
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="verify-email" element={<VerifyEmail />} />
        <Route path="forgot-password" element={<ForgotPassword />} />
        <Route path="reset-password" element={<ResetPassword />} />
        <Route element={<RequireAuth needProfile={false} />}>
          <Route path="profiles" element={<Profiles />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route path="watch/:id" element={<Watch />} />
          <Route path="my-list" element={<MyList />} />
          <Route path="account" element={<Account />} />
        </Route>
        <Route element={<RequireAuth admin />}>
          <Route path="admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<div className="p-10 text-center text-muted">Page not found.</div>} />
      </Route>
    </Routes>
  )
}
