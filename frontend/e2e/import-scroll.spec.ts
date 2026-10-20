import {test,expect} from '@playwright/test';

for(const [status,message] of [[429,'Сервис импорта занят.'],[409,'Этот файл уже обрабатывается.'],[408,'Превышено время обработки.']] as const){
  test(`import backpressure ${status} explains retry and retains selected file`,async({page})=>{
    await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'import-review',role:'dispatcher',csrf_token:'layout-fixture'}}));
    await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
    await page.route('**/api/v1/imports',r=>r.fulfill({json:[]}));
    let busy=true;
    await page.route('**/api/v1/imports/events?*',r=>r.fulfill({status:busy?status:200,headers:{'Retry-After':'3'},
      json:busy?{detail:{code:'IMPORT_CAPACITY_BUSY'}}:{status:'completed',already_imported:false,import_id:1}}));
    await page.goto('/imports');
    await page.locator('input[type=file]').setInputFiles({name:'retry.csv',mimeType:'text/csv',buffer:Buffer.from('synthetic fixture')});
    const submit=page.getByRole('button',{name:'Начать импорт',exact:true});await submit.click();
    await expect(page.getByRole('alert')).toContainText(message);await expect(submit).toBeEnabled();
    await expect(page.locator('input[type=file]')).not.toHaveValue('');
    busy=false;await submit.click();
    await expect(page.getByText('Файл успешно обработан и зарегистрирован.',{exact:true})).toBeVisible();
    await expect(page.locator('input[type=file]')).toHaveValue('');
  });
}

// Read-only transport fixtures isolate layout from database content and credentials.
for(const theme of ['dark','light']) for(const [width,height] of [[1024,768],[1280,800],[1440,900],[1920,1080]]) {
  test(`imports user wheel reaches last row ${theme} ${width}x${height}`,async({page})=>{
    await page.setViewportSize({width,height});
    const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
    await page.addInitScript(theme=>localStorage.setItem('settings.theme',theme),theme);
    await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'layout-review',role:'dispatcher',csrf_token:'layout-fixture'}}));
    await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
    await page.route('**/api/v1/imports',r=>r.fulfill({json:Array.from({length:30},(_,i)=>({
      id:i+1,file_name:`layout-row-${i+1}.json`,file_sha256:'0'.repeat(64),import_type:'events_journal',status:'completed',
      processed_rows:1,inserted_rows:1,skipped_rows:0,file_size_bytes:150,error_message:null,
      started_at:'2026-10-19T09:00:00Z',completed_at:'2026-10-19T09:00:01Z'}))}));
    await page.goto('/imports');
    const last=page.getByText('layout-row-30.json',{exact:true});await expect(last).toBeAttached();
    const imports=page.locator('.imports-page');
    await expect.poll(()=>imports.evaluate(e=>e.clientHeight)).toBeGreaterThan(0);
    await page.mouse.move(width-90,height-100);
    for(let i=0;i<12;i++) await page.mouse.wheel(0,650);
    await expect(last).toBeInViewport();
    expect(await imports.evaluate(e=>e.scrollTop)).toBeGreaterThan(500);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await page.getByRole('link',{name:'Настройки',exact:true}).click();
    await page.getByRole('link',{name:'Импорт данных',exact:true}).click();
    await page.mouse.move(width-90,height-100);for(let i=0;i<12;i++) await page.mouse.wheel(0,650);
    await expect(last).toBeInViewport();expect(errors).toEqual([]);
    if(process.env.UI_SCREENSHOT_DIR) await page.screenshot({path:`${process.env.UI_SCREENSHOT_DIR}/imports-scroll-${theme}-${width}.png`});
  });
}

test('import loading and failure remain reachable by wheel and recover',async({page})=>{
  await page.setViewportSize({width:1024,height:768});
  await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'layout-review',role:'dispatcher',csrf_token:'layout-fixture'}}));
  await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
  let release:()=>void=()=>{};const pending=new Promise<void>(resolve=>{release=resolve;});let fail=true;
  await page.route('**/api/v1/imports',async r=>{
    if(fail){await pending;await r.fulfill({status:500,json:{detail:'deliberately unavailable transport'}});}
    else await r.fulfill({json:[]});
  });
  await page.goto('/imports');
  await expect(page.locator('.imports-page')).toBeVisible();
  await page.mouse.move(900,650);await page.mouse.wheel(0,1300);
  await expect(page.getByText('Загрузка истории...',{exact:true})).toBeInViewport();
  release();
  const notice=page.locator('.notice.error');await expect(notice).toBeInViewport();
  await expect(notice).not.toContainText('deliberately unavailable transport');
  fail=false;
  await page.mouse.wheel(0,-3000);
  await page.getByRole('button',{name:'Обновить',exact:true}).click();
  await page.mouse.wheel(0,1500);
  await expect(page.getByText('Импортов пока нет',{exact:true})).toBeInViewport();
});

test('late import registry failure cannot overwrite refresh after a successful upload',async({page})=>{
  await page.route('**/api/v1/auth/me',r=>r.fulfill({json:{username:'layout-review',role:'dispatcher',csrf_token:'layout-fixture'}}));
  await page.route('**/api/v1/notifications?*',r=>r.fulfill({json:[]}));
  let release:()=>void=()=>{};const pending=new Promise<void>(resolve=>{release=resolve;});let uploaded=false;
  await page.route('**/api/v1/imports',async r=>{
    if(!uploaded){await pending;await r.fulfill({status:500,json:{detail:'old request failed'}});}
    else await r.fulfill({json:[]});
  });
  await page.route('**/api/v1/imports/events?*',r=>{uploaded=true;return r.fulfill({json:{import_id:1,status:'completed',already_imported:true,file_sha256:'0'.repeat(64)}});});
  await page.goto('/imports');
  await page.locator('input[type=file]').setInputFiles({name:'layout-only.json',mimeType:'application/json',buffer:Buffer.from('[]')});
  await page.getByRole('button',{name:'Начать импорт',exact:true}).click();
  await expect(page.getByText('Импортов пока нет',{exact:true})).toBeVisible();
  const oldResponse=page.waitForResponse(r=>r.url().endsWith('/api/v1/imports')&&r.status()===500);
  release();
  await (await oldResponse).finished();
  await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>resolve())));
  await expect(page.locator('.notice.success')).toContainText('Этот файл уже был успешно импортирован ранее.');
  await expect(page.locator('.notice.error')).toHaveCount(0);
});
