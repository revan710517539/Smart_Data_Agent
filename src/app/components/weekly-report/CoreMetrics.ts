import type { SnapshotDataset } from "../../services/operatingSnapshotApi";
import type { WeeklyInstitutionReport } from "./domain";

export function buildWeeklyCoreMetricRows(dataset: SnapshotDataset) {
  return dataset.rows.map((row) => ({
    日期: String(row.stat_week || row.stat_date || ""),
    在贷余额: formatMetricYi(row.loan_balance),
    放款金额: formatMetricYi(row.loan_amount),
    新增余额: formatMetricYi(row.new_balance, true),
  }));
}

export function applyWeeklyCoreMetricSnapshot(
  reports: WeeklyInstitutionReport[],
  dataset: SnapshotDataset,
  rows: Record<string, string>[],
  updatedAt: string,
) {
  return reports.map((report, reportIndex) => reportIndex === 0 ? {
    ...report,
    sections: report.sections.map((section) => ({
      ...section,
      blocks: section.blocks.map((block) => block.type === "table" && block.id.endsWith("_core_metrics") ? {
        ...block,
        fields: ["日期", "在贷余额", "放款金额", "新增余额"],
        rows,
        dataSource: String(dataset.evidence.data_source || "weekly_core_metrics_mart"),
        updatedAt,
        evidenceRef: {
          verified: dataset.evidence.data_mode === "real",
          reason: dataset.evidence.data_mode === "real" ? "语义数据快照已校验" : "当前为显式模拟语义数据",
          evidence_id: String(dataset.evidence.evidence_id || ""),
          source_snapshot: dataset.evidence.source_snapshot,
          data_source: String(dataset.evidence.data_source || "weekly_core_metrics_mart"),
        },
      } : block),
    })),
  } : report);
}

function formatMetricYi(value: unknown, signed = false) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const yi = number / 100_000_000;
  return `${signed && yi > 0 ? "+" : ""}${yi.toFixed(2)}亿`;
}
