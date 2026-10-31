import { test, expect } from '@playwright/test'
import { guard, member, noAxeViolations, PASSWORD, signIn } from './helpers'

const NEW = 'a brand new passphrase'

test.describe('F14 account: profiles and password', () => {
  test('F14-H1 the account page lists profiles; changing the password signs other devices out and keeps this one', async ({ page, browser }) => {
    const g = guard(page, { allow: [/401/] })
    const email = await member(page, 'f14')
    const ctx = await browser.newContext()
    const other = await ctx.newPage()
    await signIn(other, email)
    await other.waitForURL((u) => !u.pathname.startsWith('/login'))

    await page.goto('/account')
    const profiles = page.getByRole('region', { name: 'Profiles' })
    await expect(profiles.getByText('Me')).toBeVisible()
    await expect(profiles.getByRole('link', { name: 'Manage profiles' })).toBeVisible()
    await noAxeViolations(page)

    const form = page.getByRole('region', { name: 'Password' })
    const save = form.getByRole('button', { name: 'Change password' })
    await form.getByLabel('Current password').fill(PASSWORD)
    await form.getByLabel(/^New password(?! again)/).fill(NEW)
    await form.getByLabel('New password again').fill(NEW + 'x')
    await expect(form.getByText(/two new passwords are different/i)).toBeVisible()
    await expect(save).toBeDisabled()
    await form.getByLabel('New password again').fill(NEW)
    await save.click()
    await expect(form.getByRole('status')).toContainText(/password updated/i)
    await page.reload()
    await expect(page.getByRole('region', { name: 'Password' })).toBeVisible() // still signed in here

    const me = await other.request.get('/api/v1/auth/me')
    expect(me.status()).toBe(401) // the other device was signed out
    await ctx.close()
    g.check()
  })

  test('F14-N1 a wrong current password is refused and nothing changes', async ({ page }) => {
    const g = guard(page, { allow: [/403/] })
    await member(page, 'f14n')
    await page.goto('/account')
    const form = page.getByRole('region', { name: 'Password' })
    await form.getByLabel('Current password').fill('not the password')
    await form.getByLabel(/^New password(?! again)/).fill(NEW)
    await form.getByLabel('New password again').fill(NEW)
    await form.getByRole('button', { name: 'Change password' }).click()
    await expect(form.getByRole('alert')).toContainText(/not correct/i)
    g.check()
  })
})
