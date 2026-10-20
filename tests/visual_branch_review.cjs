// Real persisted QA/demo data; read-only UI matrix, no inference or fabricated scores.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),{createRequire}=require('module');
const root=path.resolve(__dirname,'..'),{chromium,expect}=createRequire(path.join(root,'frontend/package.json'))('@playwright/test');
if(process.env.RUN_VISUAL_BRANCH!=='true')throw Error('Explicit RUN_VISUAL_BRANCH=true required');
const base=process.env.BASE_URL,phase=process.env.VISUAL_PHASE,out=process.env.VISUAL_OUTPUT;
if(!base||!['before','after','remote'].includes(phase)||!out)throw Error('Explicit URL, phase and output required');
const credentialPath=fs.realpathSync(process.env.REMOTE_ACCESS_FILE),relative=path.relative(root,credentialPath);
if(!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative))throw Error('Credentials must stay outside Git');
const accounts=JSON.parse(fs.readFileSync(credentialPath,'utf8'));
fs.mkdirSync(out,{recursive:true});
const result={phase,base,date:new Date().toISOString(),screens:[],page_errors:[],checks:[]};
const pass=(name,details={})=>result.checks.push({name,status:'PASS',...details});
const fingerprint=data=>crypto.createHash('sha256').update(JSON.stringify(data)).digest('hex');
(async()=>{
 const browser=await chromium.launch({channel:'chrome'});result.browser=browser.version();
 try{
  for(const theme of ['dark','light'])for(const [width,height] of [[1024,768],[1280,800],[1440,900],[1920,1080]]){
   const context=await browser.newContext({baseURL:base,viewport:{width,height}});
   await context.addInitScript(t=>localStorage.setItem('settings.theme',t),theme);
   const page=await context.newPage();page.setDefaultTimeout(20000);page.on('pageerror',e=>result.page_errors.push(e.message));
   const save=async(name,selector)=>{
    if(name!=='login')await expect(page.locator('.notification-panel summary')).not.toContainText('загрузка');
    await page.evaluate(()=>document.fonts.ready);await expect(page.locator(selector).first()).toBeVisible();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const filename=`${phase}-${theme}-${width}-${name}.png`;
    await page.screenshot({path:path.join(out,filename),animations:'disabled'});
    const geometry=await page.locator(selector).first().evaluate(el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,background:s.backgroundColor,color:s.color,font:s.fontSize,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight};});
    result.screens.push({theme,width,height,name,file:filename,geometry});
   };
   await page.goto('/');await expect(page.getByRole('button',{name:'Войти',exact:true})).toBeVisible();await save('login','.auth-card');
   await page.getByPlaceholder('Логин',{exact:true}).fill(accounts.admin.username);
   await page.getByLabel('Пароль',{exact:true}).fill(accounts.admin.password);
   await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page.locator('.app-shell')).toBeVisible();
   const me=await (await page.request.get('/api/v1/auth/me')).json();
   const predictions=await (await page.request.get('/api/v1/predictions')).json();
   const scenarios=await (await page.request.get('/api/v1/predictions/scenarios')).json();
   const math=fingerprint({gas:predictions.map(p=>[p.id,p.probability,p.model_version,p.calculated_at,p.ml_metadata]),scenario:scenarios.forecasts.map(f=>[f.id,f.payload])});
   if(result.math_sha256)expect(math).toBe(result.math_sha256);else result.math_sha256=math;
   result.model_counts={gas:predictions.length,scenario:scenarios.forecasts.length};
   const target=predictions.find(p=>p.object_id&&p.channel_id);expect(target).toBeTruthy();
   const scenes=[['settings','/settings','.settings-card'],['journal','/events','.journal-board'],['reports','/reports','.prediction-detail'],['imports','/imports','.history-card']];
   if(phase!=='before')scenes.push(['dashboard','/','.schematic-map-svg'],['objects','/objects','.objects-panel'],['alarms','/alarms','.alarms-panel'],['object',`/?objectId=${target.object_id}`,'.object-drawer'],['sensor-history',`/?objectId=${target.object_id}&channelId=${target.channel_id}`,'.sensor-detail-panel'],['predictions','/predictions','.scenario-section'],['gas-detail',`/predictions?predictionId=${target.id}`,'.prediction-detail'],['requests','/requests','.requests-panel']);
   for(const [name,url,selector] of scenes){
    await page.goto(url);await expect(page.locator(selector).first()).toBeVisible();
    if(['objects','alarms'].includes(name))await expect(page.locator('tbody td:not([colspan])').first()).toBeVisible();
    if(name==='dashboard')await expect(page.locator('.map-summary strong').first()).not.toHaveText('…');
    if(name==='requests')await expect(page.locator('.requests-table tbody tr').first()).toBeVisible();
    if(name==='journal'){
     await expect(page.locator('tbody td:not([colspan])').first()).toBeVisible();
     await page.locator('.journal-filter-trigger').first().click();await expect(page.locator('.journal-filter-popover')).toBeVisible();
    }
    if(name==='imports'){
     await expect(page.locator('tbody tr').last()).toBeAttached();await page.mouse.move(width-70,height-80);
     for(let i=0;i<12;i++)await page.mouse.wheel(0,650);
     await expect(page.locator('tbody tr').last()).toBeInViewport();
    }
    if(name==='predictions')await expect(page.locator('.scenario-forecast-card')).toHaveCount(3);
    if(name==='sensor-history')await expect(page.getByRole('heading',{name:'Последние события',exact:true})).toBeVisible();
    await save(name,selector);
    if(name==='predictions'){
     for(let i=0;i<3;i++){const card=page.locator('.scenario-forecast-card').nth(i);await card.scrollIntoViewIfNeeded();await save('scenario-'+i,'.scenario-forecast-card');}
    }
   }
   if(phase!=='before'){
    await page.goto('/settings');const x=(await page.locator('.settings-card').boundingBox()).x;
    await page.locator('.notification-panel summary').click();await expect(page.locator('.settings-card')).toBeVisible();
    expect((await page.locator('.settings-card').boundingBox()).x).toBeCloseTo(x,0);await save('notifications','.notification-panel');
    await page.goto('/reports');const beam=await page.locator('.app-shell').evaluate(e=>getComputedStyle(e).backgroundImage);
    await page.getByRole('button',{name:'Свернуть меню',exact:true}).click();
    await expect(page.locator('.sidebar-collapsed')).toBeVisible();await expect.poll(()=>page.locator('.app-shell').evaluate(e=>getComputedStyle(e).backgroundImage)).toBe(beam);
    expect(await page.locator('.app-workspace').evaluate(e=>getComputedStyle(e).backgroundImage)).toBe('none');
   }
   expect((await page.request.post('/api/v1/auth/logout',{headers:{'X-CSRF-Token':me.csrf_token}})).status()).toBe(200);
   await context.close();console.log(`PASS ${phase} ${theme} ${width}x${height}`);
  }
  expect(result.page_errors).toEqual([]);result.status='PASS';pass('real data desktop matrix without page overflow or runtime errors');
 }catch(e){result.status='FAIL';result.error=String(e);console.error(String(e));process.exitCode=1;}
 finally{fs.writeFileSync(path.join(out,'matrix.json'),JSON.stringify(result,null,2)+'\n');await browser.close();}
})();
