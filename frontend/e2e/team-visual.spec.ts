import {test,expect} from '@playwright/test';

async function login(page:import('@playwright/test').Page) {
  await page.getByPlaceholder('Логин',{exact:true}).fill(process.env.TEST_USERNAME??'dispatcher');
  await page.getByLabel('Пароль',{exact:true}).fill(process.env.TEST_PASSWORD??'');
  await page.getByRole('button',{name:'Войти',exact:true}).click();
  await expect(page.locator('.app-shell')).toBeVisible();
}

for(const theme of ['dark','light'])test(`${theme}: white utility cards preserve native controls, focus and lazy navigation`,async({page})=>{
  await page.addInitScript(t=>localStorage.setItem('settings.theme',t),theme);
  await page.goto('/');
  const card=page.locator('.auth-card'),input=page.getByPlaceholder('Логин',{exact:true});
  await expect(card).toHaveCSS('background-color','rgb(255, 255, 255)');
  await expect(card).toHaveCSS('color-scheme','light');
  const contrast=await input.evaluate(el=>{
    const colors=[getComputedStyle(el,'::placeholder').color,'rgb(255,255,255)'];
    const luminance=colors.map(c=>c.match(/[\d.]+/g)!.slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4)).map(c=>c[0]*.2126+c[1]*.7152+c[2]*.0722);
    return (Math.max(...luminance)+.05)/(Math.min(...luminance)+.05);
  });
  expect(contrast).toBeGreaterThanOrEqual(4.5);
  await page.keyboard.press('Tab');await expect(input).toBeFocused();
  await expect(input).toHaveCSS('outline-style','solid');
  await login(page);
  await page.goto('/settings');await expect(page.locator('.settings-card')).toHaveCSS('color-scheme','light');
  const x=(await page.locator('.settings-card').boundingBox())!.x;
  await page.locator('.notification-panel summary').click();
  expect((await page.locator('.settings-card').boundingBox())!.x).toBeCloseTo(x,0);
  await page.goto('/events');await expect(page.locator('.journal-page')).toHaveCSS('color-scheme','light');
  await page.locator('.journal-filter-trigger').first().click();
  await expect(page.locator('.journal-filter-popover')).toHaveCSS('background-color','rgb(243, 244, 248)');
  await page.goto('/settings');await expect(page.locator('.settings-card')).toHaveCSS('background-color','rgb(255, 255, 255)');
});

test('reports keep two balanced date columns and explain every disabled download',async({page})=>{
  await page.setViewportSize({width:1440,height:900});await page.goto('/reports');await login(page);
  const start=page.getByLabel('С',{exact:true}),end=page.getByLabel('По',{exact:true});
  const a=(await start.boundingBox())!,b=(await end.boundingBox())!;
  expect(a.y).toBeCloseTo(b.y,0);expect(a.width).toBeCloseTo(b.width,0);expect(b.x).toBeGreaterThan(a.x+a.width);
  await start.fill('2026-10-22');await end.fill('2026-10-20');
  await expect(page.getByRole('alert')).toHaveText('Начало периода не может быть позже конца.');
  await expect(start).toHaveAttribute('aria-invalid','true');
  await expect(page.getByRole('button',{name:'Скачать XLSX',exact:true})).toBeDisabled();
  await start.fill('');await expect(page.getByRole('alert')).toHaveText('Укажите начало и конец периода.');
  await start.fill('2026-10-01');await expect(page.getByRole('alert')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'Скачать PDF',exact:true})).toBeEnabled();
});
