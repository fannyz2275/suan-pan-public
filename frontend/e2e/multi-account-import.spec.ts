import { test, expect, type Page } from '@playwright/test';

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? {
    launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE },
  } : {}),
});
const accounts = [
  { id: 'a', name: 'Checking', type: 'checking', account_number_last4: '1234' },
  { id: 'b', name: 'Savings', type: 'savings', account_number_last4: '5678' },
];
const groups = accounts.map((a, i) => ({ row_id: `section-${i}`, account_id: a.id,
  account_name: 'Example Bank', account_type: a.type, kind: 'bank', error: null,
  source_file: 'combined.txt', detected_last4: a.account_number_last4,
  preview: { balance: 100 + i, statement_date: '2026-10-01', transactions: [
    { date: '2026-10-01', description: `Deposit ${i}`, amount: 100 + i, category: 'income' },
  ] },
}));

async function openImport(page: Page, multi = true) {
  const user = { id: '00000000-0000-4000-8000-000000000001', email: 'import@example.test',
    aud: 'authenticated', role: 'authenticated', app_metadata: {}, user_metadata: {}, created_at: '2026-01-01T00:00:00Z' };
  const part = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url');
  const token = `${part({ alg: 'HS256', typ: 'JWT' })}.${part({ sub: user.id, exp: 4102444800 })}.fake`;
  await page.route('**/*', async route => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === '/auth/v1/token') await route.fulfill({ json: {
      access_token: token, refresh_token: 'fake', token_type: 'bearer', expires_in: 3600, user,
    } });
    else if (path === '/auth/v1/user') await route.fulfill({ json: user });
    else if (['fetch', 'xhr'].includes(req.resourceType())) {
      const data: Record<string, unknown> = { '/finance/accounts': accounts, '/finance/goals': [],
        '/profile': { id: user.id }, '/profile/memory': null };
      await route.fulfill(path in data ? { json: data[path] } : { status: 503, json: { detail: 'Offline fixture' } });
    } else if (['127.0.0.1', 'localhost'].includes(new URL(req.url()).hostname)) await route.continue();
    else await route.abort();
  });
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(user.email);
  await page.getByLabel('Password', { exact: true }).fill('offline-password');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.getByRole('button', { name: '+ Import statements', exact: true }).click();
  if (multi) await page.getByRole('checkbox', { name: 'This file contains multiple accounts' }).check();
}

async function upload(page: Page, name = 'combined.txt') {
  await page.getByTestId('unified-row-files').setInputFiles({
    name, mimeType: 'text/plain', buffer: Buffer.from('Example Bank Checking 1234\nSavings 5678'),
  });
}

test('default flow selects an account and goes directly to preview without detection', async ({ page }) => {
  await openImport(page, false);
  await expect(page.getByRole('checkbox', { name: 'This file contains multiple accounts' })).not.toBeChecked();
  let detectionCalled = false;
  await page.route('**/import/statements/detect', async route => { detectionCalled = true; await route.abort(); });
  await page.route('**/import/statements/preview', async route => {
    expect(route.request().postData()).toContain('"account_id":"a"');
    await route.fulfill({ json: { groups: [groups[0]] } });
  });
  await upload(page);
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
  await page.getByLabel('Destination account').selectOption('a');
  await page.getByRole('button', { name: 'Preview statements' }).click();
  await expect(page.getByTestId('preview-card')).toHaveCount(1);
  await expect(page.getByRole('button', { name: 'Save all' })).toBeEnabled();
  expect(detectionCalled).toBe(false);
  await page.getByRole('button', { name: /Back/ }).click();
  await expect(page.getByLabel('Destination account')).toHaveValue('a');
});

test('combined statement requires two confirmed destinations and saves separate sections', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openImport(page);
  await expect(page.getByTestId('unified-row-account')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Match accounts' })).toBeDisabled();
  await page.route('**/import/statements/detect', route => route.fulfill({ json: { groups } }));
  let saved: { groups: Array<{ account_id: string; destination_confirmed: boolean }> } | undefined;
  await page.route('**/import/statements/confirm', async route => {
    saved = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true, saved: groups.map(g => ({ row_id: g.row_id,
      account_id: g.account_id, transactions_created: 1, error: null })), transfer_candidates_added: 0 } });
  });
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  await expect(page.getByRole('heading', { name: 'Review account matches' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'Confirm this account destination' }).nth(0).check();
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'Confirm this account destination' }).nth(1).check();
  await page.getByRole('button', { name: 'Preview statements' }).click();
  await expect(page.getByTestId('preview-card')).toHaveCount(2);
  await expect(page.getByRole('button', { name: 'Save all' })).toBeInViewport();
  await page.screenshot({ path: '/tmp/suan-pan-multi-account-preview.png' });
  await page.getByRole('button', { name: 'Save all' }).click();
  await expect(page.getByTestId('unified-import-modal')).toHaveCount(0);
  expect(saved?.groups.map(g => g.account_id)).toEqual(['a', 'b']);
  expect(saved?.groups.every(g => g.destination_confirmed)).toBe(true);
});

