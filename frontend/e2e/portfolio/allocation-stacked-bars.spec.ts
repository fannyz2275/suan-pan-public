// Spec A §3.3 — AllocationStackedBars
import { test, expect } from '@playwright/test';

const CANNED_EXPOSURE = {
  asset_class: [
    { label: 'Equity', percent: 70 },
    { label: 'Fixed Income', percent: 30 },
  ],
  sector: [
    { label: 'Technology', percent: 70 },
    { label: 'N/A', percent: 30 },
  ],
  region: [
    { label: 'US', percent: 100 },
  ],
};

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.waitForURL(/\/$/);
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
}

test.describe('AllocationStackedBars', () => {
  test('happy path: allocation-bars container and bar rows render', async ({ page }) => {
    await page.route('**/portfolio/exposure**', async (route) => {
      const url = new URL(route.request().url());
      const dim = url.searchParams.get('dim') as keyof typeof CANNED_EXPOSURE;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_EXPOSURE[dim] ?? []),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="allocation-bars"]')).toBeVisible();
    await expect(page.locator('[data-testid="bar-asset_class"]')).toBeVisible();
    await expect(page.locator('[data-testid="bar-sector"]')).toBeVisible();
    await expect(page.locator('[data-testid="bar-region"]')).toBeVisible();
  });

  test('happy path: fires three parallel GET /portfolio/exposure requests on mount', async ({ page }) => {
    const dims = new Set<string>();
    page.on('request', (req) => {
      if (req.url().includes('/portfolio/exposure')) {
        const dim = new URL(req.url()).searchParams.get('dim');
        if (dim) dims.add(dim);
      }
    });
    await goToPortfolio(page);
    await page.waitForTimeout(500); // allow parallel fetches to complete
    expect(dims.has('asset_class')).toBe(true);
    expect(dims.has('sector')).toBe(true);
    expect(dims.has('region')).toBe(true);
  });

  test('empty state: all exposures return [] — component returns null, allocation-bars absent', async ({ page }) => {
    await page.route('**/portfolio/exposure**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      });
    });
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="allocation-bars"]')).toHaveCount(0);
  });

  test('error state: 500 from exposure — component returns null, no crash', async ({ page }) => {
    await page.route('**/portfolio/exposure**', async (route) => {
      await route.fulfill({ status: 500, body: '{"detail":"error"}' });
    });
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await goToPortfolio(page);
    await expect(page.locator('[data-testid="allocation-bars"]')).toHaveCount(0);
    expect(errors).toHaveLength(0);
  });

  // TG-13: segment-click → HoldingsTable filter is not yet wired.
  // HoldingsTable does not accept filterDim/filterLabel props; the onSelect
  // callback from PortfolioPage reaches AllocationStackedBars but doesn't
  // propagate to a GET /portfolio/holdings?dim=...&label=... request.
  test.skip('interaction: clicking bar segment filters HoldingsTable (TG-13 — blocked)', async ({ page }) => {
    await page.route('**/portfolio/exposure**', async (route) => {
      const url = new URL(route.request().url());
      const dim = url.searchParams.get('dim') as keyof typeof CANNED_EXPOSURE;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(CANNED_EXPOSURE[dim] ?? []),
      });
    });
    await goToPortfolio(page);
    // Click a segment in the sector bar.
    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/portfolio/holdings') && req.url().includes('dim=sector'),
    );
    await page.locator('[data-testid="bar-sector"] [role="button"]').first().click();
    await reqPromise;
  });
});
