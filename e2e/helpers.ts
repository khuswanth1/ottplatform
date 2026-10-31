import { expect, type Page, type BrowserContext } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

export const PASSWORD = 'correct horse battery'
let counter = 0
export const uniqueEmail = (tag = 'user') => `${tag}-${Date.now()}-${++counter}@example.com`

// The seeded videos live on a host that does not exist here, so the browser reports those loads as failed. That is the only
// console noise we accept; everything else (and any 5xx from our own API) fails the test.
const ACCEPTED_NOISE = [/cdn\.example\.com/, /\/auth\/me/, // a signed-out visitor's session check answers 401 (BUG-001, S4)
   /Failed to load resource.*(ERR_NAME_NOT_RESOLVED|ERR_FAILED|ERR_BLOCKED|ERR_INTERNET_DISCONNECTED)/]

export function guard(page: Page, { allow = [] as RegExp[] } = {}) {
  const problems: string[] = []
  page.on('console', (m) => {
    if (m.type() !== 'error') return
    const text = `${m.text()} ${m.location().url}`
    // an intentional 401/403/409 answer shows up as a console error too: tests that provoke one list it in `allow`
    if ([...ACCEPTED_NOISE, ...allow].some((r) => r.test(text))) return
    problems.push(`console error: ${m.text()}`)
  })
  page.on('response', (r) => { if (r.status() >= 500) problems.push(`${r.status()} ${r.url()}`) })
  page.on('pageerror', (e) => problems.push(`page error: ${e.message}`))
  return { check: () => expect(problems, problems.join('\n')).toEqual([]) }
}

export async function signUp(page: Page, email = uniqueEmail(), password = PASSWORD) {
  await page.goto('/register')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel(/^Password/).fill(password)
  await page.getByRole('button', { name: /create account|sign up|join/i }).click()
  return { email, password }
}

export async function signIn(page: Page, email: string, password = PASSWORD) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign in' }).click()
}

/** Register through the API (fast), sign in through the UI, pick the first profile. Returns the email. */
export async function member(page: Page, tag = 'member') {
  const email = uniqueEmail(tag)
  const r = await page.request.post('/api/v1/auth/register', { data: { email, password: PASSWORD } })
  expect(r.status()).toBe(202)
  await signIn(page, email)
  await page.waitForURL(/\/profiles|\/$/)
  if (page.url().includes('/profiles')) await page.getByRole('button', { name: /^Me$/ }).click()
  await expect(page.getByRole('button', { name: /^Notifications/ })).toBeVisible()
  return email
}

/** Same-origin API call as the signed-in page (carries the cookie and the CSRF header). */
export async function api(page: Page, method: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH', path: string, data?: unknown, profileId?: string) {
  const me = await (await page.request.get('/api/v1/auth/me')).json()
  const headers: Record<string, string> = { 'X-CSRF-Token': me.csrf_token }
  if (profileId) headers['X-Profile-Id'] = profileId
  return page.request.fetch(`/api/v1${path}`, { method, data, headers })
}

export async function profileId(page: Page) {
  return page.evaluate(() => localStorage.getItem('ott.profile') || '')
}

export async function noAxeViolations(page: Page) {
  const r = await new AxeBuilder({ page }).disableRules(['color-contrast']).analyze() // contrast is checked from the tokens with contrast.py
  expect(r.violations.map((v) => `${page.url().replace(/[0-9a-f-]{36}/g, ':id')} ${v.id}: ${v.nodes.map((n) => n.target.join(' ')).slice(0, 3).join(' | ')}`)).toEqual([])
}

export const fresh = (ctx: BrowserContext) => ctx.newPage()

/** Id of a seeded title by exact name, through the public search API. */
export async function titleId(page: Page, name: string) {
  const r = await (await page.request.get(`/api/v1/catalog/search?q=${encodeURIComponent(name)}`)).json()
  const hit = r.items.find((t: { name: string }) => t.name === name)
  expect(hit, `seeded title ${name}`).toBeTruthy()
  return hit.id as string
}

export async function episodeIds(page: Page, id: string) {
  const eps = await (await page.request.get(`/api/v1/titles/${id}/episodes?season=1`)).json()
  return eps.map((e: { id: string }) => e.id) as string[]
}

/** Signs in as the seeded administrator and returns a page that is an admin session. */
export async function adminApi(page: Page) {
  const r = await page.request.post('/api/v1/auth/login', { data: { email: 'admin@example.com', password: PASSWORD } })
  expect(r.status()).toBe(200)
  const csrf = (await r.json()).csrf_token as string
  return (method: 'PUT' | 'POST' | 'DELETE' | 'PATCH', path: string, data?: unknown) => page.request.fetch(`/api/v1${path}`, { method, data, headers: { 'X-CSRF-Token': csrf } })
}
