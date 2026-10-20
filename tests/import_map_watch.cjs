// Local-only browser observer for concurrent upload QA; no production URL or inference.
const fs=require('fs'),path=require('path'),{createRequire}=require('module');
const root=path.resolve(__dirname,'..'),{chromium,expect}=createRequire(path.join(root,'frontend/package.json'))('@playwright/test');
if(process.env.RUN_IMPORT_LOAD!=='true')throw Error('Explicit local import QA opt-in required');
const credentials=fs.realpathSync(process.env.IMPORT_LOAD_ACCESS_FILE),relative=path.relative(root,credentials);
if(!relative.startsWith('..'+path.sep)&&!path.isAbsolute(relative))throw Error('Credentials must remain outside Git');
const out=process.env.IMPORT_MAP_OUTPUT,stop=process.env.IMPORT_MAP_STOP_FILE;
if(!out||!stop)throw Error('Explicit output and completion marker required');
(async()=>{
 const browser=await chromium.launch({channel:'chrome'}),context=await browser.newContext({baseURL:'http://127.0.0.1:18094',viewport:{width:1280,height:800}}),page=await context.newPage();
 const result={browser:browser.version(),url:'http://127.0.0.1:18094',started_at:new Date().toISOString(),iterations:0,page_errors:[],status:'FAIL'};
 page.on('pageerror',e=>result.page_errors.push(e.message));
 try{
  const a=JSON.parse(fs.readFileSync(credentials,'utf8'));await page.goto('/');
  await page.getByPlaceholder('Логин',{exact:true}).fill(a.username);await page.getByLabel('Пароль',{exact:true}).fill(a.password);await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.locator('.map-summary strong').first()).not.toHaveText('…');
  if(process.env.IMPORT_MAP_READY_FILE)fs.writeFileSync(process.env.IMPORT_MAP_READY_FILE,'ready\n');
  const until=Date.now()+30*60*1000;
  while(!fs.existsSync(stop)&&Date.now()<until){
   await expect(page.locator('.schematic-map-svg')).toBeVisible();
   await page.getByRole('button',{name:'Приблизить карту',exact:true}).click();await page.getByRole('button',{name:'Отдалить карту',exact:true}).click();
   expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(1280);result.iterations++;
   await page.waitForTimeout(2500);
  }
  expect(fs.existsSync(stop),'Load runner must finish before observer timeout').toBe(true);expect(result.page_errors).toEqual([]);result.status='PASS';
 }catch(e){result.error=String(e);process.exitCode=1;}
 finally{result.finished_at=new Date().toISOString();fs.writeFileSync(out,JSON.stringify(result,null,2)+'\n');await browser.close();console.log(JSON.stringify(result));}
})();
