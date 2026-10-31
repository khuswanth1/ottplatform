import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Badge, ErrorBox, Notice, PageTitle, setDocTitle } from '../components/ui'
import { formatMoney } from '../lib/money'
import { loadRazorpay } from '../lib/autopay'

const PERKS = {
  free: ['Titles that are free to watch', 'Where-to-watch links for everything else'],
  ads: ['Premium titles included', 'Short ad breaks'],
  standard: ['Premium titles included', 'No ad breaks'],
  premium: ['Premium titles included', 'No ad breaks', 'Highest quality when available'],
}

function PlanCard({ plan, current, onChoose, busy, loggedIn }) {
  const price = plan.price ? formatMoney(plan.price.amount_cents, plan.price.currency) : null
  return (
    <li className={`card flex flex-col gap-3 p-5 ${current ? 'border-accent-text' : ''}`}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">{plan.name}</h2>
        {current && <Badge tone="free">Your plan</Badge>}
      </div>
      <p className="text-2xl font-bold">
        {plan.code === 'free' ? 'Free' : price ? <>{price}<span className="text-sm font-normal text-muted"> / month</span></> : <span className="text-base font-normal text-muted">Not available here</span>}
      </p>
      <ul className="flex-1 space-y-1 text-sm text-muted">
        {(PERKS[plan.code] || []).map((p) => <li key={p}>✓ {p}</li>)}
        <li>✓ {plan.max_streams === 1 ? '1 screen at a time' : `${plan.max_streams} screens at a time`}</li>
      </ul>
      {plan.code !== 'free' && (
        current ? <Link to="/account" className="btn btn-ghost">Manage</Link>
          : !loggedIn ? <button className="btn btn-primary" disabled={!plan.purchasable} onClick={() => onChoose(plan, plan.providers?.[0])}>Sign up to choose</button>
          : (
            <div className="flex flex-col gap-2">
              {plan.providers?.includes('razorpay_once') && (
                <button className="btn btn-primary" disabled={!plan.purchasable || busy} onClick={() => onChoose(plan, 'razorpay_once')}>
                  {busy === 'razorpay_once' ? 'Opening payment…' : 'Pay now: UPI, cards, net banking'}
                </button>
              )}
              {plan.providers?.includes('razorpay') && (
                <button className={`btn ${plan.providers.includes('razorpay_once') ? 'btn-ghost' : 'btn-primary'}`} disabled={!plan.purchasable || busy} onClick={() => onChoose(plan, 'razorpay')}>
                  {busy === 'razorpay' ? 'Opening payment…' : 'Subscribe with AutoPay (cards, eMandate)'}
                </button>
              )}
              {plan.providers?.includes('stripe') && (
                <button className={`btn ${plan.providers.some((x) => x.startsWith('razorpay')) ? 'btn-ghost' : 'btn-primary'}`} disabled={!plan.purchasable || busy} onClick={() => onChoose(plan, 'stripe')}>
                  {busy === 'stripe' ? 'Opening checkout…' : plan.providers.some((x) => x.startsWith('razorpay')) ? 'Pay by card (Stripe)' : `Choose ${plan.name}`}
                </button>
              )}
              {!plan.providers?.length && <button className="btn btn-primary" disabled>Not available here</button>}
            </div>
          )
      )}
    </li>
  )
}