test('unmatched section blocks preview until a destination is selected', async ({ page }) => {
  await openImport(page);
  await page.route('**/import/statements/detect', route => route.fulfill({ json: { groups: [{ ...groups[0], account_id: '' }] } }));
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  const confirm = page.getByRole('checkbox', { name: 'Confirm this account destination' });
  await expect(confirm).toBeDisabled();
  await page.getByLabel('Destination account').selectOption('a');
  await confirm.check();
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeEnabled();
});

test('unsafe detection keeps upload visible and reports the problem', async ({ page }) => {
  await openImport(page);
  await page.route('**/import/statements/detect', route => route.fulfill({ status: 422,
    json: { detail: 'Could not safely separate every account section.' } }));
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Could not safely separate' })).toBeVisible();
  await expect(page.getByTestId('unified-row-files')).toHaveCount(1);
});

test('invalid file is rejected before any parsing', async ({ page }) => {
  await openImport(page);
  await upload(page, 'statement.docx');
  await expect(page.getByTestId('unified-row-file-error')).toContainText('PDF, CSV, or TXT');
  await expect(page.getByRole('button', { name: 'Match accounts' })).toBeDisabled();
});

test('preserves good sections and requires review of shared and unresolved content', async ({ page }) => {
  await openImport(page);
  await page.route('**/import/statements/detect', route => route.fulfill({ json: { groups: [
    { ...groups[0], document_notices: [{ role: 'disclosure', ranges: [[1, 5]] }] },
    { ...groups[1], account_id: '', preview: null, error_code: 'section_parse', error: 'Could not validate this section.' },
  ] } }));
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  await expect(page.getByText('Needs review', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: 'Confirm this account destination' }).check();
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'Exclude this unresolved section from this import' }).check();
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
  await page.getByRole('checkbox', { name: 'I reviewed the shared content exclusions' }).check();
  await page.getByRole('button', { name: 'Preview statements' }).click();
  await expect(page.getByTestId('preview-card')).toHaveCount(1);
});

test('new destination keeps detected type and last four, then requires confirmation', async ({ page }) => {
  await openImport(page);
  await page.route('**/import/statements/detect', route => route.fulfill({ json: { groups: [{ ...groups[1], account_id: '' }] } }));
  let created: unknown;
  await page.route('**/finance/accounts', async route => {
    if (route.request().method() === 'POST') {
      created = route.request().postDataJSON();
      await route.fulfill({ json: { id: 'new-account', ...(created as object) } });
    } else await route.fulfill({ json: accounts });
  });
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  await page.getByLabel('Destination account').selectOption('__new__');
  await page.getByTestId('unified-new-name').fill('New savings');
  await expect(page.getByTestId('unified-new-type')).toBeDisabled();
  await page.getByRole('button', { name: 'Create account', exact: true }).click();
  await expect(page.getByLabel('Destination account')).toHaveValue('new-account');
  expect(created).toMatchObject({ type: 'savings', account_number_last4: '5678' });
  await expect(page.getByRole('button', { name: 'Preview statements' })).toBeDisabled();
});

test('partial save retains failed sections and does not claim success', async ({ page }) => {
  await openImport(page);
  await page.route('**/import/statements/detect', route => route.fulfill({ json: { groups } }));
  await page.route('**/import/statements/confirm', route => route.fulfill({ json: {
    ok: true, saved: [{ row_id: 'section-0', account_id: 'a', error: null },
      { row_id: 'section-1', account_id: 'b', error: 'Save failed' }], transfer_candidates_added: 0,
  } }));
  await upload(page);
  await page.getByRole('button', { name: 'Match accounts' }).click();
  await page.getByRole('checkbox', { name: 'Confirm this account destination' }).nth(0).check();
  await page.getByRole('checkbox', { name: 'Confirm this account destination' }).nth(1).check();
  await page.getByRole('button', { name: 'Preview statements' }).click();
  await page.getByRole('button', { name: 'Save all' }).click();
  await expect(page.getByTestId('preview-card')).toHaveCount(1);
  await expect(page.getByRole('alert').filter({ hasText: 'Some sections could not be saved' })).toBeVisible();
});
