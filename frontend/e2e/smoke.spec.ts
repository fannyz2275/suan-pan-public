import { test, expect } from "@playwright/test";

const TEST_EMAIL = process.env.TEST_EMAIL;
const TEST_PASSWORD = process.env.TEST_PASSWORD;

test.skip(
  !TEST_EMAIL || !TEST_PASSWORD,
  "Set TEST_EMAIL and TEST_PASSWORD to run the smoke test."
);

test("profile edit round-trip", async ({ page }) => {
  await page.goto("/login");

  await page.getByLabel(/email/i).fill(TEST_EMAIL!);
  await page.getByLabel(/password/i).fill(TEST_PASSWORD!);
  await page.getByRole("button", { name: /sign in/i }).click();

  await page.waitForURL(/\/(dashboard|chat|$)/, { timeout: 15_000 });

  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();

  // Edit the profile region and verify it persists.
  const newValue = `Smoke ${Date.now()}`;
  const firstEditable = page.getByLabel("Region", { exact: true });
  await firstEditable.fill(newValue);
  await page.getByRole("button", { name: /save/i }).first().click();

  // Reload to confirm persistence
  await page.reload();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await page.getByRole("button", { name: "Edit profile", exact: true }).click();
  await expect(firstEditable).toHaveValue(newValue);
});
