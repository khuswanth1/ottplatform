import { test, expect } from '@playwright/test'
import { adminApi, api, episodeIds, guard, member, noAxeViolations, PASSWORD, profileId, signIn, titleId, uniqueEmail } from './helpers'

const ended = (page: import('@playwright/test').Page) => page.evaluate(() => document.querySelector('video')!.dispatchEvent(new Event('ended')))
const episodeParam = (page: import('@playwright/test').Page) => new URL(page.url()).searchParams.get('episode')

test.describe('F06 binge a series', () => {
  test('F06-H1 autoplay rolls on three episodes, then asks "Are you still watching?"; Keep watching goes on', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f06')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    await page.addInitScript(() => localStorage.setItem('ott.autoplayNext', '1'))
    await page.goto(`/watch/${id}?episode=${eps[0]}`)
    for (let i = 1; i <= 3; i++) {
      await expect(page.locator('video')).toBeVisible()
      await ended(page)
      await expect.poll(() => episodeParam(page)).toBe(eps[i])
    }
    await expect(page.locator('video')).toBeVisible()
    await ended(page)
    const dialog = page.getByRole('alertdialog', { name: /still watching/i })
    await expect(dialog).toBeVisible()
    expect(episodeParam(page)).toBe(eps[3]) // did not start the next one by itself
    await expect(dialog.getByRole('button', { name: 'Keep watching' })).toBeFocused()
    await dialog.getByRole('button', { name: 'Keep watching' }).click()
    await expect.poll(() => episodeParam(page)).toBe(eps[4])
    g.check()
  })

  test('F06-E1 with autoplay off the episode ends on a card and waits for a click', async ({ page }) => {
    await member(page, 'f06off')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    await page.goto(`/watch/${id}?episode=${eps[0]}`)
    await expect(page.locator('video')).toBeVisible()
    await ended(page)
    await expect(page.getByText('Episode finished.')).toBeVisible()
    expect(episodeParam(page)).toBe(eps[0])
    await page.getByRole('button', { name: 'Play next episode' }).click()
    await expect.poll(() => episodeParam(page)).toBe(eps[1])
  })

  test('F06-E2 the last episode says the series is finished and offers no next episode', async ({ page }) => {
    await member(page, 'f06last')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    await page.goto(`/watch/${id}?episode=${eps[4]}`)
    await expect(page.locator('video')).toBeVisible()
    await ended(page)
    await expect(page.getByText(/finished watching/i)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Play next episode' })).toHaveCount(0)
  })

  test('F06-E3 an episode that does not belong to the title is refused', async ({ page }) => {
    const g = guard(page, { allow: [/400/] })
    await member(page, 'f06bad')
    const id = await titleId(page, 'Serial')
    await page.goto(`/watch/${id}?episode=00000000-0000-0000-0000-000000000000`)
    await expect(page.getByRole('alert')).toBeVisible()
    g.check()
  })

  test('F06-E4 skip intro appears inside the range an admin entered, and jumps to its end', async ({ page, browser }) => {
    await member(page, 'f06skip')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    const ctx = await browser.newContext()
    const admin = await adminApi(await ctx.newPage())
    const r = await admin('PUT', '/admin/markers', { title_id: id, episode_id: eps[0], kind: 'intro', start_s: 60, end_s: 90 })
    expect(r.status()).toBe(200)
    await ctx.close()
    await page.goto(`/watch/${id}?episode=${eps[0]}`)
    await expect(page.locator('video')).toBeVisible()
    await page.evaluate(() => {
      const v = document.querySelector('video')!
      let t = 0
      Object.defineProperty(v, 'currentTime', { configurable: true, get: () => t, set: (x) => { t = x; v.dispatchEvent(new Event('timeupdate')) } })
      Object.defineProperty(v, 'duration', { configurable: true, get: () => 300 })
      ;(window as unknown as { __setTime: (x: number) => void }).__setTime = (x) => { t = x; v.dispatchEvent(new Event('timeupdate')) }
    })
    const set = (x: number) => page.evaluate((s) => (window as unknown as { __setTime: (x: number) => void }).__setTime(s), x)
    await set(59)
    await expect(page.getByRole('button', { name: 'Skip intro' })).toHaveCount(0)
    await set(61)
    await page.getByRole('button', { name: 'Skip intro' }).click()
    await expect(page.getByRole('button', { name: 'Skip intro' })).toHaveCount(0)
    expect(await page.evaluate(() => document.querySelector('video')!.currentTime)).toBe(90)
  })
})

