import { test, expect, type Page } from "@playwright/test";

async function mockReadyAnalysisWithRecommendation(page: Page) {
  await page.route("**/api/v1/analysis**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ready: true,
        total_rounds: 18,
        window: 18,
        prob_2x: { current: 0.5, history: [0.5] },
        prob_5x: { current: 0.1, history: [0.1] },
        prob_10x: { current: 0.0, history: [0.0] },
        moving_avg: 2.25,
        median: 2.25,
        std_dev: 0.75,
        max: 3.0,
        min: 1.5,
        atr: 0.2,
        rsi: { period: 14, current: null, chart: [null] },
        macd: { fast: 12, slow: 26, signal_period: 9, chart: [null] },
        bollinger_bands: {
          current: { upper: 3.75, middle: 2.25, lower: 1.01 },
          chart: [{ upper: 3.75, middle: 2.25, lower: 1.01 }],
        },
        chart_data: [{ index: 1, value: 2.0 }],
        recommendation: {
          volatility_cv: 0.62,
          regime: "medium",
          floor_line: 1.32,
          target_line: 3.41,
          flow_state: "warm",
          stake_scale: 1.0,
          entry_ok: true,
        },
        ml_prediction: {
          available: true,
          prob_blue: 0.55,
          prob_green: 0.25,
          prob_yellow: 0.12,
          prob_red: 0.08,
          prob_blue_binary: 0.55,
          skip_recommended: false,
          entry_boost: false,
        },
        analyzed_at: "2026-01-01T00:00:00Z",
      }),
    });
  });

  await page.route("**/api/v1/rounds", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rounds: [] }),
    });
  });
}

async function mockReadyAnalysisWithNoEntry(page: Page, noEntryReasons: string[]) {
  await page.route("**/api/v1/analysis**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        ready: true,
        total_rounds: 18,
        window: 18,
        prob_2x: { current: 0.5, history: [0.5] },
        prob_5x: { current: 0.1, history: [0.1] },
        prob_10x: { current: 0.0, history: [0.0] },
        moving_avg: 2.25,
        median: 2.25,
        std_dev: 0.75,
        max: 3.0,
        min: 1.5,
        atr: 0.2,
        rsi: { period: 14, current: null, chart: [null] },
        macd: { fast: 12, slow: 26, signal_period: 9, chart: [null] },
        bollinger_bands: {
          current: { upper: 3.75, middle: 2.25, lower: 1.01 },
          chart: [{ upper: 3.75, middle: 2.25, lower: 1.01 }],
        },
        chart_data: [{ index: 1, value: 2.0 }],
        recommendation: {
          volatility_cv: 0.62,
          regime: "medium",
          floor_line: 1.32,
          target_line: 3.41,
          flow_state: "warm",
          stake_scale: 1.0,
          entry_ok: false,
        },
        ml_prediction: {
          available: true,
          prob_blue: 0.55,
          prob_green: 0.25,
          prob_yellow: 0.12,
          prob_red: 0.08,
          prob_blue_binary: 0.55,
          skip_recommended: false,
          entry_boost: false,
        },
        no_entry: {
          active: noEntryReasons.length > 0,
          reasons: noEntryReasons,
          low_consecutive_count: noEntryReasons.includes("low_consecutive") ? 5 : 0,
          volatility_cv: noEntryReasons.includes("low_volatility") ? 0.1 : 0.35,
          median_value: noEntryReasons.includes("low_expected_value") ? 1.25 : 2.1,
        },
        analyzed_at: "2026-01-01T00:00:00Z",
      }),
    });
  });

  await page.route("**/api/v1/rounds", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rounds: [] }),
    });
  });
}

test("home page loads with dashboard content", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("main")).toBeVisible();
  await expect(page.locator("main")).toContainText("Rocket Analysis");
});

test("home page has correct title", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveTitle(/Rocket/i);
});

test("home page renders recommendation panel values", async ({ page }) => {
  await mockReadyAnalysisWithRecommendation(page);
  await page.goto("/");

  await expect(page.getByText("推奨ライン")).toBeVisible();
  await expect(page.getByText("中ボラ")).toBeVisible();
  await expect(page.getByText("🔵 Blue")).toBeVisible();
  await expect(page.getByText("🟢 Green")).toBeVisible();
});

test("no-entry indicator shows green when no reasons", async ({ page }) => {
  await mockReadyAnalysisWithNoEntry(page, []);
  await page.goto("/");

  const indicator = page.getByRole("status");
  await expect(indicator).toBeVisible();
  await expect(indicator).toContainText("エントリー可");
});

test("no-entry indicator shows yellow and reason label for one reason", async ({ page }) => {
  await mockReadyAnalysisWithNoEntry(page, ["low_consecutive"]);
  await page.goto("/");

  const indicator = page.getByRole("status");
  await expect(indicator).toBeVisible();
  await expect(indicator).toContainText("注意");
  await expect(indicator).toContainText("① 低倍率連続");
});

test("no-entry indicator shows red and all reason labels for multiple reasons", async ({ page }) => {
  await mockReadyAnalysisWithNoEntry(page, ["low_consecutive", "low_volatility"]);
  await page.goto("/");

  const indicator = page.getByRole("status");
  await expect(indicator).toBeVisible();
  await expect(indicator).toContainText("買い禁止");
  await expect(indicator).toContainText("① 低倍率連続");
  await expect(indicator).toContainText("③ 低ボラティリティ");
});
