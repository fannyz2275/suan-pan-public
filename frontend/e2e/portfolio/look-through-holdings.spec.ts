import { test, expect } from '@playwright/test';

async function goToPortfolio(page: import('@playwright/test').Page) {
  await page.goto('/dashboard');
  await page.click('[data-testid="tab-wealth"]');
  await page.click('[data-testid="tab-portfolio"]');
  await expect(page.getByTestId('portfolio-page')).toBeVisible();
}

test('look-through holdings render underlying exposure', async ({ page }) => {
  await page.route('**/portfolio/lookthrough**', route => route.fulfill({
    json: [{ ticker: 'AAPL', name: 'Apple', sector: 'Technology', country: 'United States', market_value: 500, percent: 5, via: ['VTI'] }],
  }));
  await goToPortfolio(page);
  const table = page.getByTestId('lookthrough-table');
  await expect(table.getByText('AAPL', { exact: true })).toBeVisible();
  await expect(table.getByText('$500', { exact: true })).toBeVisible();
  await expect(table.getByText('VTI', { exact: true })).toBeVisible();
});

test('look-through empty response shows empty state', async ({ page }) => {
  await page.route('**/portfolio/lookthrough**', route => route.fulfill({ json: [] }));
  await goToPortfolio(page);
  await expect(page.getByText(/No look-through data yet/)).toBeVisible();
});

test('look-through failure is visible without crashing the page', async ({ page }) => {
  await page.route('**/portfolio/lookthrough**', route => route.fulfill({ status: 500, json: { detail: 'error' } }));
  await goToPortfolio(page);
  await expect(page.getByText('Could not load look-through holdings.')).toBeVisible();
});
