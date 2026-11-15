import { test, expect } from '@playwright/test'

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE } } : {}) })

for (const width of [1280, 390]) {
  test(`restore and explicitly resume analysis at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    const user = { id:'00000000-0000-4000-8000-000000000001', email:'resume@example.test', aud:'authenticated', role:'authenticated', app_metadata:{}, user_metadata:{}, created_at:'2026-01-01T00:00:00Z' }
    const part = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url')
    const token = `${part({alg:'HS256',typ:'JWT'})}.${part({sub:user.id,exp:4102444800})}.fake`
    let ready = false
    let calls = 0
    await page.route('**/*', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      const data: Record<string, unknown> = {
        '/auth/v1/token': { access_token:token, refresh_token:'offline', token_type:'bearer', expires_in:3600, user },
        '/auth/v1/user':user, '/finance/accounts':[], '/finance/goals':[], '/profile':{id:user.id}, '/profile/memory':null,
        '/advisor/analysis/config':{enabled:true}, '/advisor/sessions':[{id:'saved-session'}],
        '/advisor/sessions/saved-session/messages':[{role:'user',content:'How did my wealth grow?'},{role:'assistant',content:'I need aligned month-end balances.'}],
        '/advisor/sessions/saved-session/pending-analysis':{pending:calls ? null : {id:'pending',requirements:['aligned_wealth'],missing:ready?[]:['aligned_wealth'],ready,upload_action:ready?null:'upload_statements'}},
      }
      if (path === '/advisor/pending-analysis/pending/resume') {
        calls++
        await new Promise(resolve => setTimeout(resolve, 200))
        await route.fulfill({json:{session_id:'saved-session',message_id:'new-answer',answer:'Your updated balances are now available.'}})
      } else if (path in data) await route.fulfill({json:data[path]})
      else if (['fetch','xhr'].includes(request.resourceType())) await route.fulfill({status:503,json:{detail:'Offline fixture only'}})
      else if (['localhost','127.0.0.1'].includes(new URL(request.url()).hostname)) await route.continue()
      else await route.abort()
    })
    await page.goto('/login')
    await page.getByLabel('Email', {exact:true}).fill(user.email)
    await page.getByLabel('Password', {exact:true}).fill('offline-only')
    await page.getByRole('button',{name:'Sign In',exact:true}).click()
    await page.getByRole('button',{name:'Open advisor',exact:true}).click()
    await expect(page.getByText('I need aligned month-end balances.',{exact:true})).toBeVisible()
    await expect(page.getByRole('button',{name:'Upload missing statements'})).toBeVisible()
    expect(calls).toBe(0)
    await page.getByRole('button',{name:'Upload missing statements'}).click()
    await expect(page.getByRole('heading',{name:'Import statements',exact:true})).toBeVisible()
    await page.getByRole('button',{name:'Cancel',exact:true}).click()
    expect(calls).toBe(0)
    // Simulate committed data becoming available, then a browser restart.
    ready = true
    await page.reload()
    await page.getByRole('button',{name:'Open advisor',exact:true}).click()
    await expect(page.getByRole('button',{name:'Continue analysis'})).toBeVisible()
    expect(calls).toBe(0)
    await page.getByRole('button',{name:'Continue analysis'}).click()
    await expect(page.getByRole('button',{name:'Continue analysis'})).toBeDisabled()
    await expect(page.getByText('Your updated balances are now available.',{exact:true})).toBeVisible()
    expect(calls).toBe(1)
    await expect(page.getByTestId('pending-analysis')).toHaveCount(0)
    await page.screenshot({path:`test-results/advisor-resume-${width}.png`,fullPage:true})
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy()
  })
}
