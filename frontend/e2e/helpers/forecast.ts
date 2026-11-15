import type { Page, APIRequestContext } from '@playwright/test'
export const server = process.env.FORECAST_TEST_API || 'http://127.0.0.1:8099'
export async function openForecast(page: Page, request: APIRequestContext) {
 const tables = await (await request.get(server + '/fixture')).json()
    const forecastResponse = await request.get(server + '/engine/forecast')
    if (!forecastResponse.ok()) throw new Error(await forecastResponse.text())
    const snapshot = (await forecastResponse.json()).starting
    const user = { id:'00000000-0000-4000-8000-000000000001', email:'forecast@example.test', aud:'authenticated', role:'authenticated', app_metadata:{}, user_metadata:{}, created_at:'2026-01-01T00:00:00Z' }
    const part = (v: unknown) => Buffer.from(JSON.stringify(v)).toString('base64url')
    const token = `${part({alg:'HS256',typ:'JWT'})}.${part({sub:user.id,exp:4102444800})}.fake`
    const browserErrors: string[] = []
    page.on('pageerror', error => browserErrors.push(error.message))

    await page.route('**/*', async route => {
      const req = route.request(), url = new URL(req.url()), path = url.pathname
      if (path === '/engine/forecast' || path.startsWith('/profile/ai-providers')) {
        const response = await request.fetch(server + path + url.search, { method:req.method(), data:req.postDataJSON() ?? undefined })
        await route.fulfill({response})
        return
      }
      const data: Record<string, unknown> = {
        '/auth/v1/token':{access_token:token,refresh_token:'offline',token_type:'bearer',expires_in:3600,user},
        '/auth/v1/user':user, '/finance/accounts':tables.accounts, '/finance/goals':tables.goals,
        '/finance/transactions':tables.transactions, '/engine/recurring/rules':{rules:tables.recurring_rules},
        '/profile':{id:user.id}, '/profile/memory':null,
        '/engine/snapshot':snapshot,
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
 await page.getByTestId('tab-plan').click()
 return { panel: page.getByRole('region', {name: 'Financial forecast'}), browserErrors }
}
