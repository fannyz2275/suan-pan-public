import { execSync } from 'child_process';
import { chromium } from '@playwright/test';

export default async function globalSetup() {
  // 1. Verify backend is running in eval mode.
  let health: { eval_mocks?: boolean } = {};
  try {
    const res = await fetch('http://localhost:8000/eval/health');
    if (!res.ok) {
      throw new Error(`/eval/health returned HTTP ${res.status}`);
    }
    health = await res.json();
  } catch (err) {
    throw new Error(
      `Backend not reachable at http://localhost:8000/eval/health — ` +
      `start with: EVAL_MOCKS=1 uvicorn app.main:app --port 8000\n${err}`,
    );
  }
  if (!health.eval_mocks) {
    throw new Error(
      'Backend is not in eval mode (eval_mocks=false). ' +
      'Set EVAL_MOCKS=1 before starting uvicorn.',
    );
  }

  // 2. Seed the DB with the primary fixture.
  execSync(
    'python -m backend.tests.evals.shared.seed_runner --fixture single_brokerage',
    { stdio: 'inherit', cwd: process.cwd() },
  );

  // 3. Login once and persist auth state for all tests.
  const email = process.env.TEST_EMAIL ?? 'eval-a@test.local';
  const password = process.env.TEST_PASSWORD ?? 'eval-a-pw';

  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto(process.env.PLAYWRIGHT_BASE ?? 'http://localhost:5173');

  // Fill Supabase auth form.
  await page.getByPlaceholder(/email/i).fill(email);
  await page.getByPlaceholder(/password/i).fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL(/dashboard/);

  await page.context().storageState({ path: 'e2e/.auth.json' });
  await browser.close();
}
