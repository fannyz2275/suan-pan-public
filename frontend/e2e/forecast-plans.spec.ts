import { test, expect } from '@playwright/test'
import { openForecast, server } from './helpers/forecast'

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: 'block',
  ...(process.env.CHAT_UI_BROWSER_EXECUTABLE ? { launchOptions: { executablePath: process.env.CHAT_UI_BROWSER_EXECUTABLE } } : {}) })

const money = (n: number) => n.toLocaleString('en-US', {style:'currency', currency:'USD'})
// Independent expectations: cash starts at 20k, investments at 10k, monthly
// surplus is 5,000 - 1,000 - 60 - 500 = 3,440. Returns default to zero.
const cases = [
  {name:'ordinary household without dated spending', kind:'ordinary', cash:30320, wealth:71280},
  {name:'wedding paid in full despite saved progress', kind:'wedding', cash:24320, wealth:65280},
  {name:'vacation and wedding both spend cash', kind:'multiple', cash:21320, wealth:62280},
  {name:'emergency savings reserve does not spend wealth', kind:'savings', cash:30320, wealth:71280},
  {name:'competing savings targets cannot reuse cash', kind:'competing', cash:30320, wealth:71280},
  {name:'debt payoff reduces cash and debt equally', kind:'debt', cash:26320, wealth:67280},
  {name:'oversized wedding exposes cash shortfall', kind:'shortfall', cash:-29680, wealth:11280},
  {name:'job loss spends cash without selling investments', kind:'jobloss', cash:15320, wealth:11280},
  {name:'investing half the surplus conserves wealth', kind:'invest', cash:25160, wealth:71280},
  {name:'cash reserve prevents premature investment', kind:'reserve', cash:25000, wealth:71280},
  {name:'annual insurance lands only in its scheduled month', kind:'annual', cash:29120, wealth:70080},
  {name:'biweekly payroll has a three-paycheck month', kind:'biweekly', cash:30320, wealth:76280},
  {name:'refunds reduce spending and internal transfers stay neutral', kind:'refund', cash:30620, wealth:72480},
  {name:'memory-only travel is automatically included', kind:'memory', cash:27320, wealth:68280},
  {name:'missing records are visibly disclosed', kind:'empty', cash:0, wealth:0},
]
for (const width of [1280, 390]) for (const plan of cases) {
  test(`${plan.name} at ${width}px`, async ({page, request}) => {
    await request.post(server + '/reset')
    const tables = await (await request.get(server + '/fixture')).json()
    const wedding = tables.goals[0]
    const settings = tables.user_notes[0]
    tables.goals = []
    tables.user_notes = [settings]
    const goal = (id: string, amount: number, type = 'life_event') => ({...wedding, id, name:id, type, target_amount:amount})
    if (plan.kind === 'wedding') tables.goals = [wedding]
    if (plan.kind === 'multiple') tables.goals = [wedding, goal('Travel',3000)]
    if (plan.kind === 'savings') tables.goals = [goal('Emergency fund',15000,'savings')]
    if (plan.kind === 'competing') tables.goals = [goal('A reserve',20000,'savings'),goal('B deposit',20000,'savings')]
    if (plan.kind === 'debt') {
      tables.accounts.push({...tables.accounts[0], id:'debt', type:'debt',balance:-4000})
      tables.goals = [goal('Pay off card',9000,'debt_payoff')]
    }
    if (plan.kind === 'shortfall') tables.goals = [goal('Wedding',60000)]
    if (plan.kind === 'jobloss') {
      tables.recurring_rules = tables.recurring_rules.filter((r: {direction:string}) => r.direction !== 'income')
      tables.transactions = tables.transactions.filter((r: {category:string}) => r.category !== 'income')
    }
    if (plan.kind === 'invest') settings.provenance.settings.invest_surplus = 0.5
    if (plan.kind === 'reserve') Object.assign(settings.provenance.settings,{invest_surplus:1,cash_reserve:25000})
    if (plan.kind === 'annual') tables.recurring_rules.push({...tables.recurring_rules[1],id:'00000000-0000-4000-8000-000000000099',keyword:'Insurance',normalized_key_pattern:'insurance',amount_median:1200,amount_min:1200,amount_max:1200,frequency:'annual',last_seen_date:'2025-12-15'})
    tables.transactions.forEach((r: {id:string}, i:number) => { r.id = `00000000-0000-4000-8000-${String(100+i).padStart(12,'0')}` })
    if (plan.kind === 'biweekly') Object.assign(tables.recurring_rules[0],{amount_median:2500,amount_min:2500,amount_max:2500,frequency:'biweekly',last_seen_date:'2026-10-30',sample_transaction_ids:tables.transactions.filter((r: {category:string})=>r.category==='income').map((r: {id:string})=>r.id)})
    if (plan.kind === 'refund') for (const month of ['07','08','09']) {
      tables.transactions.push({...tables.transactions[0],id:'refund'+month,date:`2026-${month}-10`,description:'Food refund',category:'groceries',amount:100})
      tables.transactions.push({...tables.transactions[0],id:'transfer'+month,date:`2026-${month}-10`,description:'Savings transfer',category:'transfer',amount:-10000,transfer_status:'user_confirmed_internal'})
    }
    if (plan.kind === 'memory') tables.user_notes.push({id:'travel-memory',user_id:settings.user_id,provenance:{forecast_event:{label:'Travel',amount:3000,month:'2026-12'}}})
    if (plan.kind === 'empty') { tables.accounts=[]; tables.transactions=[]; tables.recurring_rules=[] }
    expect((await request.post(server + '/reset',{data:tables})).ok()).toBeTruthy()
    await page.setViewportSize({width,height:1000})
    const {panel, browserErrors} = await openForecast(page,request)
    await expect(panel.getByTestId('forecast-cash')).toHaveText(money(plan.cash))
    await expect(panel.getByTestId('forecast-wealth')).toHaveText(money(plan.wealth))
    await panel.getByText('Monthly numbers and limitations',{exact:true}).click()
    if (plan.kind === 'competing') {
      await expect(panel).toContainText('B deposit: $20,000.00 in 2026-12 · 0% funded')
      await expect(panel).toContainText('All scheduled goals funded: 0%')
    }
    if (plan.kind === 'debt') await expect(panel).toContainText('Pay off card: $4,000.00')
    if (plan.kind === 'empty' || plan.kind === 'jobloss') await expect(panel).toContainText('Incomplete income or everyday-spending estimates')
    // Verify every displayed ledger cell against real API output, then assert
    // independent cash conservation between successive months (zero returns).
    const result = await (await request.get(server + '/engine/forecast')).json()
    if (plan.kind === 'biweekly') {
      expect(result.projection.find((r: {month:string}) => r.month === '2027-04').income).toBe(7500)
      expect(result.projection.find((r: {month:string}) => r.month === '2027-10').income).toBe(7500)
    }
    let cash = result.starting.liquid_assets
    let wealth = result.starting.net_worth
    for (const row of result.projection) {
      cash += row.income-row.spending-row.planned_spending-row.debt_payment-row.contribution
      wealth += row.income-row.spending-row.planned_spending
      expect(row.cash_p50).toBeCloseTo(cash,2)
      expect(row.wealth_p50).toBeCloseTo(wealth,2)
      await expect(panel.getByTestId('forecast-month-'+row.month).locator('td')).toHaveText([
        row.month,...[row.income,row.spending,row.planned_spending,row.debt_payment,row.contribution,row.cash_p50,row.wealth_p50].map(money)])
    }
    await page.reload()
    await page.getByTestId('tab-plan').click()
    await expect(panel.getByTestId('forecast-cash')).toHaveText(money(plan.cash))
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBeTruthy()
    expect(browserErrors).toEqual([])
  })
}

