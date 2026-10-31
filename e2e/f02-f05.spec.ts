import { test, expect, type Browser } from '@playwright/test'
import { api, guard, member, noAxeViolations, PASSWORD, profileId, signIn, titleId, uniqueEmail } from './helpers'

// F02 returning user / PIN / stream limit, F03 browse and play, F04 search, F05 My list.

test.describe('F02 returning user', () => {
  test('F02-H1 the session survives a reload and the chosen profile is remembered', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f02')
    await page.reload()
    await expect(page.getByRole('button', { name: /^Notifications/ })).toBeVisible()
    await expect(page).not.toHaveURL(/profiles|login/)
    g.check()
  })

  test('F02-E1 a locked profile asks for its PIN: wrong PIN refused, right PIN opens, other devices must unlock too', async ({ page, browser }) => {
    const g = guard(page, { allow: [/403/] })
    const email = await member(page, 'f02pin')
    // set a PIN through the editor
    await page.goto('/profiles')
    await page.getByRole('button', { name: 'Manage profiles' }).click()
    await page.locator('main').getByRole('button', { name: /Me/ }).click()
    await page.getByRole('button', { name: /Set a PIN/ }).click()
    await page.getByLabel('New 4-digit PIN').fill('1234')
    await page.getByLabel('Your account password').fill(PASSWORD)
    await page.getByRole('button', { name: 'Save PIN' }).click()
    await expect(page.getByRole('button', { name: /Change or remove PIN/ })).toBeVisible()
    // a second device signs in: the profile is locked until the PIN is entered there
    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    const og = guard(other, { allow: [/403/] })
    await signIn(other, email)
    await other.locator('main').getByRole('button', { name: /Me/ }).click()
    await other.getByLabel(/PIN for Me/).fill('9999')
    await other.getByRole('button', { name: 'Open profile' }).click()
    await expect(other.getByRole('alert')).toContainText(/not correct/i)
    await other.getByLabel(/PIN for Me/).fill('1234')
    await other.getByRole('button', { name: 'Open profile' }).click()
    await expect(other.getByRole('button', { name: /^Notifications/ })).toBeVisible()
    await ctx.close()
    g.check()
    og.check()
  })

  test('F02-E2 five wrong PINs lock the profile for a while', async ({ page, browser }) => {
    const email = await member(page, 'f02lock')
    const pid = await profileId(page)
    const r = await api(page, 'PUT', `/profiles/${pid}/pin`, { pin: '4321', password: PASSWORD })
    expect(r.status()).toBe(200)
    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    await signIn(other, email)
    await expect(other.getByRole('heading', { name: /who.s watching/i })).toBeVisible()
    const csrf = (await (await other.request.get('/api/v1/auth/me')).json()).csrf_token
    const attempt = (pin: string) => other.request.post(`/api/v1/profiles/${pid}/unlock`, { data: { pin }, headers: { 'X-CSRF-Token': csrf } })
    for (let i = 0; i < 5; i++) expect((await attempt('0000')).status()).toBe(403)
    expect((await attempt('4321')).status()).toBe(429) // even the right one waits
    await ctx.close()
  })

  test('F02-E3 the plan allows one screen: a second device is refused with a clear message', async ({ page, browser }) => {
    const g = guard(page, { allow: [/409/] })
    const email = await member(page, 'f02screens')
    await page.goto(`/watch/${await titleId(page, 'Open Film')}`)
    await expect(page.getByRole('region', { name: /./ }).or(page.getByLabel('Video player'))).toBeVisible()
    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    const og = guard(other, { allow: [/409/] })
    await signIn(other, email)
    await other.getByRole('button', { name: /Me/ }).click()
    await other.goto(`/watch/${await titleId(other, 'Second Film')}`)
    await expect(other.getByRole('heading', { name: 'All your screens are in use' })).toBeVisible()
    await expect(other.getByRole('link', { name: 'See plans' })).toBeVisible()
    await ctx.close()
    g.check()
    og.check()
  })
})

test.describe('F03 browse, open, play', () => {
  test('F03-H1 home lists a playable title; open it; Play reaches the player', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f03')
    await page.goto('/')
    await page.getByRole('link', { name: /Open Film/ }).first().click()
    await expect(page.getByRole('heading', { name: 'Open Film', level: 1 })).toBeVisible()
    await page.getByRole('link', { name: 'Play' }).first().click()
    await expect(page).toHaveURL(/\/watch\//)
    await expect(page.getByLabel('Video player')).toBeVisible()
    await expect(page.getByRole('button', { name: /^(Play|Pause)$/ })).toBeVisible()
    g.check()
  })

  test('F03-E1 Play on a title with no stream opens an explanation with a trailer link, not other content', async ({ page }) => {
    const g = guard(page, { allow: [/40[34]/] })
    await member(page, 'f03locked')
    const id = await titleId(page, 'Locked Film')
    await page.goto(`/title/${id}`)
    await expect(page.getByRole('heading', { name: 'Locked Film', level: 1 })).toBeVisible()
    await page.getByRole('link', { name: 'Play', exact: true }).click()
    await expect(page.getByRole('heading', { name: /cannot be played here/i })).toBeVisible()
    await expect(page.locator('video, iframe')).toHaveCount(0)
    await page.getByRole('link', { name: /watch the trailer instead/i }).click()
    await expect(page).toHaveURL(/\/title\/[0-9a-f-]{36}\?trailer=1$/)
    g.check()
  })

  test('F03-E3 a made-up title id shows a not-found message', async ({ page }) => {
    const g = guard(page, { allow: [/404/] })
    await member(page, 'f03nf')
    await page.goto('/title/00000000-0000-0000-0000-000000000000')
    await expect(page.getByRole('alert')).toBeVisible()
    g.check()
  })

  test('F03-A1 home, title and watch pages have no accessibility violations', async ({ page }) => {
    await member(page, 'f03a11y')
    for (const path of ['/', `/title/${await titleId(page, 'Open Film')}`, `/watch/${await titleId(page, 'Open Film')}`]) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await noAxeViolations(page)
    }
  })

  test('F03-M1 title page fits a phone and keeps Play reachable @mobile', async ({ page }) => {
    await member(page, 'f03m')
    await page.goto(`/title/${await titleId(page, 'Open Film')}`)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(page.getByRole('link', { name: 'Play' }).first()).toBeVisible()
  })
})

