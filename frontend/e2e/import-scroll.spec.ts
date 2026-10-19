import {test,expect} from '@playwright/test';

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
