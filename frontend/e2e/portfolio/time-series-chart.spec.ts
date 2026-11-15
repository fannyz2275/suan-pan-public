// Spec A §3.2 — PortfolioTimeSeriesChart
import { test, expect } from '@playwright/test';

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.waitForURL(/\/$/);
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
}

test.describe('PortfolioTimeSeriesChart', () => {
  test('happy path: chart container renders with timeseries-chart testid', async ({ page }) => {
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="timeseries-chart"]')).toBeVisible();
  });

  test('happy path: fires GET /portfolio/timeseries with date params on mount', async ({ page }) => {
    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/timeseries') && req.method() === 'GET',
    );
    await goToPortfolio(page);
    const req = await reqPromise;
    const url = new URL(req.url());
    expect(url.searchParams.get('from_date')).toBeTruthy();
    expect(url.searchParams.get('to_date')).toBeTruthy();
  });

  test('window buttons render for each window key', async ({ page }) => {
    await goToPortfolio(page);
    // Each window button must be present: 1M, 3M, 6M, YTD, 1Y, All
    for (const w of ['1M', '3M', '6M', 'YTD', '1Y', 'All']) {
      await expect(page.locator(`[data-testid="window-btn-${w}"]`)).toBeVisible();
    }
  });

  test('macro overlay controls are absent', async ({ page }) => {
    await goToPortfolio(page);
    await expect(page.locator('[data-testid^="overlay-"]')).toHaveCount(0);
  });

  test('clicking 1M window button fires new timeseries request with scoped from_date', async ({ page }) => {
    await goToPortfolio(page);
    // Drain the initial fetch first.
    await page.waitForRequest((req) => req.url().includes('/portfolio/timeseries'));

    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/timeseries') && req.method() === 'GET',
    );
    await page.click('[data-testid="window-btn-1M"]');
    const req = await reqPromise;
    const url = new URL(req.url());
    const fromDate = url.searchParams.get('from_date');
    expect(fromDate).toBeTruthy();
    // from_date should be within 32 days of today.
    const from = new Date(fromDate!);
    const diff = (Date.now() - from.getTime()) / (1000 * 60 * 60 * 24);
    expect(diff).toBeLessThan(32);
  });

  test('timeseries request does not request macro overlays', async ({ page }) => {
    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/timeseries') && req.method() === 'GET',
    );
    await goToPortfolio(page);
    const req = await reqPromise;
    const url = new URL(req.url());
    expect(url.searchParams.has('overlays')).toBe(false);
  });

  test('empty state: "No snapshots" message renders when series is empty', async ({ page }) => {
    await page.route('**/portfolio/timeseries**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ series: [], overlays: [] }),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('text=No snapshots in this window')).toBeVisible();
  });

  test('error state: 500 from timeseries — no crash, chart area still renders', async ({ page }) => {
    await page.route('**/portfolio/timeseries**', async (route) => {
      await route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="timeseries-chart"]')).toBeVisible();
    expect(errors).toHaveLength(0);
  });
});