test.describe('F07 profiles', () => {
  test('F07-H1 add a profile, pick an avatar with the keyboard, it shows on the tile', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f07')
    await page.goto('/profiles')
    await page.getByRole('button', { name: 'Manage profiles' }).click()
    await page.getByRole('button', { name: /Add profile/ }).click()
    await page.getByLabel('Name').fill('Kid Brother')
    await page.getByLabel('Sun').focus()
    for (let i = 0; i < 5; i++) await page.keyboard.press('ArrowRight') // Sun, Moon, Cat, Robot, Fox, Owl
    await expect(page.getByLabel('Owl')).toBeChecked()
    await page.getByRole('button', { name: 'Save' }).click()
    await expect(page.locator('main').getByText('Kid Brother')).toBeVisible()
    const profiles = await (await api(page, 'GET', '/profiles')).json()
    expect(profiles.find((p: { name: string }) => p.name === 'Kid Brother').avatar).toBe('avatar-6')
    g.check()
  })

  test('F07-E1 the sixth profile is refused and the add button disappears at five', async ({ page }) => {
    const g = guard(page, { allow: [/409/] })
    await member(page, 'f07max')
    for (let i = 2; i <= 5; i++) expect((await api(page, 'POST', '/profiles', { name: `P${i}` })).status()).toBe(201)
    expect((await api(page, 'POST', '/profiles', { name: 'P6' })).status()).toBe(409)
    await page.goto('/profiles')
    await expect(page.getByRole('button', { name: /Add profile/ })).toHaveCount(0)
    g.check()
  })

  test('F07-E2 the only profile cannot be deleted', async ({ page }) => {
    const g = guard(page, { allow: [/409/] })
    await member(page, 'f07del')
    const [only] = await (await api(page, 'GET', '/profiles')).json()
    expect((await api(page, 'DELETE', `/profiles/${only.id}`)).status()).toBe(409)
    g.check()
  })

  test('F07-E3 duplicate profile names are refused', async ({ page }) => {
    const g = guard(page, { allow: [/409/] })
    await member(page, 'f07dup')
    expect((await api(page, 'POST', '/profiles', { name: 'Me' })).status()).toBe(409)
    g.check()
  })

  test('F07-E4 a kids profile only sees family titles', async ({ page }) => {
    await member(page, 'f07kids')
    const kid = await (await api(page, 'POST', '/profiles', { name: 'Kid', maturity_level: 'kids' })).json()
    const id = await titleId(page, 'Open Film')
    const r = await api(page, 'POST', '/playback/sessions', { title_id: id }, kid.id)
    expect(r.status()).toBe(403)
    expect((await r.json()).detail.code).toBe('kids_restricted')
  })

  test('F07-A1 the profile picker and editor have no accessibility violations', async ({ page }) => {
    await member(page, 'f07a11y')
    await page.goto('/profiles')
    await noAxeViolations(page)
    await page.getByRole('button', { name: 'Manage profiles' }).click()
    await page.locator('main').getByRole('button', { name: /Me/ }).click()
    await noAxeViolations(page)
  })
})

