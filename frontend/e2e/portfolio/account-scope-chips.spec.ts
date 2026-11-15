// Spec A §3.1 — AccountScopeChips
import { test, expect } from '@playwright/test';

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.waitForURL(/\/$/);
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
}

test.describe('AccountScopeChips', () => {
  test('happy path: "All investments" chip renders and is initially active', async ({ page }) => {
    await goToPortfolio(page);
    const allChip = page.locator('[data-testid="scope-chip-all"]');
    await expect(allChip).toBeVisible();
    await expect(allChip).toHaveAttribute('aria-pressed', 'true');
  });

  test('happy path: per-account chips render for seeded brokerage account', async ({ page }) => {
    await goToPortfolio(page);
    // Wait for the GET /finance/accounts fetch to complete and render chips.
    await page.waitForRequest(
      (req) => req.url().includes('/finance/accounts') && req.method() === 'GET',
    );
    // Per-account chip should appear: data-testid="scope-chip-acc-brok-1"
    await expect(page.locator('[data-testid^="scope-chip-acc-"]')).toHaveCount(1);
  });

  test('empty state: only "All investments" chip if no brokerage accounts', async ({ page }) => {
    // Intercept the accounts endpoint to return only non-brokerage accounts.
    await page.route('**/finance/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([{ id: 'acc-checking', name: 'Checking', type: 'checking' }]),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="scope-chip-all"]')).toBeVisible();
    await expect(page.locator('[data-testid^="scope-chip-acc-"]')).toHaveCount(0);
  });

  test('error state: 500 from /finance/accounts — All chip still renders, no crash', async ({ page }) => {
    await page.route('**/finance/accounts', async (route) => {
      await route.fulfill({ status: 500, body: '{"detail":"server error"}' });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="scope-chip-all"]')).toBeVisible();
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    expect(errors).toHaveLength(0);
  });

  test('interaction: clicking a per-account chip deactivates "All investments"', async ({ page }) => {
    await page.route('**/finance/accounts', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'acc-brok-1', name: 'Fidelity Brokerage', type: 'brokerage' },
        ]),
      });
    });
    await goToPortfolio(page);
    const acctChip = page.locator('[data-testid="scope-chip-acc-brok-1"]');
    await expect(acctChip).toBeVisible();
    await acctChip.click();
    await expect(acctChip).toHaveAttribute('aria-pressed', 'true');
    await expect(page.locator('[data-testid="scope-chip-all"]')).toHaveAttribute('aria-pressed', 'false');
  });
});
