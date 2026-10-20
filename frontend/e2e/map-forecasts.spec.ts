import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
const actual=JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/combined_actual_numeric.json',import.meta.url),'utf8'));
const recorded=actual.evidence_context.forecasts;
function fixture(){return {configuration:{enabled:true,sensor_failure:true,fire:true},scenario_run:{id:1,state:'completed'},truncated:false,
  forecasts:recorded.map((p:Record<string,unknown>,i:number)=>({key:`${p.worker}-${i+1}`,worker:p.worker,object_id:1,channel_id:p.channel?Number(p.channel):null,
    bound:true,available:true,score:p.score,warning:p.warning,source:'Синтетический сценарий · экспериментальная модель',cutoff:p.cutoff,
    issued_at:p.issued_at,window_start:p.window_start,window_end_exclusive:p.window_end_exclusive,model_version:p.model_version,
    snapshot_version:'recorded-supplier-inference',detail_url:`/predictions?scenarioRun=1&scenarioId=${i+1}`,recommendations:[]})).concat([{key:'gas-recorded-public',worker:'gas',object_id:2,channel_id:3,bound:true,available:true,score:0.00830046623911187,warning:null,source:'Демонстрационные данные · сохранённый gas proxy',cutoff:'2026-09-28',issued_at:'2026-09-29T06:00:00+03:00',window_start:'2026-09-30',window_end_exclusive:'2026-10-01',model_version:'gas-cross-g2-v3-refit_2025h1-0312ff1f436e',snapshot_version:'daily-2026-09-28:r1',detail_url:'/predictions?predictionId=1',recommendations:[]}])};}

for(const theme of ['dark','light'])test(`map displays every saved model without hiding low scores ${theme}`,async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.addInitScript(v=>localStorage.setItem('settings.theme',v),theme);
  await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'map-layout',role:'manager',csrf_token:'layout-only-fixture'}}));
  await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
  await page.route('**/api/v1/map/objects',r=>r.fulfill({json:[{object_id:1,name:'ДЕМО — проверка нескольких моделей',object_type:'Синтетический сценарий',status:'alarm',sensor_count:2,sensors_with_data:0,alarm_sensor_count:0,last_event_time:null,geometry:{type:'Point',coordinates:[37.55,55.75]},geometry_is_synthetic:true,data_is_synthetic:true},{object_id:2,name:'ДЕМО — газовый канал',object_type:'Синтетический сценарий',status:'unknown',sensor_count:1,sensors_with_data:0,alarm_sensor_count:0,last_event_time:null,geometry:{type:'Point',coordinates:[37.8,55.6]},geometry_is_synthetic:true,data_is_synthetic:true}]}));
  let fail=false;await page.route('**/api/v1/map/forecasts',r=>fail?r.fulfill({status:503,json:{detail:'private-stack'}}):r.fulfill({json:fixture()}));
  await page.route('**/api/v1/objects/1/sensors',r=>r.fulfill({json:{object_id:1,sensors:[]}}));
  await page.goto('/?mapMode=forecasts');
  const controls=page.getByRole('region',{name:'Фильтры прогнозов карты'});
  await expect(controls).toContainText('4 результата');
  await expect(page.locator('.map-forecast-marker-label')).toContainText(['S/F','G']);
  await expect(page.locator('.map-legend')).not.toBeVisible();
  await page.getByRole('button',{name:/ДЕМО — проверка нескольких моделей · S \/ F/}).click();
  const drawer=page.locator('.object-drawer');await expect(drawer).toBeVisible();
  await expect(drawer.locator('.map-forecast-card')).toHaveCount(3);
  await expect(drawer).toContainText('Порог сценарного предупреждения не превышен');
  await expect(drawer.getByRole('link',{name:'Детали, решение и черновик заявки'}).last()).toHaveAttribute('href',/scenarioId=3/);
  for(const [width,height] of [[1024,768],[1280,800],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});await expect(drawer).toBeInViewport();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.locator('.schematic-map-svg').dispatchEvent('wheel',{deltaY:-10000,ctrlKey:true,clientX:600,clientY:450,bubbles:true,cancelable:true});
    const view=await page.locator('.schematic-map-svg').getAttribute('viewBox');expect(view).not.toMatch(/NaN|Infinity/);
    await expect(drawer.locator('.drawer-close')).toBeInViewport();
    const toggle=(await page.getByRole('group',{name:'Режим карты'}).boundingBox())!;
    const reset=(await page.getByRole('button',{name:'Показать все',exact:true}).boundingBox())!;
    expect(toggle.x<reset.x+reset.width&&toggle.x+toggle.width>reset.x&&toggle.y<reset.y+reset.height&&toggle.y+toggle.height>reset.y).toBe(false);
  }
  await drawer.locator('.drawer-close').click();await expect(drawer).not.toBeVisible();
  await controls.getByLabel('Модель',{exact:true}).selectOption('fire');await expect(controls).toContainText('1 результат');
  await expect(page.locator('.map-forecast-marker-label')).toHaveText('F');
  await page.goBack();await expect(controls.getByLabel('Модель',{exact:true})).toHaveValue('all');
  await controls.getByLabel('Модель',{exact:true}).selectOption('fire');
  await controls.locator('.map-forecast-object-links button').first().click();
  await expect(drawer.locator('.map-forecast-card').first()).toHaveClass(/fire/);
  await drawer.locator('.drawer-close').click();
  await controls.getByLabel('Модель',{exact:true}).selectOption('gas');await expect(page).toHaveURL(/forecastType=gas/);await expect(page.locator('.map-forecast-marker-label')).toHaveCount(1);await expect(page.locator('.map-forecast-marker-label')).toHaveText('G');
  await controls.getByLabel('Модель',{exact:true}).selectOption('multiple');await expect(controls).toContainText('3 результата');
  await controls.getByLabel('Доступность',{exact:true}).selectOption('unavailable');await expect(controls).toContainText('По выбранным фильтрам результатов нет');
  await page.getByRole('button',{name:'Фактическое состояние',exact:true}).click();await expect(page.locator('.map-legend')).toBeVisible();
  fail=true;await page.reload();await page.getByRole('button',{name:'Прогнозы',exact:true}).click();
  await expect(controls.getByRole('alert')).toBeVisible();await expect(controls).not.toContainText('private-stack');
  fail=false;await controls.getByRole('button',{name:'Повторить загрузку прогнозов'}).click();await expect(controls.getByRole('alert')).not.toBeVisible();
  expect(errors).toEqual([]);
});