for (const width of [1280,390]) test(`edits, resets, payment cadence and investment horizons at ${width}px`, async ({page,request}) => {
  test.setTimeout(90000)
  await request.post(server+'/reset')
  await page.setViewportSize({width,height:1000})
  const {panel,browserErrors} = await openForecast(page,request)
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,320.00')
  const edit = async (label:string,value:string) => {
    const field=panel.getByLabel(label,{exact:true})
    await field.fill(value)
    await panel.getByRole('heading',{name:'Cash and wealth forecast',exact:true}).click()
    await expect(panel).toHaveAttribute('aria-busy','false')
  }
  await edit('Month for Wedding','2027-02')
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$30,320.00')
  await panel.getByRole('button',{name:'Reset Wedding',exact:true}).click()
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,320.00')
  await edit('Amount for Vacation','3000')
  await edit('Month for Vacation','2027-01')
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$21,320.00')
  await panel.getByLabel('Include Vacation',{exact:true}).uncheck()
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,320.00')
  await panel.getByLabel('Frequency for Internet',{exact:true}).selectOption('quarterly')
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,440.00')
  await expect(panel.getByTestId('total-recurring_costs')).toHaveText('$1,020.00/month equivalent')
  await panel.getByRole('button',{name:'Reset Internet',exact:true}).click()
  await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,320.00')
  await edit('Expected annual investment return (%)','10')
  await expect(panel.getByTestId('forecast-wealth')).toHaveText('$66,280.00')
  for (const [months,wealth] of [['60', money(20000+3440*60-6000+10000*1.1**5)],['120',money(20000+3440*120-6000+10000*1.1**10)],['360',money(20000+3440*360-6000+10000*1.1**30)]]) {
    await panel.getByLabel('Forecast horizon').selectOption(months)
    await expect(panel.getByTestId('forecast-wealth')).toHaveText(wealth)
    await expect(panel.getByTestId('forecast-cash')).toHaveText('$24,320.00')
  }
  await panel.getByLabel('Forecast horizon').selectOption('12')
  await edit('Annual investment volatility (%)','15')
  const baseline = await (await request.get(server+'/engine/forecast')).json()
  for (const row of baseline.projection) {
    expect(row.wealth_p10).toBeLessThanOrEqual(row.wealth_p50)
    expect(row.wealth_p50).toBeLessThanOrEqual(row.wealth_p90)
  }
  await panel.getByRole('button',{name:'Refresh forecast'}).click()
  await expect(panel).toHaveAttribute('aria-busy','false')
  expect((await (await request.get(server+'/engine/forecast')).json()).projection).toEqual(baseline.projection)
  await page.reload()
  await page.getByTestId('tab-plan').click()
  await expect(panel.getByTestId('forecast-wealth')).toHaveText(money(baseline.projection.at(-1).wealth_p50))
  expect(browserErrors).toEqual([])
})