test.describe('F04 search', () => {
  test('F04-H1 typing shows suggestions; arrow keys and Enter open the title', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f04')
    await page.getByLabel('Search titles').fill('open')
    await expect(page.getByRole('listbox', { name: 'Title suggestions' })).toContainText('Open Film')
    await page.getByLabel('Search titles').press('ArrowDown')
    await page.getByLabel('Search titles').press('Enter')
    await expect(page).toHaveURL(/\/title\//)
    await expect(page.getByRole('heading', { name: 'Open Film', level: 1 })).toBeVisible()
    g.check()
  })

  test('F04-H2 Enter without choosing a suggestion shows the results page', async ({ page }) => {
    await member(page, 'f04b')
    const box = page.getByLabel('Search titles')
    await box.fill('film')
    await box.press('Enter')
    await expect(page).toHaveURL(/\/search\?q=film/)
    await expect(page.getByRole('link', { name: /Second Film/ }).first()).toBeVisible()
  })

  test('F04-E1 nothing matches: a friendly empty state, no error', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f04c')
    await page.goto('/search?q=zzzzqqq')
    await expect(page.getByText(/no results/i)).toBeVisible()
    g.check()
  })

  test('F04-E2 emoji, accents and a very long query do not break the page', async ({ page }) => {
    const g = guard(page, { allow: [/422/] })
    await member(page, 'f04d')
    for (const q of ['café ☕ 🎬', 'a'.repeat(100), '%_\\\'"<script>']) {
      await page.goto(`/search?q=${encodeURIComponent(q)}`)
      await expect(page.getByRole('heading', { name: 'Search' })).toBeVisible()
    }
    g.check()
  })

  test('F04-E3 one character is not enough to search', async ({ page }) => {
    await member(page, 'f04e')
    await page.goto('/search?q=o')
    await expect(page.getByText(/at least two characters/i)).toBeVisible()
  })
})

test.describe('F05 My list', () => {
  test('F05-H1 add from the title page, see it in My list, remove it', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f05')
    await page.goto(`/title/${await titleId(page, 'Open Film')}`)
    await page.getByRole('button', { name: /^\s*My list/ }).click()
    await expect(page.getByRole('button', { name: /In my list/ })).toBeVisible()
    await page.goto('/my-list')
    await expect(page.getByRole('link', { name: /Open Film/ }).first()).toBeVisible()
    await page.goto(`/title/${await titleId(page, 'Open Film')}`)
    await page.getByRole('button', { name: /In my list/ }).click()
    await expect(page.getByRole('button', { name: /^\s*My list/ })).toBeVisible()
    await page.goto('/my-list')
    await expect(page.getByText(/nothing here yet/i)).toBeVisible()
    g.check()
  })

  test('F05-E1 the list belongs to one profile: a second profile starts empty', async ({ page }) => {
    await member(page, 'f05b')
    const id = await titleId(page, 'Open Film')
    expect((await api(page, 'PUT', `/watchlist/${id}`, { kind: 'watchlist' }, await profileId(page))).status()).toBe(200)
    const second = await (await api(page, 'POST', '/profiles', { name: 'Second' })).json()
    expect((await (await api(page, 'GET', '/watchlist/ids', undefined, second.id)).json()).watchlist).toEqual([])
  })

  test('F05-E2 adding twice and removing something that is not there both succeed (idempotent)', async ({ page }) => {
    await member(page, 'f05c')
    const pid = await profileId(page)
    const id = await titleId(page, 'Open Film')
    expect((await api(page, 'PUT', `/watchlist/${id}`, undefined, pid)).status()).toBe(200)
    expect((await api(page, 'PUT', `/watchlist/${id}`, undefined, pid)).status()).toBe(200)
    expect((await api(page, 'DELETE', `/watchlist/${id}`, undefined, pid)).status()).toBe(200)
    expect((await api(page, 'DELETE', `/watchlist/${id}`, undefined, pid)).status()).toBe(200)
  })

  test('F05-E3 two tabs toggling the same title end in a consistent state', async ({ page, context }) => {
    await member(page, 'f05d')
    const id = await titleId(page, 'Open Film')
    const tab2 = await context.newPage()
    await Promise.all([page, tab2].map((p) => p.goto(`/title/${id}`)))
    await Promise.all([page, tab2].map((p) => p.getByRole('button', { name: /^\s*My list|In my list/ }).click()))
    await page.reload()
    const ids = await (await api(page, 'GET', '/watchlist/ids', undefined, await profileId(page))).json()
    expect(ids.watchlist.length).toBeLessThanOrEqual(1)
  })

  test('F05-A1 the list and search pages have no accessibility violations', async ({ page }) => {
    await member(page, 'f05a')
    for (const path of ['/my-list', '/search?q=film', '/latest']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await noAxeViolations(page)
    }
  })
})

// keep the helper imports honest
void uniqueEmail
void (null as unknown as Browser)
