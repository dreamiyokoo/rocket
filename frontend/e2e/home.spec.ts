import { test, expect } from "@playwright/test";

test("home page loads with dashboard content", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("main")).toContainText("Rocket Analysis");
});

test("home page has correct title", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Rocket/i);
});
