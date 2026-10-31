import { test, expect } from '@playwright/test'
import { episodeIds, guard, member, noAxeViolations, signIn, titleId } from './helpers'

test.describe('F13 report a playback problem', () => {
  test('F13-H1 a viewer reports a problem from the player; an admin sees it and resolves it', async ({ page, browser }) => {
    const g = guard(page, { allow: [/cdn\.example\.com/, /ERR_NAME_NOT_RESOLVED/, /Failed to load resource/] })
    await member(page, 'f13')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    await page.goto(`/watch/${id}?episode=${eps[1]}`)
    await expect(page.locator('video')).toBeVisible()

    await page.getByRole('button', { name: 'Report a problem' }).click()
    const dialog = page.getByRole('dialog', { name: /report a problem/i })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Send report' })).toBeDisabled() // a kind is required
    await noAxeViolations(page)

    await dialog.getByLabel('No sound').check()
    await dialog.getByLabel(/anything to add/i).fill('Silent after the opening scene')
    await page.keyboard.type(' ')                  // typing in the note must not toggle the video
    await dialog.getByRole('button', { name: 'Send report' }).click()
    await expect(dialog.getByRole('status')).toContainText(/report was sent/i)
    await dialog.getByRole('button', { name: 'Back to the video' }).click()
    await expect(dialog).toBeHidden()

    // an administrator sees it
    const ctx = await browser.newContext()
    const adminPage = await ctx.newPage()
    await signIn(adminPage, 'admin@example.com')
    await adminPage.waitForURL((u) => !u.pathname.startsWith('/login'))
    if (adminPage.url().includes('/profiles')) await adminPage.getByRole('button', { name: /^Admin$/ }).click()
    await expect(adminPage.getByRole('button', { name: /^Notifications/ })).toBeVisible()
    await adminPage.goto('/admin')
    await adminPage.getByRole('tab', { name: 'Playback reports' }).click()
    const row = adminPage.locator('.card', { hasText: 'Silent after the opening scene' })
    await expect(row).toContainText('Serial')
    await expect(row).toContainText('S1E2')
    await expect(row).toContainText('No sound')
    await row.getByRole('button', { name: /resolved/i }).click()
    await expect(adminPage.getByText('No reports here.')).toBeVisible()
    await ctx.close()
    g.check()
  })

  test('F13-E1 Escape closes the dialog without sending anything', async ({ page }) => {
    await member(page, 'f13e')
    const id = await titleId(page, 'Serial')
    const eps = await episodeIds(page, id)
    await page.goto(`/watch/${id}?episode=${eps[0]}`)
    await page.getByRole('button', { name: 'Report a problem' }).click()
    await expect(page.getByRole('dialog', { name: /report a problem/i })).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByRole('dialog', { name: /report a problem/i })).toBeHidden()
  })
})
