import {test,expect} from '@playwright/test';
import type {Page} from '@playwright/test';

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
