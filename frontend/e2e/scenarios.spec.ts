import {test,expect} from '@playwright/test';
import {readFileSync,mkdirSync} from 'node:fs';

// Recorded real frozen inference on labelled synthetic supplier inputs, not invented scores.
const actual=JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/combined_actual_numeric.json',import.meta.url),'utf8'));
function fixture(){
  return {configuration:{enabled:true,sensor_failure:true,fire:true},
    run:{id:1,as_of_date:'2025-08-15',revision:1,snapshot_version:'supplier-numeric-fixture',state:'completed',
      workers:actual.evidence_context.workers,worker_errors:{},recommendations:actual.evidence_context.recommendations,rule_version:'evidence-combination-v1.1'},
    runs:[],forecasts:actual.evidence_context.forecasts.map((payload:Record<string,unknown>,i:number)=>({
      id:i+1,run_id:1,worker:payload.worker,object_id:1,channel_id:payload.channel?Number(payload.channel):null,
      payload,attention:false,status:'new',revision:1,decisions:[],request_id:null})),has_more:false};
}
for(const theme of ['dark','light'])test(`real scenario cards are honest and scrollable ${theme}`,async({page})=>{
  const data=fixture();const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(theme=>localStorage.setItem('settings.theme',theme),theme);
  await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'scenario-layout',role:'dispatcher',csrf_token:'layout-only-fixture'}}));
  await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/predictions/scenarios**',r=>r.fulfill({json:data}));
  await page.route(/\/api\/v1\/predictions(\?.*)?$/,r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/predictions/status',r=>r.fulfill({json:{message:'Газовая очередь не изменена'}}));
  await page.route('**/api/v1/predictions/reasons',r=>r.fulfill({json:{}}));
  await page.route('**/api/v1/predictions/runs',r=>r.fulfill({json:[]}));
  for(const [width,height] of [[1024,768],[1280,800],[1440,900]]){
    await page.setViewportSize({width,height});await page.goto('/predictions');
    const section=page.getByRole('region',{name:'Экспериментальные сценарии',exact:true});
    await expect(section.getByText('Сценарная оценка:',{exact:false})).toHaveCount(3);
    await expect(section.getByText('Экспериментально · синтетическая проверка',{exact:true})).toBeVisible();
    await expect(section).not.toContainText(/undefined|NaN|вероятность реального пожара|73%/);
    await page.mouse.move(width-80,height-100);for(let i=0;i<8;i++)await page.mouse.wheel(0,450);
    await expect(section.getByText('Доказательства и ограничения качества',{exact:true})).toBeInViewport();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    if(process.env.SCENARIO_SCREENSHOT_DIR){mkdirSync(process.env.SCENARIO_SCREENSHOT_DIR,{recursive:true});
      await section.locator('.scenario-grid').evaluate(e=>e.scrollIntoView({block:'start'}));
      await page.screenshot({path:`${process.env.SCENARIO_SCREENSHOT_DIR}/${theme}-${width}-scenario-cards.png`});}
  }
  await page.goto('/predictions?scenarioId=3');
  const card=page.getByRole('article',{name:/Экспериментальный сценарный прогноз пожара №3/});
  await expect(card.getByText(/Версия модели:/)).toBeVisible();
  await expect(card.getByRole('button',{name:'Сохранить ручную проверку'})).toBeDisabled();
  await expect(card.getByText('Для сохранения решения заполните комментарий проверки.')).toBeVisible();
  expect(errors).toEqual([]);
});

test('unavailable scenarios never use rejected raw scores and recover independently',async({page})=>{
  await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'scenario-layout',role:'manager',csrf_token:'layout-only-fixture'}}));
  await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
  await page.route(/\/api\/v1\/predictions(\?.*)?$/,r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/predictions/status',r=>r.fulfill({json:{message:'Газовая очередь доступна независимо'}}));
  await page.route('**/api/v1/predictions/reasons',r=>r.fulfill({json:{}}));
  await page.route('**/api/v1/predictions/runs',r=>r.fulfill({json:[]}));
  const missing=fixture();missing.forecasts=[];
  missing.run.workers.fire={status:'invalid',reason:'UNSUPPORTED_MODEL_VERSION'};
  missing.run.worker_errors={sensor_failure:'INSUFFICIENT_HISTORY'};
  let fail=true;
  await page.route('**/api/v1/predictions/scenarios**',r=>fail?r.fulfill({status:503,json:{detail:'private-internal-error'}}):r.fulfill({json:missing}));
  await page.goto('/predictions');
  await expect(page.locator('.status-notice')).toContainText('Газовая очередь доступна независимо');
  await expect(page.getByRole('button',{name:'Повторить загрузку сценариев'})).toBeVisible();
  fail=false;await page.getByRole('button',{name:'Повторить загрузку сценариев'}).click();
  const region=page.getByRole('region',{name:'Экспериментальные сценарии',exact:true});
  await expect(region).toContainText('Недостаточный охват истории');
  await expect(region).toContainText('Неподдерживаемая версия модели');
  await expect(region).not.toContainText(/private-internal-error|0%|0,000/);
  await expect(region.getByText('Экспериментально · синтетическая проверка',{exact:true})).toBeVisible();
});

test('real scenario API review creates a separate draft and confirms through existing workflow',async({page})=>{
  test.skip(!process.env.TEST_SCENARIO_ID,'Requires real inference persisted in isolated scenario QA');
  const id=process.env.TEST_SCENARIO_ID;
  await page.goto(`/predictions?scenarioId=${id}`);
  await page.getByPlaceholder('Логин',{exact:true}).fill(process.env.TEST_USERNAME??'dispatcher');
  await page.getByLabel('Пароль',{exact:true}).fill(process.env.TEST_PASSWORD??'');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  const card=page.getByRole('article',{name:new RegExp(`№${id}$`)});
  await expect(card).toHaveCount(1);
  await card.getByLabel('Комментарий проверки',{exact:true}).fill('Проверка технического маршрута; синтетический сценарий');
  await card.getByRole('button',{name:'Сохранить ручную проверку'}).click();
  await expect(card.getByText('Решение сохранено',{exact:true})).toBeVisible();
  await card.getByRole('button',{name:'Создать отдельный черновик заявки'}).click();
  const link=card.getByRole('link',{name:/Открыть черновик \/ заявку/});await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByLabel('Тема черновика',{exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Подтвердить заявку',exact:true})).toBeEnabled();
  await page.getByRole('button',{name:'Подтвердить заявку',exact:true}).click();
  await expect(page.getByText('Черновик подтверждён: заявка создана',{exact:true})).toBeVisible();
});
