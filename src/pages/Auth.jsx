import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { shouldOfferAutopay } from '../lib/autopay'
import { ErrorBox, Field, Notice, Spinner, setDocTitle } from '../components/ui'

function Shell({ title, children, footer }) {
  useEffect(() => setDocTitle(title), [title])
  return (
    <div className="mx-auto w-full max-w-md px-4 py-10">
      <div className="card space-y-4 p-6">
        <h1 className="text-2xl font-bold">{title}</h1>
        {children}
      </div>
      {footer && <p className="mt-4 text-center text-sm text-muted">{footer}</p>}
    </div>
  )
}

export function Login() {
  const { login } = useAuth()
  const nav = useNavigate()
  const loc = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const m = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (user) => nav('/profiles', { replace: true, state: { from: shouldOfferAutopay(user) ? '/plans?autopay=1' : loc.state?.from || '/' } }),
  })
  return (
    <Shell title="Sign in" footer={<>New here? <Link className="text-white underline" to="/register">Create an account</Link></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Field label="Email"><input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password"><input className="input" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <ErrorBox error={m.error} />
        <button className="btn btn-primary w-full" disabled={m.isPending}>{m.isPending ? 'Signing in…' : 'Sign in'}</button>
        <Link to="/forgot-password" className="block text-center text-sm text-muted hover:text-white">Forgot your password?</Link>
      </form>
    </Shell>
  )
}

export function Register() {
  const loc = useLocation()
  const [email, setEmail] = useState(typeof loc.state?.email === 'string' ? loc.state.email : '')
  const [password, setPassword] = useState('')
  const m = useMutation({ mutationFn: () => api('/auth/register', { method: 'POST', body: { email, password } }) })
  if (m.isSuccess) return <Shell title="Check your inbox"><Notice tone="ok">{m.data.message}</Notice><Link to="/login" className="btn btn-ghost w-full">Back to sign in</Link></Shell>
  return (
    <Shell title="Create your account" footer={<>Already a member? <Link className="text-white underline" to="/login">Sign in</Link></>}>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
        <Field label="Email"><input className="input" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Password" hint="At least 10 characters."><input className="input" type="password" autoComplete="new-password" minLength={10} maxLength={128} required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <ErrorBox error={m.error} />
        <button className="btn btn-primary w-full" disabled={m.isPending}>{m.isPending ? 'Creating…' : 'Create account'}</button>
      </form>
    </Shell>
  )
}

export function VerifyEmail() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const m = useMutation({ mutationFn: () => api('/auth/verify-email', { method: 'POST', body: { token } }) })
  useEffect(() => { if (token) m.mutate() }, [token]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Shell title="Email verification">
      {!token && <ErrorBox error={new Error('This link is missing its token.')} />}
      {m.isPending && <Spinner />}
      {m.isSuccess && <><Notice tone="ok">{m.data.message}</Notice><Link to="/login" className="btn btn-primary w-full">Sign in</Link></>}
      <ErrorBox error={m.error} />
    </Shell>
  )
}

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const m = useMutation({ mutationFn: () => api('/auth/forgot-password', { method: 'POST', body: { email } }) })
  return (
    <Shell title="Reset your password">
      {m.isSuccess ? <Notice tone="ok">{m.data.message}</Notice> : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
          <Field label="Email"><input className="input" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          <ErrorBox error={m.error} />
          <button className="btn btn-primary w-full" disabled={m.isPending}>Send reset link</button>
        </form>
      )}
    </Shell>
  )
}

export function ResetPassword() {
  const [params] = useSearchParams()
  const [password, setPassword] = useState('')
  const m = useMutation({ mutationFn: () => api('/auth/reset-password', { method: 'POST', body: { token: params.get('token'), password } }) })
  return (
    <Shell title="Choose a new password">
      {m.isSuccess ? <><Notice tone="ok">{m.data.message}</Notice><Link to="/login" className="btn btn-primary w-full">Sign in</Link></> : (
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); m.mutate() }}>
          <Field label="New password" hint="At least 10 characters."><input className="input" type="password" autoComplete="new-password" minLength={10} maxLength={128} required value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
          <ErrorBox error={m.error} />
          <button className="btn btn-primary w-full" disabled={m.isPending}>Update password</button>
        </form>
      )}
    </Shell>
  )
}