test.describe('F08 plans and account', () => {
  test('F08-H1 with billing off the plans page says so and the account shows the free plan', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f08')
    await page.goto('/plans')
    await expect(page.getByText(/paid plans are not open yet/i)).toBeVisible()
    await expect(page.getByText(/1 screen at a time/).first()).toBeVisible()
    await page.goto('/account')
    await expect(page.getByText(/you are on the free plan/i)).toBeVisible()
    g.check()
  })

  test('F08-E1 change, cancel and resume are refused when there is no paid plan', async ({ page }) => {
    const g = guard(page, { allow: [/409/] })
    await member(page, 'f08none')
    expect((await api(page, 'POST', '/billing/cancel')).status()).toBe(409)
    expect((await api(page, 'POST', '/billing/change-plan', { plan_code: 'premium' })).status()).toBe(409)
    g.check()
  })

  test('F08-N1 card declined, plan change, renewal and cancel against real Stripe: manual (see replica/stripe-test-mode.md)', async () => {
    test.skip(true, 'needs Stripe test mode')
  })
})

test.describe('F09 rate, remove from activity', () => {
  test('F09-H1 a rating survives a reload and clears with a second press', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f09')
    await page.goto(`/title/${await titleId(page, 'Open Film')}`)
    const like = page.getByRole('button', { name: 'I like this' })
    await like.click()
    await expect(like).toHaveAttribute('aria-pressed', 'true')
    await page.reload()
    await expect(page.getByRole('button', { name: 'I like this' })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: 'I like this' }).click()
    await expect(page.getByRole('button', { name: 'I like this' })).toHaveAttribute('aria-pressed', 'false')
    g.check()
  })

  test('F09-H2 watched titles appear in viewing activity and can be removed; removal sticks after a reload', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f09act')
    const pid = await profileId(page)
    const id = await titleId(page, 'Open Film')
    expect((await api(page, 'PUT', '/watch-progress', { title_id: id, position_seconds: 120, duration_seconds: 6000 }, pid)).status()).toBe(200)
    await page.goto('/my-list?tab=history')
    await expect(page.getByRole('link', { name: 'Open Film' })).toBeVisible()
    await page.getByRole('button', { name: /Remove Open Film from viewing activity/ }).click()
    await expect(page.getByText(/nothing watched yet/i)).toBeVisible()
    await page.reload()
    await expect(page.getByText(/nothing watched yet/i)).toBeVisible()
    g.check()
  })

  test('F09-E1 removing someone else\'s activity entry is a 404', async ({ page, browser }) => {
    const g = guard(page, { allow: [/404/] })
    await member(page, 'f09own')
    const pid = await profileId(page)
    await api(page, 'PUT', '/watch-progress', { title_id: await titleId(page, 'Open Film'), position_seconds: 5, duration_seconds: 100 }, pid)
    const entry = (await (await api(page, 'GET', '/watch-progress?history=true', undefined, pid)).json())[0]
    const ctx = await browser.newContext()
    const p2 = await ctx.newPage()
    await member(p2, 'f09other')
    expect((await api(p2, 'DELETE', `/watch-progress/${entry.id}`, undefined, await profileId(p2))).status()).toBe(404)
    await ctx.close()
    g.check()
  })
})

test.describe('F10 remind me', () => {
  test('F10-H1 Remind me on a coming-soon title sets, persists and clears', async ({ page }) => {
    const g = guard(page)
    await member(page, 'f10')
    await page.goto('/latest')
    const item = page.getByRole('listitem').filter({ hasText: 'Coming Soon Film' })
    await item.getByRole('button', { name: 'Remind me' }).click()
    await expect(item.getByRole('button', { name: 'Reminder set' })).toBeVisible()
    await page.reload()
    await expect(page.getByRole('listitem').filter({ hasText: 'Coming Soon Film' }).getByRole('button', { name: 'Reminder set' })).toBeVisible()
    await page.getByRole('listitem').filter({ hasText: 'Coming Soon Film' }).getByRole('button', { name: 'Reminder set' }).click()
    await expect(page.getByRole('listitem').filter({ hasText: 'Coming Soon Film' }).getByRole('button', { name: 'Remind me' })).toBeVisible()
    g.check()
  })

  test('F10-E1 a title that is already out cannot be reminded about', async ({ page }) => {
    const g = guard(page, { allow: [/409/] })
    await member(page, 'f10out')
    const r = await api(page, 'PUT', `/reminders/${await titleId(page, 'Open Film')}`, undefined, await profileId(page))
    expect(r.status()).toBe(409)
    g.check()
  })

  test('F10-E2 the bell is empty for a new profile and says what to do', async ({ page }) => {
    await member(page, 'f10bell')
    await page.getByRole('button', { name: /^Notifications/ }).click()
    await expect(page.getByText(/use .remind me. on a coming-soon title/i)).toBeVisible()
  })
})

