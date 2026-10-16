import {test,expect} from "@playwright/test";
import {mkdir,writeFile} from "node:fs/promises";

async function login(page:import("@playwright/test").Page,path="/") {
  await page.goto(path);
  await page.getByPlaceholder("Логин",{exact:true}).fill(process.env.TEST_USERNAME ?? "dispatcher");
  await page.getByLabel("Пароль",{exact:true}).fill(process.env.TEST_PASSWORD ?? "");
  await page.getByRole("button",{name:"Войти",exact:true}).click();
  await expect(page.locator(".app-shell")).toBeVisible();
}

test("notification read survives an older poll response and recovers from failure",async({page})=>{
  test.setTimeout(100000);
  const notice={id:990001,message:"TEST RC — фактическая тревога",kind:"observed_alarm",reference_id:1,object_id:1,channel_id:1,created_at:"2026-10-16T12:00:00Z"};
  let release!:()=>void,started!:()=>void,returned!:()=>void;
  const gate=new Promise<void>(resolve=>{release=resolve;});
  const secondPoll=new Promise<void>(resolve=>{started=resolve;});
  const oldReturned=new Promise<void>(resolve=>{returned=resolve;});
  let calls=0,reads=0;
  await page.route("**/api/v1/notifications?*",async route=>{
    calls++;
    if(calls===2) {started();await gate;}
    if(calls===3) {await route.fulfill({status:503,body:"temporary failure"});return;}
    await route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(calls<=2?[notice]:[])});
    if(calls===2)returned();
  });
  await page.route("**/api/v1/notifications/990001/read",async route=>{
    reads++;await route.fulfill({status:200,contentType:"application/json",body:"{}"});
  });
  await login(page);
  await page.locator(".notification-panel summary").click();
  await expect(page.locator(".notification-panel time")).toHaveAttribute("datetime",notice.created_at);
  await secondPoll;
  await page.getByRole("button",{name:"Прочитано: "+notice.message,exact:true}).click();
  await expect(page.locator(".notification-panel a")).toHaveCount(0);
  release();await oldReturned;
  await expect(page.locator(".notification-panel a")).toHaveCount(0);
  await expect(page.locator(".notification-panel summary")).toContainText("связь потеряна",{timeout:25000});
  await expect(page.locator(".notification-panel summary")).not.toContainText("связь потеряна",{timeout:25000});
  expect(reads).toBe(1);
});

test("stored prediction supports URL, refresh, close and browser Back",async({page})=>{
  await login(page,"/predictions");
  const response=await page.request.get("/api/v1/predictions");
  const rows=await response.json();
  test.skip(rows.length===0,"Requires an existing stored result; never generates or fabricates ML output");
  const id=rows[0].id;
  await page.getByRole("button",{name:"Открыть",exact:true}).first().click();
  await expect(page).toHaveURL(new RegExp("predictionId="+id));
  await expect(page.getByRole("heading",{name:"Прогноз №"+id,exact:true})).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading",{name:"Прогноз №"+id,exact:true})).toBeVisible();
  await page.getByRole("button",{name:"Закрыть прогноз",exact:true}).click();
  await expect(page).not.toHaveURL(/predictionId=/);
  await expect(page.locator(".prediction-detail")).toHaveCount(0);
  await page.goBack();
  await expect(page.getByRole("heading",{name:"Прогноз №"+id,exact:true})).toBeVisible();
});

test("desktop visual matrix with actual data and long Russian object names",async({page})=>{
  test.skip(process.env.RUN_RC_VISUAL!=="true","Opt-in screenshot evidence on isolated QA");
  test.setTimeout(180000);
  const dir=process.env.RC_VISUAL_DIR ?? "test-results/rc-visual";
  await mkdir(dir,{recursive:true});
  const errors:string[]=[];
  page.on("pageerror",error=>errors.push(error.message));
  await page.goto("/");
  await page.screenshot({path:dir+"/login.png"});
  await login(page);
  const measurements:unknown[]=[];
  const routes=["/","/objects","/alarms","/events","/requests","/imports","/predictions","/reports","/settings","/?objectId=1&channelId=1"];
  for(const [width,height,theme] of [[1280,800,"dark"],[1440,900,"light"],[1920,1080,"dark"]] as const){
    await page.setViewportSize({width,height});
    await page.evaluate(value=>localStorage.setItem("settings.theme",value),theme);
    for(let i=0;i<routes.length;i++){
      await page.goto(routes[i]);
      await expect(page.locator(".app-shell")).toBeVisible();
      await expect(page.locator("main")).not.toContainText(/Загрузка (объектов|истории|заявок|событий|прогнозов|датчиков)/);
      if(routes[i]==="/predictions" && await page.getByRole("button",{name:"Открыть",exact:true}).count()){
        await page.getByRole("button",{name:"Открыть",exact:true}).first().click();
        await expect(page.locator(".prediction-detail")).toBeVisible();
      }
      const metrics=await page.evaluate(()=>({viewport:innerWidth,document:document.documentElement.scrollWidth,
        main:document.querySelector("main")?.getBoundingClientRect().width}));
      measurements.push({width,height,theme,path:routes[i],...metrics});
      await page.screenshot({path:dir+"/"+width+"-"+i+".png",fullPage:true,animations:"disabled"});
      expect.soft(metrics.document,"Horizontal document overflow "+routes[i]+" at "+width).toBeLessThanOrEqual(width+1);
      await expect.soft(page.locator("main")).not.toContainText(/undefined|NaN/);
    }
  }
  // UI-only object-name fixture. No telemetry or ML response is replaced.
  await page.route("**/api/v1/map/objects",async route=>{
    const response=await route.fetch();const rows=await response.json();
    if(rows.length)rows[0].name="ТЕСТ длинного русского имени объекта — ".repeat(12);
    await route.fulfill({response,json:rows});
  });
  await page.setViewportSize({width:1280,height:800});
  await page.goto("/objects");
  await expect(page.locator(".objects-table")).toBeVisible();
  await page.getByPlaceholder("Поиск по названию, типу или ID...").fill("ТЕСТ длинного");
  await expect(page.locator(".objects-table tbody tr")).toHaveCount(1);
  await page.screenshot({path:dir+"/long-name.png",fullPage:true});
  await page.locator(".objects-table tbody tr").click();
  await expect(page.locator(".object-drawer")).toContainText("ТЕСТ длинного русского имени");
  await page.screenshot({path:dir+"/long-name-drawer.png",fullPage:true});
  await page.route("**/api/v1/notifications?*",route=>route.fulfill({status:200,contentType:"application/json",body:JSON.stringify([
    {id:999001,message:"ТЕСТ длинного уведомления — ".repeat(30),kind:"observed_alarm",reference_id:1,object_id:1,channel_id:1,created_at:"2026-10-16T12:00:00Z"}
  ])}));
  await page.reload();
  await page.locator(".notification-panel summary").click();
  await expect(page.locator(".notification-panel a")).toContainText("ТЕСТ длинного уведомления");
  await page.screenshot({path:dir+"/long-notification.png",fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  expect(overflow).toBe(false);expect(errors).toEqual([]);
  await writeFile(dir+"/matrix.json",JSON.stringify({measurements,runtime_errors:errors,long_name_overflow:overflow},null,2));
});
