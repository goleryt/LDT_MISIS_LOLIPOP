import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';

async function login(page:Page,path='/requests') {
  await page.goto(path);
  await page.getByPlaceholder('Логин',{exact:true}).fill(process.env.TEST_USERNAME ?? 'dispatcher');
  await page.getByLabel('Пароль',{exact:true}).fill(process.env.TEST_PASSWORD ?? '');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

test('fully filled request submits the visible values and records creation history',async({page})=>{
  await login(page);
  await page.getByRole('button',{name:'Новая заявка',exact:true}).click();
  await expect(page.getByRole('button',{name:'Создать заявку',exact:true})).toBeDisabled();
  await expect(page.getByText('Выберите объект — это обязательное поле.')).toBeVisible();
  await page.getByRole('combobox',{name:'Объект',exact:true}).selectOption('1');
  await expect(page.getByText('Заполните тему заявки — это обязательное поле.')).toBeVisible();
  await expect(page.getByRole('combobox',{name:'Датчик',exact:true}).locator('option[value="1"]')).toHaveCount(1);
  await page.getByRole('combobox',{name:'Датчик',exact:true}).selectOption('1');
  await page.getByRole('combobox',{name:'Приоритет',exact:true}).selectOption('high');
  const title=`UI regression ${Date.now()}`;
  await page.getByLabel('Тема',{exact:true}).fill(title);
  await page.getByLabel('Описание',{exact:true}).fill('Проверить состояние оборудования по фактическим данным');
  const button=page.getByRole('button',{name:'Создать заявку',exact:true});
  await expect(button).toBeEnabled();
  const response=page.waitForResponse(r=>r.url().endsWith('/api/v1/requests') && r.request().method()==='POST');
  await button.click();
  const created=await response;
  expect(created.status()).toBe(200);
  expect(created.request().postDataJSON()).toEqual({object_id:1,channel_id:1,title,
    description:'Проверить состояние оборудования по фактическим данным',priority:'high'});
  const row=await created.json();expect(row.status).toBe('new');
  await expect(page.getByText('Заявка создана',{exact:true})).toBeVisible();
  const history=await page.request.get(`/api/v1/requests/${row.id}/history`);
  expect(history.status()).toBe(200);
  expect((await history.json())[0]).toMatchObject({to_status:'new',actor:process.env.TEST_USERNAME ?? 'dispatcher'});
});

test('read-only role sees why a filled request cannot be submitted',async({page})=>{
  await login(page);
  // UI-only role fixture; backend enforcement is tested separately against PostgreSQL.
  await page.route('**/api/v1/auth/me',async route=>{
    const upstream=await route.fetch();
    await route.fulfill({response:upstream,json:{...await upstream.json(),role:'manager'}});
  });
  await page.reload();
  await page.getByRole('button',{name:'Новая заявка',exact:true}).click();
  await page.getByRole('combobox',{name:'Объект',exact:true}).selectOption('1');
  await page.getByLabel('Тема',{exact:true}).fill('Заполненная форма просмотра');
  await expect(page.getByRole('button',{name:'Создать заявку',exact:true})).toBeDisabled();
  await expect(page.getByText(/Ваша роль разрешает только просмотр заявок/)).toBeVisible();
});

test('fully filled isolated draft confirms with its current version',async({page})=>{
  const id=process.env.TEST_DRAFT_REQUEST_ID;
  test.skip(!id,'Requires an ordinary draft fixture in isolated QA; never fabricates ML results');
  await login(page,`/requests?requestId=${id}`);
  const review=page.getByRole('region',{name:`Проверка заявки ${id}`});
  await expect(review).toBeVisible();
  await page.getByLabel('Тема черновика',{exact:true}).fill(' ');
  await expect(page.getByText('Заполните тему черновика — это обязательное поле.')).toBeVisible();
  await page.getByLabel('Тема черновика',{exact:true}).fill('Проверено диспетчером: заполнены все поля');
  await page.getByRole('textbox',{name:'Описание черновика',exact:true}).fill('Техническая проверка формы, без нового ML-результата');
  await page.getByRole('combobox',{name:'Приоритет черновика',exact:true}).selectOption('high');
  if(process.env.UI_SCREENSHOT_DIR) {
    await mkdir(process.env.UI_SCREENSHOT_DIR,{recursive:true});
    await review.screenshot({path:`${process.env.UI_SCREENSHOT_DIR}/draft-filled.png`,animations:'disabled'});
  }
  const response=page.waitForResponse(r=>r.url().endsWith(`/api/v1/requests/${id}`) && r.request().method()==='PATCH');
  await page.getByRole('button',{name:'Подтвердить заявку',exact:true}).click();
  const changed=await response;expect(changed.status()).toBe(200);
  expect(changed.request().postDataJSON().expected_updated_at).toBeTruthy();
  expect((await changed.json()).status).toBe('new');
  await expect(page.getByText('Черновик подтверждён: заявка создана',{exact:true})).toBeVisible();
  const history=await (await page.request.get(`/api/v1/requests/${id}/history`)).json();
  expect(history.at(-1)).toMatchObject({from_status:'draft',to_status:'new'});
});

test('list typography and opaque filters remain readable in both themes',async({page})=>{
  await login(page);
  for(const theme of ['dark','light']) {
    await page.evaluate(value=>localStorage.setItem('settings.theme',value),theme);
    for(const path of ['/alarms','/imports','/events']) {
      await page.goto(path);
      const cell=page.locator('tbody td').first();await expect(cell).toBeVisible();
      expect(await cell.evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
      const panel=page.locator('.alarms-panel,.history-card,.journal-board').first();
      expect(await panel.evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
      if(path==='/events') {
        await page.locator('.journal-filter-trigger').first().click();
        const filter=page.locator('.journal-filter-popover');await expect(filter).toBeVisible();
        expect(await filter.evaluate(el=>getComputedStyle(el).backgroundColor)).not.toBe('rgba(0, 0, 0, 0)');
        const text=await filter.locator('button').last().evaluate(el=>{
          const s=getComputedStyle(el);return {color:s.color,background:s.backgroundColor};
        });
        expect(text.color).not.toBe(text.background);
      }
    }
  }
});

test('map resize, wheel bursts and pinch preserve finite zoom and viewport panels',async({page})=>{
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await login(page,'/?objectId=1&channelId=1');
  const map=page.locator('.schematic-map-svg');
  const drawer=page.locator('.object-drawer');
  await expect(drawer).toBeVisible();
  for(const [width,height] of [[1920,1080],[1440,900],[1280,800],[1152,768],[1024,700]]) {
    await page.setViewportSize({width,height});
    await expect.poll(async()=>await page.locator('.map-page').evaluate(el=>el.getBoundingClientRect().bottom)).toBeLessThanOrEqual(height+1);
    const bounds=await drawer.boundingBox();expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);expect(bounds!.x+bounds!.width).toBeLessThanOrEqual(width+1);
    expect(bounds!.y+bounds!.height).toBeLessThanOrEqual(height+1);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await expect(page.locator('.drawer-close')).toBeInViewport();
    await expect(page.locator('.schematic-map-controls')).toBeInViewport();
  }
  await page.setViewportSize({width:1280,height:800});
  const drawerBefore=await drawer.boundingBox();
  const captured=await map.evaluate(el=>{
    const rect=el.getBoundingClientRect();const results=[];
    for(const deltaMode of [0,1,2]) for(const ctrlKey of [false,true]) {
      for(let i=0;i<40;i++) {
        const event=new WheelEvent('wheel',{bubbles:true,cancelable:true,ctrlKey,deltaMode,deltaY:-3,
          clientX:rect.left+100,clientY:rect.top+100});
        el.dispatchEvent(event);results.push(event.defaultPrevented);
      }
    }
    for(const value of [NaN,Infinity]) {
      const invalid=new WheelEvent('wheel',{bubbles:true,cancelable:true});
      Object.defineProperty(invalid,'deltaY',{value});el.dispatchEvent(invalid);
    }
    return results;
  });
  expect(captured.every(Boolean)).toBe(true);
  await expect.poll(async()=>Number((await map.getAttribute('viewBox'))!.split(' ')[2])).toBe(300);
  expect((await map.getAttribute('viewBox'))!.split(' ').map(Number).every(Number.isFinite)).toBe(true);
  expect((await drawer.boundingBox())!.width).toBeCloseTo(drawerBefore!.width,0);
  await expect(page.locator('.schematic-map-controls button').first()).toBeDisabled();
  await page.locator('.schematic-map-controls button').last().click();
  await page.locator('.schematic-map-controls button').first().click();
  await page.locator('.schematic-reset-button').click();
  await expect(map).toHaveAttribute('viewBox','0 0 1200 820');
  await map.hover({position:{x:80,y:200}});await page.mouse.wheel(0,-100);
  await expect(map).not.toHaveAttribute('viewBox','0 0 1200 820');
  await page.locator('.drawer-close').click();await expect(drawer).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('prediction cards preserve stored proxy values and contrast in light and dark',async({page})=>{
  await login(page,'/predictions');
  const stored=await (await page.request.get('/api/v1/predictions')).json();
  test.skip(!stored.length,'Needs an existing stored prediction; never creates ML output');
  for(const theme of ['dark','light']) {
    await page.evaluate(value=>localStorage.setItem('settings.theme',value),theme);
    await page.goto(`/predictions?predictionId=${stored[0].id}`);
    await expect(page.getByRole('heading',{name:`Прогноз №${stored[0].id}`,exact:true})).toBeVisible();
    await expect(page.locator('.prediction-summary')).toContainText(`${(stored[0].probability*100).toFixed(1)}%`);
    for(const target of ['.status-notice','.prediction-card p','.prediction-summary dt']) {
      const contrast=await page.locator(target).first().evaluate(el=>{
        const rgb=(value:string)=>(value.match(/[\d.]+/g)??[]).slice(0,3).map(Number);
        const lum=(values:number[])=>values.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;})
          .reduce((a,v,i)=>a+v*[.2126,.7152,.0722][i],0);
        let surface:Element|null=el;
        while(surface && ['rgba(0, 0, 0, 0)','transparent'].includes(getComputedStyle(surface).backgroundColor)) surface=surface.parentElement;
        const a=lum(rgb(getComputedStyle(el).color));const b=lum(rgb(getComputedStyle(surface!).backgroundColor));
        return (Math.max(a,b)+.05)/(Math.min(a,b)+.05);
      });
      expect(contrast,`${theme} ${target}`).toBeGreaterThanOrEqual(4.5);
    }
  }
});

test('settings stay centered under notification overlay and sidebar icons align',async({page})=>{
  await login(page,'/settings');
  const logo=(await page.locator('.brand-mark').boundingBox())!;
  const arrow=(await page.locator('.sidebar-toggle svg').boundingBox())!;
  expect(Math.abs(logo.x+logo.width/2-arrow.x-arrow.width/2)).toBeLessThan(1);
  const card=page.locator('.settings-card');const before=await card.boundingBox();
  await page.locator('.notification-panel summary').click();
  const after=await card.boundingBox();
  expect(after!.x).toBeCloseTo(before!.x,0);expect(after!.y).toBeCloseTo(before!.y,0);
  await page.locator('.notification-panel summary').click();
  await page.getByRole('button',{name:'Свернуть меню',exact:true}).click();
  await expect(page.locator('.sidebar')).toHaveClass(/sidebar-collapsed/);
  await expect.poll(async()=>{
    const icon=(await page.locator('.sidebar-toggle svg').boundingBox())!;
    const button=(await page.locator('.sidebar-toggle').boundingBox())!;
    return Math.abs(icon.x+icon.width/2-button.x-button.width/2);
  }).toBeLessThan(1);
  const brand=await page.locator('.brand-mark').evaluate(el=>({cursor:getComputedStyle(el).cursor,background:getComputedStyle(el).backgroundImage}));
  expect(brand).toEqual({cursor:'default',background:'none'});
  expect(await page.locator('.sidebar-footer').evaluate(el=>parseFloat(getComputedStyle(el).paddingTop))).toBeGreaterThanOrEqual(16);
  await page.getByRole('button',{name:'Развернуть меню',exact:true}).click();
});

test('requested visual matrix for both themes and reduced desktop',async({page})=>{
  test.skip(process.env.RUN_UI_VISUAL!=='true','Opt-in visual evidence on isolated QA');
  test.setTimeout(180000);
  const dir=process.env.UI_SCREENSHOT_DIR ?? 'test-results/ui-fixes';await mkdir(dir,{recursive:true});
  const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await login(page);
  const stored=await (await page.request.get('/api/v1/predictions')).json();
  const routes=[['alarms','/alarms'],['imports','/imports'],['journal','/events'],
    ['predictions',`/predictions${stored.length?`?predictionId=${stored[0].id}`:''}`],['settings','/settings'],['map','/'],['request','/requests']];
  const measurements=[];
  for(const theme of ['dark','light']) for(const [width,height] of [[1280,800],[1440,900]]) {
    await page.setViewportSize({width,height});
    await page.evaluate(value=>localStorage.setItem('settings.theme',value),theme);
    for(const [name,path] of routes) {
      await page.goto(path);await expect(page.locator('.app-shell')).toBeVisible();
      if(name==='predictions' && stored.length) await expect(page.locator('.prediction-summary')).toBeVisible();
      if(name==='alarms') await expect(page.locator('.alarms-table tbody tr').first()).toBeVisible();
      if(name==='imports') await expect(page.locator('.imports-table tbody tr').first()).toBeVisible();
      if(name==='settings') await expect(page.locator('.settings-card')).toBeVisible();
      if(name==='map') await expect(page.locator('.map-summary strong').first()).not.toHaveText('…');
      if(name==='journal') {
        await expect(page.locator('.journal-table tbody .event-row-clickable').first()).toBeVisible();
        await page.locator('.journal-filter-trigger').first().click();
      }
      if(name==='request') {
        await page.getByRole('button',{name:'Новая заявка',exact:true}).click();
        await page.getByRole('combobox',{name:'Объект',exact:true}).selectOption('1');
        await page.getByLabel('Тема',{exact:true}).fill('Проверка оборудования');
        await page.getByLabel('Описание',{exact:true}).fill('Проверить фактическое состояние');
        await page.getByRole('button',{name:'Создать заявку',exact:true}).scrollIntoViewIfNeeded();
      }
      await page.screenshot({path:`${dir}/${theme}-${width}-${name}.png`,animations:'disabled'});
      if(name==='predictions' && stored.length) {
        await page.getByRole('heading',{name:'Рекомендация для проверки',exact:true}).scrollIntoViewIfNeeded();
        await page.screenshot({path:`${dir}/${theme}-${width}-prediction-decision.png`,animations:'disabled'});
      }
      const dimensions=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth}));
      expect(dimensions.document).toBeLessThanOrEqual(width);
      measurements.push({theme,width,height,path,...dimensions});
    }
  }
  await page.setViewportSize({width:1024,height:700});
  await page.goto('/?objectId=1&channelId=1');await expect(page.locator('.object-drawer')).toBeVisible();
  await page.screenshot({path:`${dir}/reduced-1024-map-drawer.png`});
  await page.setViewportSize({width:1920,height:1080});
  await page.screenshot({path:`${dir}/wide-1920-map-drawer.png`});
  await page.goto('/settings');
  await expect(page.locator('.settings-card')).toBeVisible();
  await page.screenshot({path:`${dir}/sidebar-expanded.png`,animations:'disabled'});
  await page.getByRole('button',{name:'Свернуть меню',exact:true}).click();
  await expect(page.locator('.sidebar')).toHaveClass(/sidebar-collapsed/);
  await page.screenshot({path:`${dir}/sidebar-collapsed.png`,animations:'disabled'});
  expect(errors).toEqual([]);
  await writeFile(`${dir}/matrix.json`,JSON.stringify({measurements,pageerrors:errors},null,2));
});
