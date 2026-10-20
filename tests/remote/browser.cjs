// Opt-in checks against the existing demo. No inference, traces, or secret output.
const fs=require('fs');const path=require('path');const {createRequire}=require('module');
const root=path.resolve(__dirname,'../..');
if(process.env.RUN_REMOTE_RC!=='true')throw new Error('Explicit RUN_REMOTE_RC=true is required: this probe writes labelled demo workflow data.');
const {chromium,expect}=createRequire(path.join(root,'frontend/package.json'))('@playwright/test');
const access=process.env.REMOTE_ACCESS_FILE;
if(!access)throw new Error('REMOTE_ACCESS_FILE must point to credentials outside the repository.');
const relative=path.relative(root,fs.realpathSync(access));
if(!relative.startsWith('..'+path.sep) && !path.isAbsolute(relative))throw new Error('Credentials must be outside the repository.');
const accounts=JSON.parse(fs.readFileSync(access,'utf8'));
const base='https://ldt-demo-production.up.railway.app';
const out=process.env.REMOTE_EVIDENCE_DIR??path.join(root,'docs/evidence/release-rc/remote');fs.mkdirSync(out,{recursive:true});
const result={base_url:base,date:new Date().toISOString(),checks:[],screenshots:[],page_errors:[],unexpected_server_errors:[]};
const record=(name,details={})=>{result.checks.push({name,status:'PASS',...details});console.log('PASS '+name);};
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});result.browser=browser.version();
 const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:900}});
 const page=await context.newPage();page.setDefaultTimeout(20000);
 page.on('pageerror',e=>result.page_errors.push(e.message));
 page.on('response',r=>{if(r.status()>=500 && r.url().startsWith(base+'/api/'))result.unexpected_server_errors.push({path:new URL(r.url()).pathname,status:r.status()});});
 const save=async(name)=>{await page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});result.screenshots.push(name+'.png');};
 const get=async(p)=>{const r=await page.request.get(p);expect(r.status(),p).toBe(200);return r.json();};
 const login=async(role,target='/')=>{
  await page.goto(base+target);await page.getByPlaceholder('Логин',{exact:true}).fill(accounts[role].username);
  await page.getByLabel('Пароль',{exact:true}).fill(accounts[role].password);
  await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
 };
 try {
  await login('dispatcher');record('HTTPS browser login');
  const predictions=await get('/api/v1/predictions');expect(predictions.length).toBeGreaterThan(0);
  const requests=await get('/api/v1/requests');
  const target=predictions.find(p=>requests.some(q=>q.id===p.request_id && q.status==='draft'))
    ?? predictions.find(p=>p.recommendation && !p.request_id && !['closed','false_alarm'].includes(p.status))??predictions[0];
  const pendingDraft=requests.some(q=>q.id===target.request_id && q.status==='draft');
  result.prediction_id=target.id;result.object_id=target.object_id;result.channel_id=target.channel_id;
  const mapPath=`/?objectId=${target.object_id}&channelId=${target.channel_id}`;
  await page.goto(base+mapPath);await expect(page.locator('.object-drawer')).toBeVisible();
  await expect(page.getByRole('heading',{name:'Последние события',exact:true})).toBeVisible();
  const history=await get(`/api/v1/sensors/${target.channel_id}/history`);
  record('map to object to exact sensor and history',{events:history.events?.length});
  await page.reload();await expect(page.locator('.object-drawer')).toBeVisible();record('object sensor deep link refresh');
  for(let i=0;i<3;i++){
   await page.getByRole('button',{name:'Закрыть датчик',exact:true}).click();
   await expect(page).not.toHaveURL(/channelId=/);
   await page.goBack();await expect(page).toHaveURL(new RegExp('channelId='+target.channel_id));
   await expect(page.getByRole('complementary',{name:'Подробности датчика'})).toBeVisible();
  }record('fast browser Back restores the exact sensor three times');
  const svg=page.locator('.schematic-map-svg');
  for(const [width,height] of [[1440,900],[1280,800],[1024,700]]){
   await page.setViewportSize({width,height});
   await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
   await expect(page.locator('.drawer-close')).toBeInViewport();await expect(page.locator('.schematic-map-controls')).toBeInViewport();
   await save(`map-${width}`);
  }
  const drawer=await page.locator('.object-drawer').boundingBox();
  const intercepted=await svg.evaluate(el=>{const b=el.getBoundingClientRect();return [0,1,2].flatMap(deltaMode=>Array.from({length:40},()=>{
   const e=new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaMode,deltaY:-3,clientX:b.left+100,clientY:b.top+100});el.dispatchEvent(e);return e.defaultPrevented;
  }));});expect(intercepted.every(Boolean)).toBe(true);
  await expect.poll(async()=>Number((await svg.getAttribute('viewBox')).split(' ')[2])).toBe(300);
  expect((await svg.getAttribute('viewBox')).split(' ').map(Number).every(Number.isFinite)).toBe(true);
  expect((await page.locator('.object-drawer').boundingBox()).width).toBeCloseTo(drawer.width,0);
  await expect(page.locator('.drawer-close')).toBeInViewport();await save('map-large-zoom');
  await page.locator('.schematic-reset-button').click();await page.locator('.schematic-map-controls button').first().click();
  await page.locator('.schematic-map-controls button').nth(1).click();
  // Exercise a visible patch of map rather than a sensor overlay covering its left edge.
  await page.setViewportSize({width:1440,height:900});
  const point=await svg.evaluate(el=>{const r=el.getBoundingClientRect();
   for(let y=r.top+80;y<r.bottom-30;y+=40)for(let x=r.left+30;x<r.right-30;x+=40)
    if(document.elementFromPoint(x,y)?.closest('.schematic-map-svg'))return {x,y};
   return null;
  });expect(point).not.toBeNull();await page.mouse.move(point.x,point.y);await page.mouse.wheel(0,-100);
  await expect(svg).not.toHaveAttribute('viewBox','0 0 1200 820');
  await page.locator('.drawer-close').click();await expect(page.locator('.object-drawer')).toHaveCount(0);
  record('map resize wheel synthetic pinch extreme scale and drawer');
  await page.setViewportSize({width:1440,height:900});await page.goto(base+'/alarms');
  await expect(page.locator('.alarms-panel')).toBeVisible();
  const alarm=page.locator('tbody tr').first();await expect(alarm).toBeVisible();await alarm.click();
  await expect(page).toHaveURL(/objectId=\d+&channelId=\d+/);await expect(page.getByRole('heading',{name:'Последние события',exact:true})).toBeVisible();
  record('alarm to exact object and sensor');
  await page.locator('.notification-panel summary').click();
  const notice=page.locator('.notification-panel a').first();
  if(await notice.count()){
   await notice.click();await expect(page.locator('main')).toBeVisible();
   await page.locator('.notification-panel button').first().click();record('notification navigation and mark read');
   await page.locator('.notification-panel summary').click();
  }else result.checks.push({name:'notification entity navigation',status:'NOT TESTED',reason:'No existing unread notification; no fabricated prediction notice'});
  await page.goto(base+`/predictions?predictionId=${target.id}`);await expect(page.locator('.prediction-detail')).toBeVisible();
  await page.reload();await expect(page.getByRole('heading',{name:`Прогноз №${target.id}`,exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Закрыть прогноз',exact:true}).click();await page.goBack();await expect(page.locator('.prediction-detail')).toBeVisible();
  if(!target.request_id || pendingDraft){
   await page.getByLabel('Комментарий',{exact:true}).fill('REMOTE RC VALIDATION: контроль обработки существующего demo-прогноза, без нового inference.');
   await page.getByRole('button',{name:'Сохранить решение',exact:true}).click();
   await expect(page.getByText(`Решение по прогнозу №${target.id} сохранено`,{exact:true})).toBeVisible();
   if(!target.request_id)await page.getByRole('button',{name:'Создать черновик заявки',exact:true}).click();
   await page.getByRole('link',{name:/Открыть заявку · №/}).click();
   await expect(page.getByRole('heading',{name:/Черновик заявки №/})).toBeVisible();
   await page.getByLabel('Тема черновика',{exact:true}).fill('REMOTE RC DEMO — проверка рекомендации диспетчером');
   await page.getByRole('textbox',{name:'Описание черновика',exact:true}).fill('Тестовый workflow существующего синтетического demo-объекта. Во внешнюю ИС не передаётся.');
   await page.getByRole('combobox',{name:'Приоритет черновика',exact:true}).selectOption('high');
   await save('request-draft-filled');
   await page.getByRole('button',{name:'Сохранить черновик',exact:true}).click();await expect(page.locator('.requests-feedback')).toHaveText('Черновик сохранён');
   const response=page.waitForResponse(r=>r.request().method()==='PATCH' && /\/api\/v1\/requests\/\d+$/.test(r.url()));
   await page.getByRole('button',{name:'Подтвердить заявку',exact:true}).click();const changed=await response;expect(changed.status()).toBe(200);
   const row=await changed.json();result.request_id=row.id;expect(row.status).toBe('new');
   await expect(page.locator('.requests-feedback')).toContainText('Черновик подтверждён');
   await save('request-confirmed');
   await page.getByRole('region',{name:`Проверка заявки ${row.id}`}).getByRole('button',{name:'Закрыть просмотр заявки',exact:true}).click();
   const statusControl=page.getByRole('combobox',{name:`Статус заявки ${row.id}`,exact:true});
   for(const status of ['in_progress','completed']){
    const updated=page.waitForResponse(r=>r.request().method()==='PATCH' && r.url().endsWith(`/api/v1/requests/${row.id}`));
    await statusControl.selectOption(status);expect((await updated).status()).toBe(200);
   }
   const changes=await get(`/api/v1/requests/${row.id}/history`);expect(changes.map(c=>c.to_status)).toEqual(['draft','draft','new','in_progress','completed']);
   record('stored prediction decision recommendation draft review confirmation completion',{request_id:row.id,history:changes.map(c=>c.to_status)});
  } else record('existing prediction request link',{request_id:target.request_id});
  await page.goto(base+'/requests');await page.getByRole('button',{name:'Новая заявка',exact:true}).click();
  await expect(page.getByRole('button',{name:'Создать заявку',exact:true})).toBeDisabled();
  await expect(page.getByText('Выберите объект — это обязательное поле.')).toBeVisible();
  await page.getByRole('combobox',{name:'Объект',exact:true}).selectOption(String(target.object_id));
  await page.getByRole('combobox',{name:'Датчик',exact:true}).selectOption(String(target.channel_id));
  await page.getByLabel('Тема',{exact:true}).fill('REMOTE RC DEMO — ручная проверка заполненной формы');
  await page.getByLabel('Описание',{exact:true}).fill('Без изменения ML и без внешнего выезда.');
  await page.getByRole('combobox',{name:'Приоритет',exact:true}).selectOption('medium');
  await expect(page.getByRole('button',{name:'Создать заявку',exact:true})).toBeEnabled();await save('request-create-filled');
  const created=page.waitForResponse(r=>r.request().method()==='POST' && r.url().endsWith('/api/v1/requests'));
  await page.getByRole('button',{name:'Создать заявку',exact:true}).click();const row=await(await created).json();result.manual_request_id=row.id;
  await expect(page.locator('.requests-feedback')).toHaveText('Заявка создана');record('fully filled request creation',{request_id:row.id});
  await page.goto(base+'/imports');const name='remote-rc-demo-'+Date.now()+'.json';
  const content=JSON.stringify([{ид_события:String(980000000000+Math.floor(Date.now()/1000)),ид_канала_данных:String(target.channel_id),дата:'2026-10-18',время:'22:00:00',тревожное:'false',значение_датчика:'0.310'}]);
  const file={name,mimeType:'application/json',buffer:Buffer.from(content)};
  await page.locator('input[type=file]').setInputFiles(file);await page.getByRole('button',{name:'Начать импорт',exact:true}).click();
  await expect(page.getByText('Файл успешно обработан и зарегистрирован.')).toBeVisible();await expect(page.locator('tr').filter({hasText:name})).toContainText('Завершён');
  await page.locator('input[type=file]').setInputFiles(file);await page.getByRole('button',{name:'Начать импорт',exact:true}).click();
  await expect(page.getByText('Этот файл уже был успешно импортирован ранее.')).toBeVisible();record('safe labelled demo import registry and duplicate');
  await page.goto(base+'/reports');
  for(const format of ['PDF','XLSX']){
   const download=page.waitForEvent('download');await page.getByRole('button',{name:`Скачать ${format}`,exact:true}).click();
   const d=await download;expect(await d.failure()).toBeNull();await d.saveAs(path.join(out,'remote-report.'+format.toLowerCase()));
  }record('browser PDF and XLSX exports');
  for(const theme of ['dark','light']){
   await page.evaluate(v=>localStorage.setItem('settings.theme',v),theme);
   for(const [url,name] of [['/alarms','alerts'],['/imports','imports'],['/events','journal'],[`/predictions?predictionId=${target.id}`,'prediction'],['/settings','settings'],[mapPath,'map']]){
    await page.goto(base+url);await expect(page.locator('.app-shell')).toBeVisible();
    if(name==='prediction')await expect(page.locator('.prediction-detail')).toBeVisible();
    if(name==='map')await expect(page.locator('.object-drawer')).toBeVisible();
    if(name==='journal')await page.locator('.journal-filter-trigger').first().click();
    if(['alerts','imports','journal'].includes(name)){
     const td=page.locator('tbody td:not([colspan])').first();await expect(td).toBeVisible();
     await expect.poll(()=>td.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
    }
    if(name==='settings'){
     const before=await page.locator('.settings-card').boundingBox();await page.locator('.notification-panel summary').click();
     const after=await page.locator('.settings-card').boundingBox();expect(after.x).toBeCloseTo(before.x,0);await page.locator('.notification-panel summary').click();
    }
    await save(theme+'-'+name);
   }
  }record('both themes typography journal prediction settings and drawer screenshots');
  await page.goto(base+'/settings');await page.getByRole('button',{name:'Свернуть меню',exact:true}).click();await save('sidebar-collapsed');
  const icon=await page.locator('.sidebar-toggle svg').boundingBox(),button=await page.locator('.sidebar-toggle').boundingBox();
  expect(Math.abs(icon.x+icon.width/2-button.x-button.width/2)).toBeLessThan(1);
  await page.getByRole('button',{name:'Развернуть меню',exact:true}).click();await save('sidebar-expanded');record('sidebar logo and toggle');
  await page.getByRole('button',{name:'Выйти из аккаунта',exact:true}).click();await expect(page.getByRole('button',{name:'Войти',exact:true})).toBeVisible();
  expect((await page.request.get('/api/v1/auth/me')).status()).toBe(401);record('browser logout invalidates session');
  await login('manager','/requests');await page.getByRole('button',{name:'Новая заявка',exact:true}).click();
  await expect(page.getByText(/Ваша роль разрешает только просмотр заявок/)).toBeVisible();record('different role UI restriction');
  await page.goto(base+'/settings');await page.getByRole('button',{name:'Выйти из аккаунта',exact:true}).click();
  expect(result.page_errors).toEqual([]);expect(result.unexpected_server_errors).toEqual([]);result.status='PASS';
 }catch(e){result.status='FAIL';result.failure=String(e);console.error(String(e));await save('failure');process.exitCode=1;}
 finally{fs.writeFileSync(path.join(out,'browser.json'),JSON.stringify(result,null,2)+'\n');await browser.close();}
})();