test.describe('F11 account, devices, deletion', () => {
  test('F11-H1 devices list shows two sign-ins; signing the other out ends its session', async ({ page, browser }) => {
    const g = guard(page)
    const email = await member(page, 'f11')
    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    await signIn(other, email)
    await expect(other.getByRole('heading', { name: /who.s watching/i })).toBeVisible()
    await page.goto('/account')
    const rows = page.locator('#devices-h ~ ul li')
    await expect(rows).toHaveCount(2)
    await expect(page.getByText('This device')).toBeVisible()
    await page.getByRole('button', { name: /^Sign out Chrome/ }).click()
    await expect(rows).toHaveCount(1)
    expect((await other.request.get('/api/v1/auth/me')).status()).toBe(401)
    await ctx.close()
    g.check()
  })

  test('F11-N1 deleting the account needs the right password', async ({ page }) => {
    const g = guard(page, { allow: [/403/] })
    await member(page, 'f11bad')
    await page.goto('/account')
    await page.getByRole('button', { name: /Delete my account/ }).click()
    page.once('dialog', (d) => d.accept())
    await page.getByLabel('Your password, to confirm').fill('not the password')
    await page.getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page.getByRole('alert')).toContainText(/not correct/i)
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(200)
    g.check()
  })

  test('F11-H2 deleting the account signs out, and the same login no longer works', async ({ page }) => {
    const g = guard(page, { allow: [/401/] })
    const email = await member(page, 'f11del')
    await page.goto('/account')
    await page.getByRole('button', { name: /Delete my account/ }).click()
    page.once('dialog', (d) => d.accept())
    await page.getByLabel('Your password, to confirm').fill(PASSWORD)
    await page.getByRole('button', { name: 'Delete permanently' }).click()
    await expect(page).toHaveURL(/localhost:5174\/$/)
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401)
    const r = await page.request.post('/api/v1/auth/login', { data: { email, password: PASSWORD } })
    expect(r.status()).toBe(401)
    g.check()
  })

  test('F11-A1 account page has no accessibility violations', async ({ page }) => {
    await member(page, 'f11a11y')
    await page.goto('/account')
    await page.waitForLoadState('networkidle')
    await noAxeViolations(page)
  })
})

test.describe('F12 admin', () => {
  test('F12-E1 a normal member is sent away from the admin dashboard and the admin API is closed to them', async ({ page }) => {
    const g = guard(page, { allow: [/403/] })
    await member(page, 'f12')
    await page.goto('/admin')
    await expect(page).not.toHaveURL(/admin/)
    expect((await api(page, 'GET', '/admin/titles')).status()).toBe(403)
    g.check()
  })

  test('F12-H1 the administrator can open the dashboard and sees the seeded titles', async ({ page }) => {
    const g = guard(page)
    await signIn(page, 'admin@example.com')
    await page.getByRole('button', { name: /Admin/ }).first().click()
    await page.goto('/admin')
    await expect(page.getByRole('heading', { name: 'Admin dashboard' })).toBeVisible()
    await expect(page.getByText('Open Film').first()).toBeVisible()
    await noAxeViolations(page)
    g.check()
  })
})

void uniqueEmail