export default function Plans() {
  const { user } = useAuth()
  const nav = useNavigate()
  const [params] = useSearchParams()
  useEffect(() => setDocTitle('Plans'), [])
  const q = useQuery({ queryKey: ['plans'], queryFn: () => api('/billing/plans'), staleTime: 5 * 60_000 })
  const sub = useQuery({ queryKey: ['subscription'], queryFn: () => api('/billing/subscription'), enabled: !!user })
  const qc = useQueryClient()
  const [busy, setBusy] = useState('')
  const [paid, setPaid] = useState(false)
  const stripeCheckout = useMutation({
    mutationFn: (plan) => api('/billing/checkout', { method: 'POST', body: { plan_code: plan.code } }),
    onSuccess: (r) => { window.location.assign(r.url) },
    onSettled: () => setBusy(''),
  })
  // AutoPay: the server creates the recurring subscription, Razorpay Checkout collects the authorisation, then the server
  // verifies the signed result and re-reads the subscription from Razorpay before it grants anything.
  const razorpayCheckout = useMutation({
    mutationFn: async (plan) => {
      const [Razorpay, start] = await Promise.all([loadRazorpay(), api('/billing/razorpay/subscribe', { method: 'POST', body: { plan_code: plan.code } })])
      return new Promise((resolve, reject) => {
        const rzp = new Razorpay({
          key: start.key_id, subscription_id: start.subscription_id, name: start.name, description: `${plan.name} plan, billed monthly with AutoPay`,
          prefill: { email: start.email }, theme: { color: '#e50914' },
          handler: (res) => api('/billing/razorpay/verify', { method: 'POST', body: res }).then(resolve, reject),
          modal: { ondismiss: () => reject(Object.assign(new Error('Checkout was closed. You have not been charged.'), { dismissed: true })) },
        })
        rzp.on('payment.failed', (r) => reject(new Error(r?.error?.description || 'The payment failed. You have not been charged.')))
        rzp.open()
      })
    },
    onSuccess: () => { setPaid(true); qc.invalidateQueries({ queryKey: ['subscription'] }); qc.invalidateQueries({ queryKey: ['me'] }) },
    onSettled: () => setBusy(''),
  })
  // Pay once: Razorpay's all-methods Checkout (UPI, cards, net banking, wallets). The amount is fixed server-side; the result
  // is verified (signature + the order re-read from Razorpay) before 30 days of the plan are granted.
  const razorpayOnce = useMutation({
    mutationFn: async (plan) => {
      const [Razorpay, order] = await Promise.all([loadRazorpay(), api('/billing/razorpay/order', { method: 'POST', body: { plan_code: plan.code } })])
      return new Promise((resolve, reject) => {
        const rzp = new Razorpay({
          key: order.key_id, order_id: order.order_id, amount: order.amount, currency: order.currency, name: order.name,
          description: `${plan.name} plan, 30 days`, prefill: { email: order.email }, theme: { color: '#e50914' },
          handler: (res) => api('/billing/razorpay/verify-order', { method: 'POST', body: res }).then(resolve, reject),
          modal: { ondismiss: () => reject(Object.assign(new Error('Checkout was closed. You have not been charged.'), { dismissed: true })) },
        })
        rzp.on('payment.failed', (r) => reject(new Error(r?.error?.description || 'The payment failed. You have not been charged.')))
        rzp.open()
      })
    },
    onSuccess: () => { setPaid(true); qc.invalidateQueries({ queryKey: ['subscription'] }); qc.invalidateQueries({ queryKey: ['me'] }) },
    onSettled: () => setBusy(''),
  })
  const checkout = { error: stripeCheckout.error || [razorpayCheckout.error, razorpayOnce.error].find((e) => e && !e.dismissed) || null }
  const choose = (plan, provider) => {
    if (!user) return nav('/register', { state: { from: '/plans' } })
    setBusy(provider)
    if (provider === 'razorpay') return razorpayCheckout.mutate(plan)
    if (provider === 'razorpay_once') return razorpayOnce.mutate(plan)
    return stripeCheckout.mutate(plan)
  }
  const live = ['active', 'trialing', 'past_due'].includes(sub.data?.status)

  return (
    <div className="mx-auto max-w-5xl px-4 py-10 sm:px-8">
      <PageTitle sub="Pick what suits you. You can change or cancel from your account.">Plans</PageTitle>
      <div className="mb-4 space-y-3">
        {paid && <Notice tone="ok">Payment received and your plan is active. <Link className="underline" to="/account">View your account</Link>.</Notice>}
        {user && params.get('autopay') && !live && !paid && <Notice tone="info">Welcome! Pick a plan. Pay once with UPI, card or net banking for 30 days, or turn on AutoPay (cards, eMandate) to renew monthly. Nothing is charged until you confirm in the payment window.</Notice>}
        {params.get('checkout') === 'cancelled' && <Notice tone="info">Checkout was cancelled. You have not been charged.</Notice>}
        {q.data && !q.data.enabled && <Notice>Paid plans are not open yet. Everything free to watch is still available.</Notice>}
        {live && <Notice tone="info">You already have a plan. Change or cancel it from <Link className="underline" to="/account">your account</Link>.</Notice>}
        <ErrorBox error={q.error || checkout.error} onRetry={q.error ? q.refetch : undefined} />
      </div>
      {q.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-hidden>{Array.from({ length: 4 }, (_, i) => <div key={i} className="skeleton h-56" />)}</div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {q.data?.plans.map((p) => (
            <PlanCard key={p.code} plan={{ ...p, purchasable: p.purchasable && q.data.enabled && !live && !paid }} current={sub.data?.plan_code === p.code && (p.code === 'free' ? !live : live)}
              loggedIn={!!user} busy={busy} onChoose={choose} />
          ))}
        </ul>
      )}
    </div>
  )
}
