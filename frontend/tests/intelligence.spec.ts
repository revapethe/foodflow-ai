import { test,expect } from "@playwright/test";

test("forecast chart, evaluation and export match the actual API",async({page,request})=>{
  const result=await request.get("/api/intelligence");expect(result.ok()).toBeTruthy();
  const data=await result.json();expect(data.status).toBe("ready");
  await page.goto("/");
  const section=page.getByRole("region",{name:"Demand intelligence",exact:true});
  await expect(section).toContainText(`Historical demo forecast as of ${data.as_of}`);
  await expect(section).toContainText(data.selected_label);
  const format=(n:number)=>n.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2});
  await expect(section.getByTestId("forecast-metric").nth(1)).toHaveText(format(data.evaluation.candidates[data.selected_model].test.mae));
  await expect(page.getByRole("region",{name:"Model comparison"}).locator("tbody tr")).toHaveCount(3);
  await expect(page.getByRole("img",{name:"Observed daily orders and 14-day forecast with empirical error band"}).locator(".recharts-line-curve")).toHaveCount(2);
  const download=page.waitForEvent("download");await section.getByRole("button",{name:"Export forecast"}).click();
  const file=await download;const stream=await file.createReadStream();let text="";
  for await(const chunk of stream!)text+=chunk.toString();
  expect(text.split("\n")).toHaveLength(data.predictions.length+1);
  const first=data.predictions[0];expect(text).toContain(`${first.date},${first.prediction},${first.lower},${first.upper},${data.selected_model}`);
  await page.getByLabel("Market").selectOption("Denver");
  const city=await(await request.get("/api/intelligence?city=Denver")).json();
  await expect(section.getByTestId("forecast-metric").nth(1)).toHaveText(format(city.evaluation.candidates[city.selected_model].test.mae));
});

test("stale intelligence is hidden while historical analytics remain usable",async({page})=>{
  await page.route("**/api/intelligence?**",route=>route.fulfill({json:{status:"stale",reason:"Warehouse inputs have changed. Retrain intelligence before using forecasts or anomaly flags."}}));
  await page.goto("/");
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
  const section=page.getByRole("region",{name:"Demand intelligence",exact:true});
  await expect(section).toContainText("Warehouse inputs have changed");
  await expect(section.getByRole("button",{name:"Export forecast"})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"Export daily data"})).toBeEnabled();
});
