import { test, expect } from '@playwright/test'

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE } } : {}) })

// Only auth/source data are intercepted. Forecast requests reach the real Python
// service + simulator against synthetic in-memory records, never production data.
const server = process.env.FORECAST_TEST_API || 'http://127.0.0.1:8099'

for (const width of [1280, 390]) {
  test(`wedding, spending and recurring amounts reconcile at ${width}px`, async ({ page, request }) => {
    await request.post(`${server}/reset`)
    const tables = await (await request.get(`${server}/fixture`)).json()
    await page.setViewportSize({ width, height: 1000 })
    const user = { id:'00000000-0000-4000-8000-000000000001', email:'forecast@example.test', aud:'authenticated', role:'authenticated', app_metadata:{}, user_metadata:{}, created_at:'2026-01-01T00:00:00Z' }
    const part = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url')
    const token = `${part({alg:'HS256',typ:'JWT'})}.${part({sub:user.id,exp:4102444800})}.fake`
    const browserErrors: string[] = []
    page.on('pageerror', error => browserErrors.push(error.message))
    let failNext = false
    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), path = url.pathname
      if (path === '/engine/forecast') {
        if (failNext && req.method() === 'PATCH') { failNext = false; await route.fulfill({status:503,json:{detail:'Unavailable'}}); return }
        const response = await request.fetch(server + path + url.search, { method:req.method(), data:req.postDataJSON() ?? undefined })
        await route.fulfill({response})
        return
      }
      const data: Record<string, unknown> = {
        '/auth/v1/token':{access_token:token,refresh_token:'offline',token_type:'bearer',expires_in:3600,user},
        '/auth/v1/user':user, '/finance/accounts':tables.accounts, '/finance/goals':tables.goals,
        '/finance/transactions':tables.transactions, '/engine/recurring/rules':{rules:tables.recurring_rules},
        '/profile':{id:user.id}, '/profile/memory':null,
        '/engine/snapshot':{liquid_assets:20000,investment_assets:10000,non_current_assets:0,total_liabilities:0,net_worth:30000},
      }
      if (path in data) await route.fulfill({json:data[path]})
      else if (['fetch','xhr'].includes(req.resourceType())) await route.fulfill({status:503,json:{detail:'Offline fixture'}})
      else if (['localhost','127.0.0.1'].includes(url.hostname)) await route.continue()
      else await route.abort()
    })
    await page.goto('/login')
    await page.getByLabel('Email', {exact:true}).fill(user.email)
    await page.getByLabel('Password', {exact:true}).fill('offline-only')
    await page.getByRole('button',{name:'Sign In',exact:true}).click()
    await page.getByTestId('tab-spending').click()
    const rules = page.getByRole('region',{name:'Current recurring rules'})
    await expect(rules.getByText('Rent', {exact:true})).toBeVisible()
    await expect(rules).toContainText('$1000.00')
    await expect(rules).toContainText('$60.00')
    await expect(rules).toContainText('$5000.00')
    // These are the same imported September rows driving the forecast baseline.
    const month = page.getByLabel('Summary month')
    await month.fill('2026-09')
    const spending = page.getByRole('region', {name:'Spending and savings'})
    await expect(spending.getByRole('button', {name:/^Income/})).toContainText('$5,000')
    await expect(spending.getByRole('button', {name:/^Spending/})).toContainText('$1,560')
    await page.getByTestId('tab-plan').click()
    const forecast = page.getByRole('region',{name:'Financial forecast'})
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$24,320.00')
    await expect(forecast.getByTestId('forecast-wealth')).toHaveText('$65,280.00')
    await expect(forecast.getByTestId('total-income')).toHaveText('$5,000.00/month equivalent')
    await expect(forecast.getByTestId('total-recurring_costs')).toHaveText('$1,060.00/month equivalent')
    await expect(forecast.getByTestId('total-everyday_spending')).toHaveText('$500.00/month equivalent')
    await expect(forecast.getByLabel('Amount for Rent',{exact:true})).toHaveValue('1000')
    await expect(forecast.getByLabel('Amount for Wedding',{exact:true})).toHaveValue('6000')
    await expect(forecast.getByLabel('Include Wedding',{exact:true})).toHaveCount(1)
    await expect(forecast.getByText('Not modeled yet: amount missing.',{exact:true})).toBeVisible()
    await forecast.getByText('Monthly numbers and limitations',{exact:true}).click()
    await expect(forecast.getByTestId('forecast-month-2026-12')).toContainText('$6,000.00')
    await expect(forecast.getByTestId('forecast-month-2026-12')).toContainText('$20,880.00')

    await forecast.getByLabel('Include Wedding',{exact:true}).uncheck()
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$30,320.00')
    const groceries = forecast.getByLabel('Amount for Groceries',{exact:true})
    await groceries.fill('700')
    await groceries.press('Tab')
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$29,720.00')
    await expect(forecast.getByTestId('total-everyday_spending')).toHaveText('$700.00/month equivalent')
    await page.reload()
    await page.getByTestId('tab-plan').click()
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$29,720.00')
    await expect(forecast.getByLabel('Include Wedding',{exact:true})).not.toBeChecked()

    // Same seed and saved inputs remain byte-stable after a refresh.
    await forecast.getByRole('button',{name:'Refresh forecast'}).click()
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$29,720.00')
    await expect(forecast.getByRole('status')).toHaveCount(0)
    failNext = true
    await forecast.getByLabel('Include Rent',{exact:true}).uncheck()
    await expect(forecast.getByRole('alert')).toContainText('Could not confirm')
    await expect(forecast.getByLabel('Include Rent',{exact:true})).toBeChecked()
    await forecast.getByRole('button',{name:'Refresh forecast'}).click()
    await expect(forecast.getByRole('alert')).toHaveCount(0)
    await expect(forecast.getByTestId('forecast-cash')).toHaveText('$29,720.00')
    await forecast.screenshot({path:`test-results/forecast-${width}.png`})
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    expect(browserErrors).toEqual([])
  })
}
