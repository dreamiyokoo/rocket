export type PredictedBand = "blue" | "green" | "yellow" | "red";

export type EvalStatsRow = {
  predicted_band: PredictedBand;
  actual_band: PredictedBand;
  verdict: "hit" | "miss";
  count: number;
};

export type EvalRecentRow = {
  round_id: number;
  predicted_band: PredictedBand;
  actual_band: PredictedBand;
  actual_multiplier: number;
  verdict: "hit" | "miss";
  evaluated_at: string;
};

export type EvalStatsResponse = {
  by_band: EvalStatsRow[];
  recent: EvalRecentRow[];
};

export type RoundEval = {
  predicted_band: PredictedBand;
  actual_band: PredictedBand;
  predicted_line?: number;
  actual: number;
  verdict: "hit" | "miss";
  emoji: string;
  label: string;
  evaluated_at: string;
};

export type RoundEvalArchive = Record<string, RoundEval>;

export type PredictionSummaryRow = {
  band: PredictedBand;
  predictedCount: number;
  hitCount: number;
  overCount: number | null;
  hitRate: number | null;
};

const SUMMARY_BANDS: PredictedBand[] = ["red", "yellow", "green", "blue"];

export function bandLabel(band: PredictedBand): string {
  if (band === "blue") return "1x台";
  if (band === "green") return "2x以上";
  if (band === "yellow") return "5x以上";
  return "10x以上";
}

export function bandLabelJa(band: PredictedBand): string {
  if (band === "blue") return "青";
  if (band === "green") return "緑";
  if (band === "yellow") return "黄";
  return "赤";
}

function isOverResult(predictedBand: PredictedBand, actualBand: PredictedBand): boolean {
  if (predictedBand === "green") return actualBand === "yellow" || actualBand === "red";
  if (predictedBand === "yellow") return actualBand === "red";
  return false;
}

export function buildPredictionSummary(rows: EvalStatsRow[]): PredictionSummaryRow[] {
  return SUMMARY_BANDS.map((band) => {
    const relevant = rows.filter((row) => row.predicted_band === band);
    const predictedCount = relevant.reduce((sum, row) => sum + row.count, 0);
    const hitCount = relevant
      .filter((row) => row.verdict === "hit")
      .reduce((sum, row) => sum + row.count, 0);
    const overCount = band === "blue" || band === "red"
      ? null
      : relevant
          .filter((row) => isOverResult(row.predicted_band, row.actual_band))
          .reduce((sum, row) => sum + row.count, 0);

    return {
      band,
      predictedCount,
      hitCount,
      overCount,
      hitRate: predictedCount > 0 ? (hitCount / predictedCount) * 100 : null,
    };
  });
}

type BuildEvalArchiveOptions = {
  missEmoji?: string;
  labelSeparator?: string;
};

export function buildEvalArchive(
  rows: EvalRecentRow[],
  options?: BuildEvalArchiveOptions,
): RoundEvalArchive {
  const missEmoji = options?.missEmoji ?? "●";
  const labelSeparator = options?.labelSeparator ?? " ";
  const archive: RoundEvalArchive = {};
  for (const row of rows) {
    archive[String(row.round_id)] = {
      predicted_band: row.predicted_band,
      actual_band: row.actual_band,
      actual: row.actual_multiplier,
      verdict: row.verdict,
      emoji: row.verdict === "hit" ? "✅" : missEmoji,
      label: `予測:${bandLabel(row.predicted_band)}${labelSeparator}実績:${bandLabel(row.actual_band)}`,
      evaluated_at: row.evaluated_at,
    };
  }
  return archive;
}
