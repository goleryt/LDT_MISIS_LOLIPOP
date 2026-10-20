// Explicit existing demo smoke. No inference, fixtures, credentials or traces in output.
const fs=require('fs'),path=require('path'),{createRequire}=require('module');
const root=path.resolve(__dirname,'../..');
if(process.env.RUN_REMOTE_SCENARIOS!=='true')throw new Error('Explicit RUN_REMOTE_SCENARIOS=true required');
const access=fs.realpathSync(process.env.REMOTE_ACCESS_FILE??'');
const relative=path.relative(root,access);
if(!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative))throw new Error('Credentials must be outside repository');
const accounts=JSON.parse(fs.readFileSync(access,'utf8'));
const {chromium,expect}=createRequire(path.join(root,'frontend/package.json'))('@playwright/test');
const base='https://ldt-demo-production.up.railway.app';
const out=process.env.REMOTE_EVIDENCE_DIR;
if(!out)throw new Error('Explicit evidence directory required');fs.mkdirSync(out,{recursive:true});
const result={url:base,date:new Date().toISOString(),checks:[],screenshots:[],page_errors:[]};
const pass=(name,data={})=>{result.checks.push({name,status:'PASS',...data});console.log('PASS '+name);};
(async()=>{
 const browser=await chromium.launch({channel:'chrome'});result.browser=browser.version();
 const context=await browser.newContext({baseURL:base,viewport:{width:1280,height:800}});
 const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>result.page_errors.push(e.message));
 const save=async name=>{await page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});result.screenshots.push(name+'.png');};
 try{
  await page.goto('/predictions');await page.getByPlaceholder('Логин',{exact:true}).fill(accounts.dispatcher.username);
  await page.getByLabel('Пароль',{exact:true}).fill(accounts.dispatcher.password);
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
  const response=await page.request.get('/api/v1/predictions/scenarios');expect(response.status()).toBe(200);
  const data=await response.json();expect(data.configuration).toMatchObject({enabled:true,fire:true,sensor_failure:true,operational_ready:false,automated_action_allowed:false});
  expect(data.run.state).toBe('completed');expect(data.forecasts).toHaveLength(3);
  expect(data.run.workers.sensor_failure.status).toBe('available');expect(data.run.workers.fire.status).toBe('available');
  for(const row of data.forecasts){expect(row.payload.eligible).toBe(true);expect(Number.isFinite(row.payload.score)).toBe(true);expect(row.payload.score).toBeGreaterThanOrEqual(0);expect(row.payload.score).toBeLessThanOrEqual(1);expect(row.payload).toMatchObject({evidence_level:'E4',score_kind:'scenario_score',label_source:'synthetic_scenario'});}
  pass('validated simultaneous SF and Fire API with production guard and no automatic action',{run_id:data.run.id,forecasts:data.forecasts.length});
  const section=page.getByRole('region',{name:'Экспериментальные сценарии',exact:true});
  for(const theme of ['dark','light'])for(const width of [1024,1280,1440]){
   await page.evaluate(v=>localStorage.setItem('settings.theme',v),theme);await page.setViewportSize({width,height:800});await page.goto('/predictions');
   await expect(section.locator('.scenario-forecast-card')).toHaveCount(3);
   for(const row of data.forecasts){const card=section.locator(`article[aria-label$="№${row.id}"]`);await expect(card.locator('.scenario-badge')).toContainText(/Синтетическая|синтетическая/);expect(await card.locator('.scenario-score').textContent()).not.toContain('%');}
   expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
   await section.scrollIntoViewIfNeeded();await save(`scenario-${theme}-${width}`);
  }pass('real public scenario cards both themes and three desktop widths');
  await page.setViewportSize({width:1280,height:800});result.requests=[];
  for(const worker of ['sensor_failure','fire']){
   const row=data.forecasts.find(f=>f.worker===worker&&!f.request_id)??data.forecasts.find(f=>f.worker===worker);await page.goto(`/predictions?scenarioRun=${data.run.id}&scenarioId=${row.id}`);
   const card=section.locator(`article[aria-label$="№${row.id}"]`);
   await expect(card.getByText(/Версия модели:/)).toContainText(row.payload.model_version);
   await card.getByLabel('Комментарий проверки',{exact:true}).fill('REMOTE DEMO: ручная техническая проверка синтетического сценария; не реальный инцидент.');
   await card.getByRole('combobox',{name:'Решение',exact:true}).selectOption('reviewed');
   await card.getByRole('button',{name:'Сохранить ручную проверку',exact:true}).click();await expect(card.getByText('Решение сохранено',{exact:true})).toBeVisible();
   if(!row.request_id){await card.getByRole('button',{name:'Создать отдельный черновик заявки',exact:true}).click();}
   const link=card.getByRole('link',{name:/Открыть черновик \/ заявку/});await expect(link).toBeVisible();
   const href=await link.getAttribute('href');const id=Number(new URL(href,base).searchParams.get('requestId'));await link.click();
   const req=await (await page.request.get('/api/v1/requests')).json();const current=req.find(r=>r.id===id);
   if(current.status==='draft'){
    await page.getByLabel('Тема черновика',{exact:true}).fill(`REMOTE SYNTHETIC DEMO — ${worker} — ручная проверка`);
    await page.getByRole('textbox',{name:'Описание черновика',exact:true}).fill('Демонстрационный сценарий поставки. Не реальное происшествие, без внешнего выезда.');
    await page.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await expect(page.locator('.requests-feedback')).toHaveText('Черновик сохранён');
    await page.getByRole('button',{name:'Подтвердить заявку',exact:true}).click();await expect(page.locator('.requests-feedback')).toContainText('Черновик подтверждён');
   }
   const history=await (await page.request.get(`/api/v1/requests/${id}/history`)).json();expect(history.some(h=>h.to_status==='draft')).toBe(true);expect(history.some(h=>h.from_status==='draft'&&h.to_status==='new')).toBe(true);
   const me=await (await page.request.get('/api/v1/auth/me')).json();const duplicate=await page.request.post(`/api/v1/predictions/scenarios/${row.id}/request`,{headers:{'X-CSRF-Token':me.csrf_token}});expect(duplicate.status()).toBe(200);expect((await duplicate.json()).request_id).toBe(id);
   result.requests.push({worker,forecast_id:row.id,request_id:id,created_now:!row.request_id,confirmed_now:current.status==='draft',history:history.map(h=>h.to_status)});await save('request-'+worker);
  }expect(result.requests[0].request_id).not.toBe(result.requests[1].request_id);pass('separate manual review draft confirmation history and idempotency');
  for(const theme of ['dark','light'])for(const width of [1024,1280,1440]){
   await page.evaluate(v=>localStorage.setItem('settings.theme',v),theme);await page.setViewportSize({width,height:800});await page.goto('/imports');
   const table=page.locator('.imports-page tbody');await expect(table).toBeVisible();const last=table.locator('tr').last();await expect(last).toBeAttached();
   await page.mouse.move(width-90,700);for(let i=0;i<10;i++)await page.mouse.wheel(0,650);
   await expect(last).toBeInViewport();expect(await page.locator('.imports-page').evaluate(e=>e.scrollTop)).toBeGreaterThan(0);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);await save(`import-wheel-${theme}-${width}`);
  }pass('actual public import history user-wheel bottom access without transport mocks');
  await page.goto('/settings');await page.getByRole('button',{name:'Выйти из аккаунта',exact:true}).click();
  await expect(page.getByRole('button',{name:'Войти',exact:true})).toBeVisible();
  expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);
  expect(result.page_errors).toEqual([]);result.status='PASS';
 }catch(e){result.status='FAIL';result.failure=String(e);console.error(String(e));await save('failure');process.exitCode=1;}
 finally{fs.writeFileSync(path.join(out,'scenarios-browser.json'),JSON.stringify(result,null,2)+'\n');await browser.close();}
})();
