// Prices are integer cents plus an ISO currency code. Format with the viewer's locale; fall back to plain text
// if the currency code is unknown to Intl.
export function formatMoney(cents, currency, locale) {
  if (!Number.isFinite(cents) || !currency) return ''
  try {
    return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(cents / 100)
  } catch {
    return `${(cents / 100).toFixed(2)} ${currency}`
  }
}

export function formatDate(iso, locale) {
  const d = iso ? new Date(iso) : null
  if (!d || Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat(locale, { dateStyle: 'long' }).format(d)
}
