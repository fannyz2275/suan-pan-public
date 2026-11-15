// Spec A §3.8, §3.9 — PortfolioPage Import + Sync Plaid buttons
import { test, expect } from '@playwright/test';

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.waitForURL(/\/$/);
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
}

test.describe('PortfolioPage — Import statement button (§3.8)', () => {
  test('btn-import-statement is visible with correct text', async ({ page }) => {
    await goToPortfolio(page);
    const btn = page.locator('[data-testid="btn-import-statement"]');
    await expect(btn).toBeVisible();
    await expect(btn).toContainText('Import statement');
  });

  test('clicking Import statement button opens UnifiedImportModal', async ({ page }) => {
    await goToPortfolio(page);
    await page.click('[data-testid="btn-import-statement"]');
    await expect(page.locator('[data-testid="unified-import-modal"]')).toBeVisible();
  });

  test('no import network call fires when Import button is clicked', async ({ page }) => {
    const unwantedRequests: string[] = [];
    page.on('request', (req) => {
      if (
        req.method() === 'POST'
        && (req.url().includes('/import/statements') || req.url().includes('/portfolio/import'))
      ) {
        unwantedRequests.push(req.url());
      }
    });
    await goToPortfolio(page);
    await page.click('[data-testid="btn-import-statement"]');
    await page.waitForTimeout(200);
    expect(unwantedRequests).toHaveLength(0);
  });
});

test.describe('PortfolioPage — Sync Plaid button (§3.9)', () => {
  test('btn-sync-plaid is visible with correct text', async ({ page }) => {
    await goToPortfolio(page);
    const btn = page.locator('[data-testid="btn-sync-plaid"]');
    await expect(btn).toBeVisible();
    await expect(btn).toContainText('Sync Plaid');
  });

  test('happy path: clicking Sync fires POST /portfolio/sync/plaid and shows success msg', async ({ page }) => {
    await page.route('**/portfolio/sync/plaid', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ snapshots_written: 1 }),
      });
    });
    await goToPortfolio(page);

    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/sync/plaid') && req.method() === 'POST',
    );
    await page.click('[data-testid="btn-sync-plaid"]');
    await reqPromise;

    await expect(page.locator('[data-testid="sync-status-msg"]')).toBeVisible();
    await expect(page.locator('[data-testid="sync-status-msg"]')).toContainText('snapshot');
  });

  test('disabled state: button shows "Syncing…" and is disabled during in-flight request', async ({ page }) => {
    // Use a slow mock to observe the loading state.
    await page.route('**/portfolio/sync/plaid', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ snapshots_written: 1 }),
      });
    });
    await goToPortfolio(page);
    await page.click('[data-testid="btn-sync-plaid"]');
    const btn = page.locator('[data-testid="btn-sync-plaid"]');
    await expect(btn).toBeDisabled();
    await expect(btn).toContainText('Syncing');
  });

  test('error state: 500 from sync/plaid shows failure message', async ({ page }) => {
    await page.route('**/portfolio/sync/plaid', async (route) => {
      await route.fulfill({ status: 500, body: '{"detail":"plaid error"}' });
    });
    await goToPortfolio(page);
    await page.click('[data-testid="btn-sync-plaid"]');
    await expect(page.locator('[data-testid="sync-status-msg"]')).toBeVisible();
    await expect(page.locator('[data-testid="sync-status-msg"]')).toContainText('failed');
  });

  test('refreshKey bump: successful sync triggers new GET /portfolio/timeseries', async ({ page }) => {
    await page.route('**/portfolio/sync/plaid', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ snapshots_written: 1 }),
      });
    });
    await goToPortfolio(page);
    // Drain the initial timeseries fetch.
    await page.waitForRequest((req) => req.url().includes('/portfolio/timeseries'));

    const newChartReqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/timeseries') && req.method() === 'GET',
    );
    await page.click('[data-testid="btn-sync-plaid"]');
    await newChartReqPromise;
  });
});
