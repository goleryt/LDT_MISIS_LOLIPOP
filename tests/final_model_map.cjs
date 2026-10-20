// Opt-in browser acceptance against genuinely persisted model results, no stubs/inference.
const fs=require('node:fs'),path=require('node:path'),{createRequire}=require('node:module');
const root=path.resolve(__dirname,'..'),requireUI=createRequire(path.join(root,'frontend/package.json'));
const {chromium,expect}=requireUI('@playwright/test');
if(process.env.RUN_FINAL_MODEL_MAP!=='true')throw new Error('Explicit RUN_FINAL_MODEL_MAP=true required');
const base=process.env.BASE_URL??'http://127.0.0.1:18112';
const host=new URL(base).hostname,local=['127.0.0.1','localhost'].includes(host);
if(!local&&(host!=='ldt-demo-production.up.railway.app'||process.env.ALLOW_PUBLIC_FINAL_MAP!=='true'))throw new Error('Unrecognized acceptance target');
const credentialFile=path.resolve(process.env.REMOTE_ACCESS_FILE??'');
if(!process.env.REMOTE_ACCESS_FILE||!path.relative(root,credentialFile).startsWith('..'+path.sep))throw new Error('Credentials must be outside Git');
const access=JSON.parse(fs.readFileSync(credentialFile,'utf8')).manager;
const out=path.resolve(process.env.FINAL_MAP_OUTPUT??path.join(root,'../final-product-private/map-matrix'));
fs.mkdirSync(out,{recursive:true});
const report={base_url:base,environment:local?'isolated local RC with restored public data':'public HTTPS',date:new Date().toISOString(),checks:[],screenshots:[],page_errors:[],server_errors:[]};
async function main(){
 const browser=await chromium.launch({channel:'chrome',headless:true});report.browser=browser.version();report.os=process.platform;
 try{
  for(const theme of ['dark','light']){
   const context=await browser.newContext({baseURL:base,viewport:{width:1440,height:900}});
   await context.addInitScript(t=>localStorage.setItem('settings.theme',t),theme);
   const page=await context.newPage();page.setDefaultTimeout(20000);
   page.on('pageerror',e=>report.page_errors.push(e.message));
   page.on('response',r=>{if(r.status()>=500&&r.url().startsWith(base+'/api/'))report.server_errors.push({path:new URL(r.url()).pathname,status:r.status()});});
   await page.goto('/?mapMode=forecasts');
   await page.getByPlaceholder('Логин',{exact:true}).fill(access.username);
   await page.getByLabel('Пароль',{exact:true}).fill(access.password);
   await page.getByRole('button',{name:'Войти',exact:true}).click();
   const controls=page.getByRole('region',{name:'Фильтры прогнозов карты'});
   await expect(controls).toBeVisible();await expect(controls.locator('.map-forecast-object-links button').first()).toBeVisible();
   const response=await context.request.get('/api/v1/map/forecasts');expect(response.status()).toBe(200);
   const data=await response.json();const workers=[...new Set(data.forecasts.filter(r=>r.available&&r.bound).map(r=>r.worker))].sort();
   expect(workers).toEqual(['fire','gas','sensor_failure']);expect(data.automated_action_allowed).toBe(false);
   if(theme==='dark'){
    report.actual_forecasts=data.forecasts;report.scenario_run=data.scenario_run;
    fs.writeFileSync(path.join(out,'map-api.json'),JSON.stringify(data,null,2));
   }
   const allObjects=(await(await context.request.get('/api/v1/map/objects')).json());
   async function screen(name){const file=`${theme}-${page.viewportSize().width}-${name}.png`;await page.screenshot({path:path.join(out,file)});report.screenshots.push(file);}
   for(const [width,height] of [[1024,768],[1280,800],[1440,900],[1920,1080]]){
    await page.setViewportSize({width,height});await page.goto('/?mapMode=forecasts');
    await expect(controls.locator('.map-forecast-object-links button').first()).toBeVisible();
    await expect(page.locator('.map-legend')).not.toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    await screen('all-models');
    for(const kind of ['gas','sensor_failure','fire']){
     await controls.getByLabel('Модель',{exact:true}).selectOption(kind);
     await expect(page).toHaveURL(new RegExp('forecastType='+kind));
     await controls.locator('.map-forecast-object-links button').first().click();
     const drawer=page.locator('.object-drawer');await expect(drawer).toBeVisible();
     const expected=data.forecasts.find(r=>r.worker===kind&&r.available&&r.bound);expect(expected).toBeTruthy();
     await expect(drawer.locator('.map-forecast-card.'+kind).first()).toBeVisible();
     await expect(drawer.locator('.map-forecast-card').first()).toHaveClass(new RegExp(kind));
     const toggle=await page.getByRole('group',{name:'Режим карты'}).boundingBox(),reset=await page.getByRole('button',{name:'Показать все',exact:true}).boundingBox();
     expect(toggle.x<reset.x+reset.width&&toggle.x+toggle.width>reset.x&&toggle.y<reset.y+reset.height&&toggle.y+toggle.height>reset.y).toBe(false);
     expect(expected.score).not.toBeNull();
     const before=await drawer.boundingBox();
     for(const deltaMode of [0,1,2])await page.locator('.schematic-map-svg').dispatchEvent('wheel',{bubbles:true,cancelable:true,ctrlKey:true,deltaMode,deltaY:-5,clientX:width/2,clientY:height/2});
     expect(await page.locator('.schematic-map-svg').getAttribute('viewBox')).not.toMatch(/NaN|Infinity/);
     const after=await drawer.boundingBox();expect(Math.abs(before.width-after.width)).toBeLessThan(1);
     await screen(kind);
     if(width===1440){
      const link=drawer.locator('.map-forecast-card.'+kind).first().getByRole('link',{name:'Детали, решение и черновик заявки',exact:true});
      const target=await link.getAttribute('href');await link.click();await expect(page).toHaveURL(base+target);
      if(kind==='gas')await expect(page.locator('.prediction-detail')).toBeVisible();
      else await expect(page.getByRole('article',{name:new RegExp('№'+new URL(target,base).searchParams.get('scenarioId')+'$')})).toContainText('Режим только чтения');
      await page.goBack();await expect(page.locator('.object-drawer')).toBeVisible();
     }
     await drawer.locator('.drawer-close').click();await expect(drawer).not.toBeVisible();
    }
    await controls.getByLabel('Модель',{exact:true}).selectOption('multiple');
    await expect(controls.locator('.map-forecast-object-links button')).toHaveCount(1);
    await controls.getByLabel('Доступность',{exact:true}).selectOption('unavailable');
    const missing=data.forecasts.filter(r=>!r.available&&r.bound);
    if(!missing.length)await expect(controls).toContainText('По выбранным фильтрам результатов нет');
    report.checks.push({theme,width,height,result:'PASS',no_overflow:true,three_models:true,low_scores_preserved:true,multiple_filter:true,pinch_finite:true,drawer_not_scaled:true});
   }
   const ordinary=allObjects.find(o=>!data.forecasts.some(r=>r.object_id===o.object_id));
   if(ordinary){await page.setViewportSize({width:1440,height:900});await page.goto('/?mapMode=forecasts&objectId='+ordinary.object_id);await expect(page.locator('.object-drawer')).toContainText('У объекта нет результатов');await screen('no-result');}
   await context.close();
  }
  expect(report.page_errors).toEqual([]);expect(report.server_errors).toEqual([]);report.status='PASS';
 }finally{await browser.close();fs.writeFileSync(path.join(out,'result.json'),JSON.stringify(report,null,2));}
}
main().then(()=>process.stdout.write(JSON.stringify({status:report.status,checks:report.checks.length,screenshots:report.screenshots.length,browser:report.browser,environment:report.environment})+'\n')).catch(e=>{process.stderr.write(String(e.message).slice(0,1800)+'\n');process.exitCode=1;});
