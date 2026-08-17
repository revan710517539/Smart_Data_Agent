import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Database } from "lucide-react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { fetchDataAssets, fetchPageDataRows, fetchTopicData } from "../../services/dataAssetApi";
import type { VisualReport, VisualReportCard } from "../../services/visualReportApi";
import { AnalysisVisualCard } from "../self-analysis/ResultViews";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import { revealVisualComment, revealVisualFollowUp } from "../self-analysis/visualFollowUp";
import type { AnalysisDataTableSelection, AnalysisRow } from "../self-analysis/domain";
import { rowsFromPageVisualDataset, rowsFromRawVisualDataset, rowsFromTopicVisualDataset, visualReportDatasetMatches } from "./reportData";

export function VisualReportCards({
  report,
  editable = false,
  layoutEditable = editable,
  railPageKey = "visual-reports",
  onChange,
}: {
  report: VisualReport;
  editable?: boolean;
  layoutEditable?: boolean;
  railPageKey?: string;
  onChange?: (report: VisualReport) => void;
}) {
  const { tenantId, userId } = usePlatformContext();
  const [rowsByDataset, setRowsByDataset] = useState<Record<string, AnalysisRow[]>>({});
  const [errorsByDataset, setErrorsByDataset] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  const cardsKey = useMemo(() => report.cards.map((card) => `${card.id}:${card.dataset.kind}:${card.dataset.id}:${card.dataset.sourceKey || ""}:${card.dataset.schemaFingerprint || ""}`).join("|"), [report.cards]);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setRowsByDataset({});
    setErrorsByDataset({});
    const loadReportData = async () => {
      const nextRows: Record<string, AnalysisRow[]> = {};
      const nextErrors: Record<string, string> = {};
      try {
        const catalog = await fetchDataAssets({ tenantId, userId, scope: "visualization" });
        const rawTables = catalog.raw_tables || [];
        const topicTables = catalog.topic_tables || [];
        const pageDataTables = (catalog.page_data || []).filter((item) => item.institutionScope === "multi_institution");
        await Promise.all(report.cards.map(async (card) => {
          if (card.dataset.kind === "raw") {
            const dataset = rawTables.find((item) => visualReportDatasetMatches(card.dataset, item));
            if (!dataset) {
              nextErrors[card.dataset.id] = "数据集不存在、无权限或 Schema 已变化，已停止展示旧配置。";
              return;
            }
            nextRows[card.dataset.id] = rowsFromRawVisualDataset(dataset);
            if (!nextRows[card.dataset.id].length) nextErrors[card.dataset.id] = "当前数据集没有可用预览行。";
            return;
          }
          if (card.dataset.kind === "page_data") {
            const dataset = pageDataTables.find((item) => visualReportDatasetMatches(card.dataset, item));
            if (!dataset) {
              nextErrors[card.dataset.id] = "多机构页面数据不存在、无权限、关系版本或 Schema 已变化。";
              return;
            }
            try {
              const snapshot = await fetchPageDataRows({
                tenantId,
                userId,
                pageDataId: dataset.id,
                pageCode: railPageKey === "my-reports" ? "my_reports" : "visual_report",
              });
              nextRows[card.dataset.id] = rowsFromPageVisualDataset(dataset, snapshot);
              if (!nextRows[card.dataset.id].length) nextErrors[card.dataset.id] = "当前多机构页面数据没有可展示行。";
            } catch (error) {
              nextErrors[card.dataset.id] = apiErrorMessage(error, "多机构页面数据读取失败。");
            }
            return;
          }
          const dataset = topicTables.find((item) => visualReportDatasetMatches(card.dataset, item));
          if (!dataset) {
            nextErrors[card.dataset.id] = "主题数据集未发布、无权限或已失效。";
            return;
          }
          try {
            const snapshot = await fetchTopicData({ tenantId, userId, referenceType: "topic", referenceId: dataset.id });
            nextRows[card.dataset.id] = rowsFromTopicVisualDataset(dataset, snapshot);
            if (!nextRows[card.dataset.id].length) nextErrors[card.dataset.id] = "当前主题数据集没有可展示行。";
          } catch (error) {
            nextErrors[card.dataset.id] = apiErrorMessage(error, "主题数据集读取失败。");
          }
        }));
      } catch (error) {
        nextErrors.catalog = apiErrorMessage(error, "可视化数据集加载失败。");
      } finally {
        if (!cancelled) {
          setRowsByDataset(nextRows);
          setErrorsByDataset(nextErrors);
          setLoading(false);
        }
      }
    };
    void loadReportData();
    return () => { cancelled = true; };
    // cardsKey intentionally captures dataset identity without rerunning on card presentation changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardsKey, tenantId, userId]);

  const updateCard = (cardId: string, patch: Partial<VisualReportCard>) => {
    if (!editable || !onChange) return;
    onChange({ ...report, cards: report.cards.map((card) => card.id === cardId ? { ...card, ...patch } : card) });
  };
  const removeCard = (cardId: string) => {
    if (!editable || !onChange) return;
    onChange({ ...report, cards: report.cards.filter((card) => card.id !== cardId) });
  };

  if (!report.cards.length) return null;
  if (loading) {
    return <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-dashed border-[#dfe7e2] bg-[#fbfdfc] text-[11px] text-[#8d9791]" role="status" data-visual-report-data-loading="true">正在读取报表数据…</div>;
  }
  return (
    <div data-visual-report-cards="true">
      {errorsByDataset.catalog && <ReportDataError message={errorsByDataset.catalog} />}
      <ResizableVisualizationGrid editable={layoutEditable}>
        {report.cards.map((card) => {
          const rows = rowsByDataset[card.dataset.id] || [];
          const selectedTable = datasetSelection(card);
          return <div key={card.id} className="flex h-full min-h-0 flex-col">
            {errorsByDataset[card.dataset.id] && <ReportDataError message={errorsByDataset[card.dataset.id]} compact />}
            <div className="min-h-0 flex-1">
              <AnalysisVisualCard
                id={card.id}
                stateKey={`visual-report:${report.id}:${card.id}`}
                title={card.title}
                type={card.type}
                rows={rows}
                initialConfig={card.config}
                fillHeight
                onFollowUp={() => revealVisualFollowUp({ key: "primary", title: card.title, type: card.type, rows, reportId: report.id, question: report.title, summary: "可视化报表配置", plan: "基于已授权数据集的可视化报表", selectedDataTables: [selectedTable], railPageKey })}
                onComment={() => revealVisualComment({ key: "primary", title: card.title, type: card.type, rows, reportId: report.id, question: report.title, summary: "可视化报表配置", plan: "基于已授权数据集的可视化报表", selectedDataTables: [selectedTable], railPageKey })}
                onTypeChange={(type) => updateCard(card.id, { type })}
                onTitleChange={editable ? (title) => updateCard(card.id, { title }) : undefined}
                onConfigChange={editable ? (config) => updateCard(card.id, { config }) : undefined}
                onDuplicate={editable ? (config) => onChange?.({ ...report, cards: [...report.cards, { ...card, id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`, title: `${card.title} · 副本`, config }] }) : undefined}
                onDelete={editable ? () => removeCard(card.id) : undefined}
              />
            </div>
          </div>;
        })}
      </ResizableVisualizationGrid>
    </div>
  );
}

function datasetSelection(card: VisualReportCard): AnalysisDataTableSelection {
  return {
    id: card.dataset.id,
    kind: card.dataset.kind,
    name: card.dataset.name,
    code: card.dataset.code,
    description: "可视化报表引用的数据集",
    sql: "",
    fields: card.dataset.fields.map((field) => `${field.fieldNameEn}(${field.fieldNameCn || field.fieldNameEn})`).join(", "),
    fieldLabels: Object.fromEntries(card.dataset.fields.map((field) => [field.fieldNameEn, field.fieldNameCn || field.fieldNameEn])),
  };
}

function ReportDataError({ message, compact = false }: { message: string; compact?: boolean }) {
  return <div className={`${compact ? "mb-1" : "mb-3"} flex items-center gap-2 rounded-lg border border-[#f0dfc8] bg-[#fffaf2] px-3 py-2 text-[10px] text-[#91671f]`} role="status">
    {compact ? <AlertCircle className="h-3.5 w-3.5 shrink-0" /> : <Database className="h-3.5 w-3.5 shrink-0" />}
    <span>{message}</span>
  </div>;
}
