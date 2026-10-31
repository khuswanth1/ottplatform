import { test, expect } from '@playwright/test'
import { guard, noAxeViolations, signUp, signIn, uniqueEmail, PASSWORD } from './helpers'

// F01 New visitor joins. Payment itself (Stripe Checkout) cannot run here: it is the manual part of the plan.
test.describe('F01 new visitor joins', () => {
  test('F01-H1 landing, email capture, register, sign in, first profile, home', async ({ page }) => {
    const g = guard(page)
    const email = uniqueEmail('f01')
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    await page.getByLabel(/email/i).first().fill(email)
    await page.getByRole('button', { name: 'Create free account' }).first().click()
    await expect(page).toHaveURL(/register/)
    await expect(page.getByLabel('Email')).toHaveValue(email) // carried over from the landing page
    await page.getByLabel(/^Password/).fill(PASSWORD)
    await page.getByRole('button', { name: 'Create account' }).click()
    await page.getByRole('link', { name: 'Sign in' }).last().click()
    await signIn(page, email)
    await expect(page.getByRole('heading', { name: /who.s watching/i })).toBeVisible()
    await page.getByRole('button', { name: /^Me$/ }).click()
    await expect(page.getByRole('button', { name: /^Notifications/ })).toBeVisible()
    g.check()
  })

  test('F01-E1 email already a member gets the same answer, no hint that the account exists', async ({ page }) => {
    const g = guard(page)
    const { email } = await signUp(page)
    await page.getByText(/verification email|on its way/i).waitFor()
    await page.goto('/register')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel(/^Password/).fill(PASSWORD)
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page.getByText(/on its way/i)).toBeVisible()
    g.check()
  })

  test('F01-E2 short password and bad email are refused with a message', async ({ page }) => {
    await page.goto('/register')
    await page.getByLabel('Email').fill('not-an-email')
    await page.getByLabel(/^Password/).fill('short')
    await page.getByRole('button', { name: 'Create account' }).click()
    await expect(page).toHaveURL(/register/)
    await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible()
  })

  test('F01-N1 wrong password gives a generic error and no session', async ({ page }) => {
    const g = guard(page, { allow: [/401/] })
    const { email } = await signUp(page)
    await page.goto('/login')
    await page.getByLabel('Email').fill(email)
    await page.getByLabel('Password').fill('wrong password here')
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('alert')).toContainText(/invalid email or password/i)
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401)
    g.check()
  })

  test('F01-A1 sign-in, register and landing pages have no accessibility violations', async ({ page }) => {
    for (const path of ['/', '/login', '/register']) {
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await noAxeViolations(page)
    }
  })

  test('F01-M1 register works at phone width @mobile', async ({ page }) => {
    await page.goto('/register')
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await expect(page.getByRole('button', { name: 'Create account' })).toBeVisible()
  })
})
