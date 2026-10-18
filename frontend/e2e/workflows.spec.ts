import { test, expect } from "@playwright/test";
test("login, map, objects, alarms, events, requests, model unavailable, logout", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto("/");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator(".app-shell")).toBeVisible();
  await expect(page.locator("svg.schematic-map-svg")).toBeVisible();
  for (const [title, path] of [["Объекты","/objects"],["Тревоги","/alarms"],["Журнал событий","/events"],["Заявки","/requests"],["Импорт данных","/imports"],["Прогнозы","/predictions"]]) {
    await page.locator(`nav a[href="${path}"]`).click();
    await expect(page).toHaveURL(new RegExp(path + "$"));
    await expect(page.locator("main")).toContainText(new RegExp(title === "Прогнозы" ? "Журнал прогнозов" : title, "i"));
  }
  await expect(page.locator(".status-notice")).toContainText(/суточный расчёт ещё не выполнялся|shadow-режим/);
  await page.locator('nav a[href="/reports"]').click();
  await expect(page.getByRole("heading", { name: "Фактические отчёты" })).toBeVisible();
  for (const format of ["PDF", "XLSX"]) {
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: `Скачать ${format}` }).click();
    const file = await downloaded;
    expect(file.suggestedFilename()).toMatch(new RegExp(`\\.${format.toLowerCase()}$`));
    expect(await file.failure()).toBeNull();
  }
  await page.locator('a[href="/settings"]').click();
  await page.getByRole("button", { name: "Выйти из аккаунта", exact: true }).click();
  await expect(page.getByRole("button", { name: "Войти", exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("real gas bundle result, advisory and dispatcher decision", async ({ page }) => {
  test.skip(process.env.RUN_ML_E2E !== "true", "Run check_ml_bundle first on the isolated test deployment");
  await page.goto("/predictions");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator(".status-notice")).toContainText("не вероятность пожара");
  await page.getByRole("button", { name: "Открыть", exact: true }).first().click();
  await expect(page.locator(".prediction-detail")).toContainText("Автоматические действия отключены");
  // Reproduce a slow detail refresh after save; isVisible() alone never waits.
  await page.route(/\/api\/v1\/predictions\/\d+$/,async route=>{
    if(route.request().method()==="GET")await new Promise(resolve=>setTimeout(resolve,300));
    await route.continue();
  });
  await page.getByLabel("Комментарий", { exact: true }).fill("Контрольный прогон интерфейса на тестовой истории");
  const decisionSaved=page.waitForResponse(response=>response.request().method()==="PATCH" && response.url().endsWith("/decision"));
  await page.getByRole("button", { name: "Сохранить решение", exact: true }).click();
  const savedResponse=await decisionSaved;
  expect(savedResponse.status()).toBe(200);
  const savedPrediction=await savedResponse.json();
  await expect(page.getByText("История решений", { exact: true })).toBeVisible();
  await expect(page.locator(".prediction-detail")).toContainText("Контрольный прогон интерфейса на тестовой истории");
  const createDraft = page.getByRole("button", { name: "Создать черновик заявки", exact: true });
  const requestLink = page.getByRole("link", { name: /Открыть заявку · №/ });
  // Use the committed server state. A visible old panel can disappear during
  // refresh, making even a preceding visibility assertion an unsafe branch.
  const freshDraft = !savedPrediction.request_id;
  if (freshDraft) await createDraft.click();
  await requestLink.click();
  if (freshDraft) {
  await expect(page.getByRole("heading", { name: /Черновик заявки №/ })).toBeVisible();
  await page.getByLabel("Тема черновика", { exact: true }).fill("Проверено диспетчером: тестовая рекомендация");
  await page.getByRole("button", { name: "Сохранить черновик", exact: true }).click();
  await expect(page.locator(".requests-feedback[role='status']")).toHaveText("Черновик сохранён");
  await page.getByRole("button", { name: "Подтвердить заявку", exact: true }).click();
  await expect(page.locator(".requests-feedback[role='status']")).toContainText("Черновик подтверждён");
  }
  await expect(page.getByRole("heading", { name: "История изменений" })).toBeVisible();
  await expect(page.locator("main")).not.toContainText(/undefined|NaN/);
  if (process.env.EVIDENCE_DIR) await page.screenshot({ path: `${process.env.EVIDENCE_DIR}/draft-confirmed-chrome.png` });
});

test("failed prediction request has visible feedback and recovers", async ({ page }) => {
  await page.goto("/predictions");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.route("**/api/v1/predictions/status", route => route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"internal secret debug"}' }));
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Сервис временно недоступен");
  await expect(page.locator("main")).not.toContainText("internal secret debug");
  await page.unroute("**/api/v1/predictions/status");
  await page.getByRole("button", { name: "Повторить загрузку", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("JSON import is visible in the registry and duplicate upload is identified", async ({ page }) => {
  await page.goto("/imports");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  const name=`acceptance-${Date.now()}.json`;
  const file={name,mimeType:"application/json",buffer:Buffer.from(JSON.stringify([{
    ид_события:String(Date.now()),ид_канала_данных:"1",дата:"2026-10-16",время:"10:00:00",тревожное:"false",значение_датчика:"25"
  }]))};
  await page.locator('input[type="file"]').setInputFiles(file);
  await page.getByRole("button", { name: "Начать импорт", exact:true }).click();
  await expect(page.getByText("Файл успешно обработан и зарегистрирован.")).toBeVisible();
  await expect(page.locator("tr").filter({hasText:name})).toContainText("Завершён");
  await page.locator('input[type="file"]').setInputFiles(file);
  await page.getByRole("button", { name: "Начать импорт", exact:true }).click();
  await expect(page.getByText("Этот файл уже был успешно импортирован ранее.")).toBeVisible();
});

test("mock alarm opens the exact sensor and can be marked read", async ({page}) => {
  test.skip(process.env.RUN_MOCK_E2E !== "true", "Start the five-source mock environment first");
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await page.locator('.notification-panel summary').click();
  // Keep mock-source/worker running: a repeated acceptance may have read all old alarms.
  await expect(page.locator('.notification-panel a[href="/?objectId=900001&channelId=900001"]').first()).toBeVisible({timeout:75000});
  await page.locator('.notification-panel a[href="/?objectId=900001&channelId=900001"]').first().click();
  await expect(page).toHaveURL(/objectId=900001&channelId=900001/);
  await expect(page.getByRole("heading",{name:"Последние события",exact:true})).toBeVisible();
  await page.getByRole("button",{name:/Прочитано:.*900001/}).first().click();
});

test("sensor history and preventive request from the map", async ({ page }) => {
  await page.goto("/?objectId=1&channelId=1");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Последние события", exact: true })).toBeVisible();
  // The telemetry acceptance may already have appended genuine test events.
  await expect.poll(async () => Number(await page.locator(".history-count").textContent())).toBeGreaterThanOrEqual(20);
  await page.getByRole("button", { name: "Создать профилактическую заявку" }).click();
  await expect(page.getByRole("combobox", { name: "Объект", exact: true })).toHaveValue("1");
  await expect(page.getByRole("combobox", { name: "Датчик", exact: true })).toHaveValue("1");
  const title = `Браузерная проверка ${Date.now()}`;
  await page.getByLabel("Тема", { exact: true }).fill(title);
  await page.getByRole("button", { name: "Создать заявку", exact: true }).click();
  const row = page.locator("tr").filter({ hasText: title });
  await expect(row).toBeVisible();
  await row.locator("select").selectOption("in_progress");
  await expect(row.locator("select")).toHaveValue("in_progress");
  await row.locator("select").selectOption("completed");
  await expect(row.locator("select")).toHaveValue("completed");
  await page.reload();
  await expect(page.locator("tr").filter({ hasText: title }).locator("select")).toHaveValue("completed");
});

test("map zoom, pan, tooltip, object click and compact navigation", async ({ page }) => {
  await page.goto("/?objectId=1");
  await page.getByPlaceholder("Логин", { exact: true }).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", { exact: true }).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  const map=page.locator("svg.schematic-map-svg");
  await expect(map).toBeVisible();
  const before=await map.getAttribute("viewBox");
  await page.getByRole("button", {name:"Приблизить карту",exact:true}).click();
  await expect(map).not.toHaveAttribute("viewBox",before!);
  const zoomed=await map.getAttribute("viewBox");
  const box=(await map.boundingBox())!;
  // The selected-object panel overlays the right half of the map.
  await page.mouse.move(box.x+100,box.y+120);
  await page.mouse.down();
  await page.mouse.move(box.x+170,box.y+150,{steps:8});
  await page.mouse.up();
  await expect(map).not.toHaveAttribute("viewBox",zoomed!);
  await page.getByRole("button", {name:"Показать все",exact:true}).click();
  // Selection via the URL is also used by alarms and notifications.
  await page.goto("/?objectId=1");
  const marker=map.locator('.schematic-object.selected .schematic-object-point');
  await expect(marker).toBeVisible();
  const point=(await marker.boundingBox())!;
  // Native pointer movement does not wait for the animated SVG halo to stop.
  await page.mouse.move(point.x+point.width/2,point.y+point.height/2);
  await expect(page.locator('.map-object-tooltip')).toBeVisible();
  await page.mouse.click(point.x+point.width/2,point.y+point.height/2);
  await expect(page.locator('.map-data-badge')).toContainText(/Условное|Демо/);
  await expect(page.locator('main')).toContainText('Фактическое состояние');
  await page.setViewportSize({width:390,height:844});
  await page.locator('nav a[href="/objects"]').click();
  await expect(page).toHaveURL(/\/objects$/);
  await expect(page.locator('.objects-table tbody tr').first()).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/undefined|NaN/);
  if (process.env.EVIDENCE_DIR) await page.screenshot({path:`${process.env.EVIDENCE_DIR}/compact-chrome.png`});
});

test("map loading and empty state, recovery and report progress", async ({page}) => {
  let release!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const mapRoute="**/api/v1/map/objects*";
  await page.route(mapRoute,async route=>{
    await gate;
    await route.fulfill({status:200,contentType:"application/json",body:"[]"});
  });
  await page.goto("/");
  await page.getByPlaceholder("Логин", {exact:true}).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль", {exact:true}).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button", {name:"Войти",exact:true}).click();
  await expect(page.locator(".map-state-notice")).toContainText("Загрузка объектов");
  release();
  await expect(page.locator(".map-state-notice")).toContainText("Объектов пока нет");
  await page.unroute(mapRoute);
  await page.route(mapRoute,route=>route.fulfill({status:503,contentType:"application/json",body:'{"detail":"private debug details"}'}));
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Сервис временно недоступен");
  await expect(page.locator("main")).not.toContainText("private debug details");
  await page.unroute(mapRoute);
  await page.getByRole("button",{name:"Повторить загрузку объектов",exact:true}).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  await expect(page.locator(".schematic-object").first()).toBeVisible();
  await page.locator('nav a[href="/reports"]').click();
  let releaseReport!:()=>void;
  const reportGate=new Promise<void>(resolve=>{releaseReport=resolve;});
  await page.route("**/api/v1/reports/**",async route=>{
    await reportGate;
    await route.fulfill({status:503,contentType:"application/json",body:'{"detail":"private debug details"}'});
  });
  await page.getByRole("button",{name:"Скачать PDF",exact:true}).click();
  await expect(page.getByRole("status")).toContainText("Формирование отчёта");
  releaseReport();
  await expect(page.getByRole("status")).toContainText("Сервис временно недоступен");
  await expect(page.getByRole("button",{name:"Скачать PDF",exact:true})).toBeEnabled();
});
