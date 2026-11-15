import { test, expect, type Page, type Route } from '@playwright/test';

// Offline UI contracts only: no model-quality claims and no database seeding.
// Run with EVAL_MOCKS=0 against Vite configured with synthetic Supabase/API values.
test.use({
  storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? {
    launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE },
  } : {}),
});

const sessionId = 'offline-chat-session';
const user = {
  id: '00000000-0000-4000-8000-000000000001',
  email: 'chat-ui@example.test', aud: 'authenticated', role: 'authenticated',
  app_metadata: {}, user_metadata: {}, created_at: '2026-01-01T00:00:00Z',
};
const jwtPart = (value: unknown) => Buffer.from(JSON.stringify(value)).toString('base64url');
const token = `${jwtPart({ alg: 'HS256', typ: 'JWT' })}.${jwtPart({ sub: user.id, exp: 4102444800 })}.fake-signature`;

function sse(...events: Record<string, unknown>[]) {
  return events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('');
}

async function respond(route: Route, ...events: Record<string, unknown>[]) {
  await route.fulfill({ contentType: 'text/event-stream', body: sse(...events) });
}

async function openOfflineAdvisor(page: Page) {
  // Only frontend documents/assets may reach a server. Every fetch/XHR is
  // intercepted, including unexpected mutations and auth refresh requests.
  await page.route('**/*', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === '/auth/v1/token') {
      await route.fulfill({ json: {
        access_token: token, refresh_token: 'offline-refresh-token',
        token_type: 'bearer', expires_in: 3600, user,
      } });
    } else if (path === '/auth/v1/user') {
      await route.fulfill({ json: user });
    } else if (['fetch', 'xhr'].includes(request.resourceType())) {
      const fixtures: Record<string, unknown> = {
        '/finance/accounts': [], '/finance/goals': [],
        '/profile': { id: user.id }, '/profile/memory': null,
      };
      if (request.method() === 'GET' && path in fixtures) {
        await route.fulfill({ json: fixtures[path] });
      } else {
        await route.fulfill({ status: 503, json: { detail: 'Unconfigured offline fixture' } });
      }
    } else if (new URL(request.url()).origin === new URL(page.url()).origin ||
               (request.isNavigationRequest() && ['localhost', '127.0.0.1'].includes(new URL(request.url()).hostname))) {
      await route.continue();
    } else {
      await route.abort('blockedbyclient');
    }
  });
  await page.goto('/login');
  await page.getByLabel('Email', { exact: true }).fill(user.email);
  await page.getByLabel('Password', { exact: true }).fill('offline-only-password');
  await page.getByRole('button', { name: 'Sign In', exact: true }).click();
  await page.getByRole('button', { name: 'Open advisor', exact: true }).click();
  await expect(page.getByPlaceholder('Ask your advisor')).toBeVisible();
}

test('send, render SSE table, and scripted follow-up preserve the session', async ({ page }) => {
  await openOfflineAdvisor(page);
  const requests: unknown[] = [];
  await page.route('**/advisor/chat', async route => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers().authorization).toBe(`Bearer ${token}`);
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      await respond(route,
        { text: 'Your monthly ' }, { text: 'surplus is **$500**.' },
        { displayable_table: {
          title: 'Monthly cash flow', summary: '1 row',
          columns: [{ key: 'label', label: 'Category' }, { key: 'amount', label: 'Amount', format: 'currency' }],
          rows: [{ label: 'Available surplus', amount: 500 }],
        } },
        { done: true, session_id: sessionId, message_id: 'answer-1' });
    } else {
      await respond(route, { text: 'Saving $200 leaves $300 per month.' },
        { done: true, session_id: sessionId, message_id: 'answer-2' });
    }
  });
  const input = page.getByPlaceholder('Ask your advisor');
  await input.fill('How much can I save?');
  await page.getByRole('button', { name: 'Send', exact: true }).click();
  await expect(page.getByText('Your monthly surplus is $500.', { exact: true })).toBeVisible();
  await expect(page.locator('#advisor-panel strong')).toHaveText('$500');
  await expect(input).toHaveValue('');
  await expect(page.getByTestId('table-pill-body')).toHaveCount(0);
  await page.getByTestId('table-pill-toggle').click();
  await expect(page.getByRole('cell', { name: '$500.00', exact: true })).toBeVisible();
  await input.fill('What if I save $200?');
  await input.press('Enter');
  await expect(page.getByText('Saving $200 leaves $300 per month.', { exact: true })).toBeVisible();
  await expect(page.getByText('In conversation', { exact: false })).toContainText('4 messages');
  expect(requests).toEqual([
    { message: 'How much can I save?', session_id: null },
    { message: 'What if I save $200?', session_id: sessionId },
  ]);
});

