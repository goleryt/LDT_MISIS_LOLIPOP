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
  await page.getByLabel("Комментарий", { exact: true }).fill("Контрольный прогон интерфейса на тестовой истории");
  await page.getByRole("button", { name: "Сохранить решение", exact: true }).click();
  await expect(page.getByText("История решений", { exact: true })).toBeVisible();
  await expect(page.locator(".prediction-detail")).toContainText("Контрольный прогон интерфейса на тестовой истории");
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
  await row.locator("select").selectOption("completed");
  await expect(row.locator("select")).toHaveValue("completed");
  await page.reload();
  await expect(page.locator("tr").filter({ hasText: title }).locator("select")).toHaveValue("completed");
});
