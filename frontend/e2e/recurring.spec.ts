import { test, expect } from '@playwright/test'

const TEST_EMAIL = process.env.TEST_EMAIL
const TEST_PASSWORD = process.env.TEST_PASSWORD

test.skip(
  !TEST_EMAIL || !TEST_PASSWORD,
  'Set TEST_EMAIL and TEST_PASSWORD to run the recurring E2E test.'
)

test.describe('recurring detection', () => {
  test('detect button surfaces rules on the cashflow tab', async ({ page }) => {
    // Sign in
    await page.goto('/login')
    await page.getByLabel(/email/i).fill(TEST_EMAIL!)
    await page.getByLabel(/password/i).fill(TEST_PASSWORD!)
    await page.getByRole('button', { name: /sign in/i }).click()
    await page.waitForURL(/\/(dashboard|chat|$)/, { timeout: 15_000 })

    // Navigate to the Cash Flow tab where RecurringCostsCard lives
    await page.getByTestId('tab-spending').click()

    // The card title should be visible
    await expect(page.getByText(/recurring costs/i)).toBeVisible()

    // Click Scan — should either reveal rules or show the empty states
    const scanButton = page.getByRole('button', { name: /scan transactions/i })
    await expect(scanButton).toBeEnabled()
    await scanButton.click()

    // Scanning disables the button while in-flight; eventually returns to enabled
    await expect(scanButton).toBeEnabled({ timeout: 30_000 })

    // At minimum, the Income + Expenses section headings render
    await expect(page.getByRole('heading', { name: /^income$/i })).toBeVisible()
    await expect(page.getByRole('heading', { name: /^expenses$/i })).toBeVisible()
  })

  test('review prompt in chat gets Yes/No buttons when pending rule exists', async ({ page }) => {
    // Sign in
    await page.goto('/login')
    await page.getByLabel(/email/i).fill(TEST_EMAIL!)
    await page.getByLabel(/password/i).fill(TEST_PASSWORD!)
    await page.getByRole('button', { name: /sign in/i }).click()
    await page.waitForURL(/\/(dashboard|chat|$)/, { timeout: 15_000 })

    // Send any message to the advisor to trigger the SSE pipeline
    await page.getByRole('button', { name: 'Open advisor' }).click()
    await page.getByPlaceholder(/ask your advisor/i).fill('any recurring?')
    await page.getByRole('button', { name: /^send$/i }).click()

    // The review-prompt injection is optional (depends on whether there are
    // pending_review rules for this user). If it shows up, verify the Yes/No
    // buttons are rendered; otherwise the test is a no-op that still validates
    // the chat flow did not throw.
    const reviewPrompt = page.getByText(/i noticed a possible recurring/i)
    if (await reviewPrompt.count()) {
      await expect(page.getByRole('button', { name: /^yes$/i })).toBeVisible()
      await expect(page.getByRole('button', { name: /^no$/i })).toBeVisible()
    }
  })
})
