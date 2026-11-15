// Spec A §3.10 — Dashboard Portfolio tab
import { test, expect } from '@playwright/test';

test.describe('Dashboard tab bar', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/dashboard');
    await page.waitForURL(/\/$/);
  });

  test('all four tab testids are present', async ({ page }) => {
    await expect(page.locator('[data-testid="tab-overview"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-spending"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-wealth"]')).toBeVisible();
    await expect(page.locator('[data-testid="tab-plan"]')).toBeVisible();
  });

  test('Portfolio tab click mounts PortfolioPage', async ({ page }) => {
    await page.click('[data-testid="tab-wealth"]');
    await page.click('[data-testid="tab-portfolio"]');
    await expect(page.locator('[data-testid="portfolio-page"]')).toBeVisible();
  });

  test('active Portfolio tab has border-primary class', async ({ page }) => {
    await page.click('[data-testid="tab-wealth"]');
    await page.click('[data-testid="tab-portfolio"]');
    await expect(page.locator('[data-testid="tab-portfolio"]')).toHaveClass(/border-primary/);
  });

  test('inactive tabs do not have border-primary', async ({ page }) => {
    await page.click('[data-testid="tab-wealth"]');
    await page.click('[data-testid="tab-portfolio"]');
    await expect(page.locator('[data-testid="tab-overview"]')).not.toHaveClass(/border-primary/);
  });

  test('Portfolio tab click fires GET /finance/accounts (AccountScopeChips mount)', async ({ page }) => {
    await page.click('[data-testid="tab-wealth"]');
    const reqPromise = page.waitForRequest(
      (req) => req.url().includes('/finance/accounts') && req.method() === 'GET',
    );
    await page.click('[data-testid="tab-portfolio"]');
    const req = await reqPromise;
    expect(req.url()).toContain('/finance/accounts');
  });
});