test('pending response disables composing and recovers when SSE completes', async ({ page }) => {
  await openOfflineAdvisor(page);
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/advisor/chat', async route => {
    await gate;
    await respond(route, { text: 'Ready.' }, { done: true, session_id: sessionId, message_id: 'answer-1' });
  });
  const input = page.getByPlaceholder('Ask your advisor');
  await input.fill('Show my outlook');
  await input.press('Enter');
  try {
    await expect(input).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeVisible();
    await expect(page.getByText('Advisor is responding', { exact: false })).toBeVisible();
  } finally {
    release();
  }
  await expect(page.getByText('Ready.', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toHaveCount(0);
});

test('fragmented SSE bytes render intact text and retain the final session event', async ({ page }) => {
  await openOfflineAdvisor(page);
  const requests: unknown[] = [];
  await page.route('**/advisor/chat', async route => {
    requests.push(route.request().postDataJSON());
    await route.fulfill({ contentType: 'text/event-stream', body:
      sse({ text: 'Saved \u00a5 and \u7b97.' }) +
      `data: ${JSON.stringify({ done: true, session_id: sessionId, message_id: `fragment-${requests.length}` })}`,
    });
  });
  // Route fulfillment buffers the body. Rechunk that mocked response inside
  // the browser so the actual ChatPanel reader receives one byte per read.
  await page.evaluate(() => {
    const originalFetch = window.fetch.bind(window);
    window.fetch = async (...args) => {
      const response = await originalFetch(...args);
      if (!String(args[0]).endsWith('/advisor/chat')) return response;
      const bytes = new Uint8Array(await response.arrayBuffer());
      let index = 0;
      return new Response(new ReadableStream({
        pull(controller) {
          if (index === bytes.length) controller.close();
          else controller.enqueue(bytes.slice(index, ++index));
        },
      }), { headers: response.headers, status: response.status });
    };
  });
  const input = page.getByPlaceholder('Ask your advisor');
  await input.fill('First question');
  await input.press('Enter');
  await expect(page.getByText('Saved \u00a5 and \u7b97.', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  await input.fill('Follow up');
  await input.press('Enter');
  await expect(page.getByText('In conversation', { exact: false })).toContainText('4 messages');
  expect(requests).toEqual([
    { message: 'First question', session_id: null },
    { message: 'Follow up', session_id: sessionId },
  ]);
});

test('provider HTTP failure is visible and retry resends the user prompt', async ({ page }) => {
  await openOfflineAdvisor(page);
  const requests: unknown[] = [];
  await page.route('**/advisor/chat', async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) {
      await route.fulfill({ status: 503, json: { detail: 'Provider temporarily unavailable' } });
    } else {
      await respond(route, { text: 'Your outlook is ready.' },
        { done: true, session_id: sessionId, message_id: 'answer-retry' });
    }
  });
  const input = page.getByPlaceholder('Ask your advisor');
  await input.fill('Show my outlook');
  await input.press('Enter');
  await expect(page.getByText('Error: request failed. Please try again.', { exact: true })).toBeVisible();
  await expect(input).toBeEnabled();
  const retry = page.getByRole('complementary', { name: 'Financial advisor' }).getByRole('button', { name: 'Retry', exact: true });
  await retry.click();
  await expect(page.getByText('Your outlook is ready.', { exact: true })).toBeVisible();
  await expect(retry).toHaveCount(0);
  expect(requests).toEqual([
    { message: 'Show my outlook', session_id: null },
    { message: 'Show my outlook', session_id: null },
  ]);
});
