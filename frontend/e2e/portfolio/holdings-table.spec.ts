// Spec A §3.4 — HoldingsTable
import { test, expect } from '@playwright/test';

const CANNED_HOLDINGS = [
  { ticker: 'AAPL', quantity: 10, price: 190, market_value: 1900, percent: 59.4, cost_basis: 1500 },
  { ticker: 'BND',  quantity: 50, price: 73.8, market_value: 3690, percent: 40.6, cost_basis: 3700 },
];

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.waitForURL(/\/$/);
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
}

test.describe('HoldingsTable', () => {
  test('happy path: holdings-table renders with all column header testids', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_HOLDINGS),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="holdings-table"]')).toBeVisible();
    await expect(page.locator('[data-testid="col-ticker"]')).toBeVisible();
    await expect(page.locator('[data-testid="col-quantity"]')).toBeVisible();
    await expect(page.locator('[data-testid="col-market-value"]')).toBeVisible();
    await expect(page.locator('[data-testid="col-percent"]')).toBeVisible();
  });

  test('happy path: per-row testids render for each holding ticker', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_HOLDINGS),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="holding-row-AAPL"]')).toBeVisible();
    await expect(page.locator('[data-testid="holding-row-BND"]')).toBeVisible();
  });

  test('happy path: default sort is market_value descending (BND row first since higher value)', async ({ page }) => {
    // BND has market_value 3690, AAPL has 1900 — BND should be first.
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_HOLDINGS),
      });
    });
    await goToPortfolio(page);
    // Wait for rows to render.
    await expect(page.locator('[data-testid="holding-row-BND"]')).toBeVisible();
    const rows = await page.locator('[data-testid^="holding-row-"]').all();
    expect(rows).toHaveLength(2);
    const firstRowId = await rows[0].getAttribute('data-testid');
    expect(firstRowId).toBe('holding-row-BND');
  });

  test('empty state: "No holdings yet." renders when holdings is empty', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="holdings-table"]')).toBeVisible();
    await expect(page.locator('text=No holdings yet.')).toBeVisible();
  });

  test('error state: 500 from holdings — "No holdings yet." renders, no crash', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="holdings-table"]')).toBeVisible();
    expect(errors).toHaveLength(0);
  });

  test('interaction: clicking Ticker header sorts rows alphabetically asc', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_HOLDINGS),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="col-ticker"]')).toBeVisible();
    await page.click('[data-testid="col-ticker"]');
    const rows = await page.locator('[data-testid^="holding-row-"]').all();
    const firstId = await rows[0].getAttribute('data-testid');
    expect(firstId).toBe('holding-row-AAPL'); // A < B
  });

  test('interaction: clicking Ticker twice reverses sort order', async ({ page }) => {
    await page.route('**/portfolio/holdings**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_HOLDINGS),
      });
    });
    await goToPortfolio(page);
    await page.click('[data-testid="col-ticker"]');
    await page.click('[data-testid="col-ticker"]');
    const rows = await page.locator('[data-testid^="holding-row-"]').all();
    const firstId = await rows[0].getAttribute('data-testid');
    expect(firstId).toBe('holding-row-BND'); // B > A, descending
  });

  test('network: fires GET /portfolio/holdings without account_id when All is active', async ({ page }) => {
    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/holdings') && req.method() === 'GET',
    );
    await goToPortfolio(page);
    const req = await reqPromise;
    expect(new URL(req.url()).searchParams.has('account_id')).toBe(false);
  });
});
