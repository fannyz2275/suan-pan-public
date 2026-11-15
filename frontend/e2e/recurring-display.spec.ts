import { test, expect } from '@playwright/test'

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE } } : {}) })

for (const width of [1280, 390]) {
  test(`recurring frequency, last payment and scan recovery at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const user = { id:'00000000-0000-4000-8000-000000000001', email:'recurring@example.test', aud:'authenticated', role:'authenticated', app_metadata:{}, user_metadata:{}, created_at:'2026-01-01T00:00:00Z' }
    const part = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url')
    const token = `${part({alg:'HS256',typ:'JWT'})}.${part({sub:user.id,exp:4102444800})}.fake`
    const rules = ['monthly','biweekly','annual'].map((frequency, i) => ({id:`r${i}`,keyword:['Internet service','Paycheck','Annual membership'][i],frequency,last_seen_date:'2026-09-04',status:'auto_applied',direction:i===1?'income':'expense',amount_median:60}))
    rules.push({...rules[0], id:'old', keyword:'Old subscription', last_seen_date:'2026-08-31'})
    let calls = 0
    let release!: () => void
    const gate = new Promise<void>(resolve => { release = resolve })
    await page.route('**/*', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      const data: Record<string, unknown> = {
        '/auth/v1/token': { access_token:token, refresh_token:'offline', token_type:'bearer', expires_in:3600, user },
        '/auth/v1/user':user, '/finance/accounts':[], '/finance/goals':[], '/profile':{id:user.id}, '/profile/memory':null,
        '/engine/recurring/rules':{rules},
      }
      if (path === '/engine/recurring/rules/r0' && request.method() === 'PATCH') {
        rules[0] = {...rules[0], frequency:request.postDataJSON().frequency, status:'user_confirmed'}
        await route.fulfill({json:rules[0]})
      } else if (path === '/engine/recurring/detect') {
        calls++
        if (calls === 1) { await gate; await route.fulfill({json:{rules}}) }
        else await route.fulfill({status:503,json:{detail:'Scan unavailable'}})
      } else if (path in data) await route.fulfill({json:data[path]})
      else if (['fetch','xhr'].includes(request.resourceType())) await route.fulfill({status:503,json:{detail:'Offline fixture'}})
      else if (['localhost','127.0.0.1'].includes(new URL(request.url()).hostname)) await route.continue()
      else await route.abort()
    })
    await page.goto('/login')
    await page.getByLabel('Email', {exact:true}).fill(user.email)
    await page.getByLabel('Password', {exact:true}).fill('offline-only')
    await page.getByRole('button',{name:'Sign In',exact:true}).click()
    await page.getByTestId('tab-spending').click()
    const card = page.getByRole('region', {name:'Current recurring rules'})
    for (const label of ['Monthly','Bi-weekly','Annually']) await expect(card.getByText(label,{exact:true}).first()).toBeVisible()
    await expect(card.getByText('Last paid Sep 4, 2026')).toHaveCount(3)
    await card.getByLabel('Hide payments last seen before').fill('2026-09')
    await expect(card.getByText('Old subscription')).toHaveCount(0)
    await expect(card.getByText('Internet service')).toBeVisible()
    await card.getByRole('button',{name:'Show all dates'}).click()
    await expect(card.getByText('Old subscription')).toBeVisible()
    await card.getByRole('button',{name:'Change frequency for Internet service'}).click()
    await card.getByLabel('Frequency for Internet service', {exact:true}).selectOption('biweekly')
    await expect(card.getByLabel('Frequency for Internet service', {exact:true})).toHaveCount(0)
    await expect(card.getByText('Bi-weekly',{exact:true})).toHaveCount(2)
    await card.getByRole('button',{name:'Scan transactions'}).click()
    await expect(card.getByRole('button',{name:'Scanning'})).toBeDisabled()
    await expect(card.getByRole('status')).toBeVisible()
    release()
    await expect(card.getByText(/Scan complete/)).toBeVisible()
    await card.getByRole('button',{name:'Scan transactions'}).click()
    await expect(card.getByRole('alert')).toContainText("couldn't confirm the scan completed")
    await expect(card.getByRole('alert')).not.toContainText('saved rules are unchanged')
    await expect(card.getByText('Internet service')).toBeVisible()
    await card.getByRole('button',{name:'Refresh results'}).click()
    await expect(card.getByRole('alert')).toHaveCount(0)
    await card.screenshot({path:`test-results/recurring-${width}.png`})
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
    expect(calls).toBe(2)
  })
}
