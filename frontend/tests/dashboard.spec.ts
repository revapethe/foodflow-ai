import { test, expect } from "@playwright/test";

test("dashboard matches API, filters, switches charts, and exports actual rows", async ({ page, request }) => {
  const response = await request.get("/api/analytics");
  expect(response.ok()).toBeTruthy();
  const all = await response.json();
  const money = (n: number) => new Intl.NumberFormat("en-US", {style:"currency", currency:"USD", minimumFractionDigits:2, maximumFractionDigits:2}).format(n);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Supply chain overview" })).toBeVisible();
  await expect(page.getByLabel("Key performance indicators")).toContainText(money(all.kpis.revenue));
  await page.getByLabel("Market").selectOption("Denver");
  const selected = await (await request.get("/api/analytics?city=Denver")).json();
  await expect(page.getByLabel("Key performance indicators")).toContainText(money(selected.kpis.revenue));
  await page.getByRole("button", { name: "orders", exact: true }).click();
  await expect(page.getByRole("button", { name: "orders", exact: true })).toHaveAttribute("aria-pressed", "true");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export daily data" }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe("foodflow-daily-analytics.csv");
  const stream = await file.createReadStream();
  let csv = "";
  for await (const chunk of stream!) csv += chunk.toString();
  expect(csv.split("\n").length).toBe(selected.daily.length + 1);
  expect(csv).toContain(`${selected.daily[0].date},${selected.daily[0].orders},${selected.daily[0].delivered_orders},${selected.daily[0].revenue}`);
  expect(errors).toEqual([]);
});

test("date filters and empty state", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
  await page.getByLabel("From date").fill("2025-01-01");
  await page.getByLabel("To date").fill("2025-01-01");
  await expect(page.getByRole("button", {name:"Export daily data"})).toBeEnabled();
  await page.getByLabel("From date").fill("2026-01-01");
  await expect(page.getByRole("alert", {name:"Analytics error"})).toContainText("valid date range");
  await page.getByRole("button", {name:"Reset filters"}).click();
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
  await page.route("**/api/analytics?**", async route => {
    const response = await route.fetch();
    const data = await response.json();
    data.kpis = {all_orders:0, delivered_orders:0, revenue:0, average_order_value:null, average_delivery_minutes:null, fulfillment_rate:null, average_rating:null};
    data.daily = []; data.restaurants = []; data.products = []; data.statuses = [];
    await route.fulfill({json:data});
  });
  await page.getByLabel("Market").selectOption("Denver");
  await expect(page.getByRole("heading", {name:"No orders in this selection"})).toBeVisible();
});

test("service failure is visible and retry recovers", async ({ page }) => {
  await page.route("**/api/analytics?**", route => route.fulfill({status:503, json:{detail:"unavailable"}}));
  await page.goto("/");
  await expect(page.getByRole("alert", {name:"Analytics error"})).toContainText("analytics service is unavailable");
  await expect(page.getByRole("button", {name:"Export daily data"})).toBeDisabled();
  await page.unroute("**/api/analytics?**");
  await page.getByRole("button", {name:"Retry"}).click();
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
});

test("mobile layout stays within viewport", async ({ page }) => {
  await page.setViewportSize({width:390,height:844});
  await page.goto("/");
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await expect(page.getByLabel("Market")).toBeVisible();
});

test("combined city/date filters reconcile displayed KPIs and restaurant rows", async ({page, request}) => {
  await page.goto("/");
  await expect(page.getByLabel("Key performance indicators")).toBeVisible();
  await page.getByLabel("Market").selectOption("Denver");
  await page.getByLabel("From date").fill("2025-03-01");
  await page.getByLabel("To date").fill("2025-06-30");
  const response = await request.get("/api/analytics?city=Denver&start=2025-03-01&end=2025-06-30");
  expect(response.ok()).toBeTruthy();
  const data = await response.json();
  const cards = page.getByLabel("Key performance indicators");
  await expect(cards).toContainText(new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(data.kpis.revenue));
  await expect(cards).toContainText(`${data.kpis.fulfillment_rate}%`);
  await expect(cards).toContainText(`${data.kpis.average_delivery_minutes} min`);
  const table = page.getByRole("region", {name:"Restaurant rankings"});
  await expect(table.locator("tbody tr")).toHaveCount(data.restaurants.length);
  await expect(table.locator("tbody tr").first()).toContainText(data.restaurants[0].restaurant_name);
  await expect(table.locator("tbody tr").first()).toContainText(new Intl.NumberFormat("en-US", {style:"currency",currency:"USD"}).format(data.restaurants[0].revenue));
  const chart = page.getByRole("img", {name:/Daily revenue chart/});
  await expect(chart.locator(".recharts-area-curve")).toHaveAttribute("d", /M.+L/);
  await chart.locator(".recharts-wrapper").hover({position:{x:250,y:100}});
  await expect(chart.locator(".recharts-tooltip-wrapper")).toBeVisible();
});

for (const width of [320, 768, 1440]) {
  test(`layout and chart rendering at ${width}px`, async ({page}) => {
    await page.setViewportSize({width,height:1000});
    await page.goto("/");
    await expect(page.getByLabel("Key performance indicators")).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    await expect(page.locator(".recharts-area-curve")).toBeVisible();
    await expect(page.locator(".recharts-bar-rectangle").first()).toBeVisible();
    if (width < 1024) {
      await page.getByRole("navigation", {name:"Dashboard sections"}).getByRole("link", {name:"Products"}).click();
      await expect(page.getByRole("heading", {name:"What customers order"})).toBeInViewport();
    }
  });
}
