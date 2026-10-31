// First sign-in: a free account is taken to the plans page once, to set up AutoPay. Nothing is charged by this;
// the person still has to pick a plan and authorise the mandate in Razorpay Checkout.
const key = (userId) => `ott.autopay_offered.${userId}`

export function shouldOfferAutopay(user, storage = globalThis.localStorage) {
  if (!user || user.plan !== 'free' || user.role === 'admin') return false
  try {
    if (storage.getItem(key(user.id))) return false
    storage.setItem(key(user.id), '1')
    return true
  } catch {
    return false // private mode: never nag without being able to remember
  }
}

const SCRIPT = 'https://checkout.razorpay.com/v1/checkout.js'

/** Loads Razorpay's Checkout once; resolves to window.Razorpay or rejects if the script is blocked/offline. */
export function loadRazorpay() {
  if (globalThis.Razorpay) return Promise.resolve(globalThis.Razorpay)
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SCRIPT
    s.async = true
    s.onload = () => (globalThis.Razorpay ? resolve(globalThis.Razorpay) : reject(new Error('Razorpay did not load.')))
    s.onerror = () => reject(new Error('Could not load the payment window. Check your connection or ad blocker.'))
    document.head.appendChild(s)
  })
}
