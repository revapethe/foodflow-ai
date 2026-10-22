import {test, expect} from "@playwright/test";

test("assistant grounds answers in warehouse, exposes SQL, and respects filter changes", async ({page, request}) => {
  const analytics = await (await request.get("/api/analytics")).json();
  await page.goto("/");
  const assistant = page.getByRole("region", {name:"Warehouse analytics assistant",exact:true});
  await assistant.getByRole("button", {name:"What is total revenue?",exact:true}).click();
  const result = page.getByRole("region", {name:"Assistant answer",exact:true});
  const money = new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(analytics.kpis.revenue);
  await expect(result).toContainText(money);
  await result.getByText("View SQL and bound parameters", {exact:true}).click();
  await expect(result.locator("pre")).toContainText("WITH selected AS");
  await expect(result).toContainText("Parameters: []");
  await page.getByRole("combobox", {name:"Market",exact:true}).selectOption("Denver");
  await expect(result).toHaveCount(0);
  await assistant.getByLabel("Your analytics question").fill("How many orders?");
  await assistant.getByRole("button", {name:"Ask warehouse",exact:true}).click();
  const city = await (await request.get("/api/analytics?city=Denver")).json();
  await expect(result).toContainText(`There are ${city.kpis.all_orders.toLocaleString("en-US")} orders`);
  await expect(result).toContainText("Applied scope: Denver");
});

test("unsupported assistant question abstains without hiding historical dashboard", async ({page}) => {
  await page.goto("/");
  await page.getByLabel("Your analytics question").fill("Why is revenue down?");
  await page.getByRole("button", {name:"Ask warehouse",exact:true}).click();
  const result = page.getByRole("region", {name:"Assistant answer",exact:true});
  await expect(result).toContainText("could not reliably interpret");
  await expect(result.getByText("View SQL and bound parameters")).toHaveCount(0);
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
});

test("assistant shows service failure and retry recovers", async ({page}) => {
  await page.route("**/api/assistant", route => route.fulfill({status:503,json:{detail:"unavailable"}}));
  await page.goto("/");
  await page.getByRole("button", {name:"What is total revenue?",exact:true}).click();
  const assistant = page.getByRole("region", {name:"Warehouse analytics assistant",exact:true});
  await expect(assistant.getByRole("alert")).toContainText("could not finish");
  await page.unroute("**/api/assistant");
  await assistant.getByRole("button", {name:"Retry question",exact:true}).click();
  await expect(page.getByRole("region", {name:"Assistant answer",exact:true})).toContainText("Delivered-order revenue is");
});

test("assistant results and SQL stay within mobile viewport", async ({page}) => {
  await page.setViewportSize({width:320,height:900});
  await page.goto("/");
  await page.getByRole("button", {name:"Top 5 restaurants by revenue",exact:true}).click();
  const result = page.getByRole("region", {name:"Assistant answer",exact:true});
  await expect(result.locator("tbody tr")).toHaveCount(5);
  await result.getByText("View SQL and bound parameters", {exact:true}).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
});
