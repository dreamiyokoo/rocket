import { test, expect, type Page } from "@playwright/test";

async function mockProbabilityTrends(page: Page) {
  await page.route("**/api/v1/rounds/probability-trends**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        timezone: "UTC",
        days: 14,
        hourly: [
          {
            bucket: "2026-05-19T12:00:00+00:00",
            total: 300,
            prob_1_2x: 0.19,
            prob_2_0x: 0.54,
            prob_blue: 0.54,
            prob_green: 0.30,
            prob_yellow: 0.08,
            prob_red: 0.08,
          },
        ],
        daily: [
          {
            bucket: "2026-05-19T00:00:00+00:00",
            total: 1200,
            prob_1_2x: 0.20,
            prob_2_0x: 0.55,
            prob_blue: 0.55,
            prob_green: 0.28,
            prob_yellow: 0.08,
            prob_red: 0.09,
          },
        ],
        // hourly は12:00のみだが、tableは hourly_stats(全期間) を使うので
        // 23:00 の件数が 0 にならないことを確認する
        hourly_stats: Array.from({ length: 24 }, (_, hour) => ({
          hour,
          total: hour === 23 ? 987 : hour === 0 ? 654 : 321,
          prob_1_2x: 0.2,
          prob_2_0x: 0.55,
          prob_green: 0.28,
          prob_yellow: 0.08,
          prob_red: 0.09,
        })),
      }),
    });
  });
}

test("probability trends page shows hourly stats from hourly_stats", async ({ page }) => {
  await mockProbabilityTrends(page);
  await page.goto("/probability-trends");

  await expect(page.getByRole("heading", { name: "時間帯別 確率統計" })).toBeVisible();

  const row23 = page.locator("tbody tr").filter({ hasText: "23:00" });
  await expect(row23).toContainText("987");

  const row00 = page.locator("tbody tr").filter({ hasText: "00:00" });
  await expect(row00).toContainText("654");
});
