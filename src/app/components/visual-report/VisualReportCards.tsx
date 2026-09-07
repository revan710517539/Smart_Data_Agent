import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Database } from "lucide-react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { fetchDataAssets, fetchPageDataRows, fetchTopicData } from "../../services/dataAssetApi";
import { upsertVisualReport, type VisualReport, type VisualReportCard } from "../../services/visualReportApi";
import { AnalysisVisualCard } from "../self-analysis/ResultViews";
import { ResizableVisualizationGrid } from "../self-analysis/ResizableVisualizationGrid";
import { visualDuplicateLayout } from "../self-analysis/visualGridLayout";
import { replaceVisualAnalysisSourceGroup } from "../analysis-workspace/AnalysisWorkspaceRail";
import { boundedVisualRows } from "../analysis-workspace/visualAnalysisScope";
import { revealVisualComment, revealVisualFollowUp } from "../self-analysis/visualFollowUp";
import type { AnalysisDataTableSelection, AnalysisRow } from "../self-analysis/domain";
import { resolveVisualReportRawTable, rowsFromPageVisualDataset, rowsFromRawVisualDataset, rowsFromTopicVisualDataset, visualReportDatasetMatches } from "./reportData";
import { askConfirm } from "../ui/ConfirmDialog";
import { applyReportPublicFilters, ReportPublicFilterControls, type ReportFilterDataset } from "../report-filters/ReportPublicFilters";

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
  const [extraCards, setExtraCards] = useState<VisualReportCard[]>([]);

  const cardsKey = useMemo(() => report.cards.map((card) => `${card.id}:${card.dataset.kind}:${card.dataset.id}:${card.dataset.sourceKey || ""}:${card.dataset.schemaFingerprint || ""}`).join("|"), [report.cards]);
  useEffect(() => {
    let cancelled = false;
    const knownIds = new Set(report.cards.map(visualReportDatasetKey));
    setLoading(true);
    setRowsByDataset((current) => Object.fromEntries(Object.entries(current).filter(([id]) => knownIds.has(id))));
    setErrorsByDataset((current) => Object.fromEntries(Object.entries(current).filter(([id]) => knownIds.has(id) || id === "catalog")));
    const applyRows = (datasetId: string, rows: AnalysisRow[], error = "") => {
      if (cancelled) return;
      setRowsByDataset((current) => current[datasetId] === rows ? current : { ...current, [datasetId]: rows });
      setErrorsByDataset((current) => {
        if (!error && !current[datasetId] && !current.catalog) return current;
        const next = { ...current };
        if (error) next[datasetId] = error;
        else delete next[datasetId];
        return next;
      });
    };
    const pageCode = railPageKey === "my-reports" ? "my_reports" : "visual_report";
    const speculative = Promise.all(report.cards.map(async (card) => {
      if (card.dataset.kind === "page_data") {
        try {
          const snapshot = await fetchPageDataRows({ tenantId, userId, pageDataId: card.dataset.id, pageCode });
          applyRows(visualReportDatasetKey(card), rowsFromPageVisualDataset({ sourceFields: card.dataset.fields } as import("../../services/dataAssetApi").PageDataAsset, snapshot));
        } catch (error) {
          applyRows(visualReportDatasetKey(card), [], apiErrorMessage(error, "多机构页面数据读取失败。"));
        }
        return;
      }
      if (card.dataset.kind === "topic") {
        try {
          const snapshot = await fetchTopicData({ tenantId, userId, referenceType: "topic", referenceId: card.dataset.id });
          applyRows(visualReportDatasetKey(card), rowsFromTopicVisualDataset({ fields: card.dataset.fields } as import("../../services/dataAssetApi").TopicTableAsset, snapshot));
        } catch (error) {
          applyRows(visualReportDatasetKey(card), [], apiErrorMessage(error, "主题数据集读取失败。"));
        }
      }
    }));
    const loadVisualizationCatalog = async (attempt = 0): Promise<void> => {
      const catalog = await fetchDataAssets({ tenantId, userId, scope: "visualization", forceRefresh: attempt > 0 });
      if (cancelled) return;
      if (catalog.status === "loading" && attempt < 12) {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        if (!cancelled) await loadVisualizationCatalog(attempt + 1);
        return;
      }
      if (catalog.status === "loading") {
        return;
      }
      const rawTables = catalog.raw_tables || [];
      const topicTables = catalog.topic_tables || [];
      const pageDataTables = (catalog.page_data || []).filter((item) => item.institutionScope === "multi_institution");
      report.cards.forEach((card) => {
        if (card.dataset.kind === "raw") {
          const resolved = resolveVisualReportRawTable(card.dataset, rawTables);
          if (!resolved.dataset) {
            applyRows(visualReportDatasetKey(card), [], resolved.error || "当前机构目录中找不到该原始表。");
            return;
          }
          const rows = rowsFromRawVisualDataset(resolved.dataset);
          applyRows(visualReportDatasetKey(card), rows, rows.length ? "" : "当前数据集没有可用预览行。");
          return;
        }
        if (card.dataset.kind === "page_data" && !pageDataTables.some((item) => visualReportDatasetMatches(card.dataset, item))) {
          applyRows(visualReportDatasetKey(card), [], "多机构页面数据不存在、无权限、关系版本或 Schema 已变化。");
        }
        if (card.dataset.kind === "topic" && !topicTables.some((item) => visualReportDatasetMatches(card.dataset, item))) {
          applyRows(visualReportDatasetKey(card), [], "主题数据集未发布、无权限或已失效。");
        }
      });
      setErrorsByDataset((current) => {
        if (!current.catalog) return current;
        const next = { ...current };
        delete next.catalog;
        return next;
      });
    };
    const catalogLoad = loadVisualizationCatalog().catch((error) => {
      if (!cancelled) setErrorsByDataset((current) => ({ ...current, catalog: apiErrorMessage(error, "可视化数据集加载失败。") }));
    });
    void Promise.allSettled([speculative, catalogLoad]).then(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
    // cardsKey intentionally captures dataset identity without rerunning on card presentation changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cardsKey, railPageKey, tenantId, userId]);

  const visibleCards = useMemo(() => {
    const known = new Set(report.cards.map((card) => card.id));
    return [...report.cards, ...extraCards.filter((card) => !known.has(card.id))];
  }, [extraCards, report.cards]);

  const filterDatasets = useMemo<ReportFilterDataset[]>(() => Array.from(new Map(visibleCards.map((card) => {
    const datasetId = visualReportDatasetKey(card);
    return [datasetId, {
      id: datasetId,
      name: card.dataset.name,
      subtitle: card.dataset.code,
      fields: card.dataset.fields,
      rows: (rowsByDataset[datasetId] || []).map((row) => row.raw),
    } satisfies ReportFilterDataset];
  })).values()), [rowsByDataset, visibleCards]);
  const filteredRowsByCardId = useMemo(() => Object.fromEntries(visibleCards.map((card) => [
    card.id,
    applyReportPublicFilters(
      rowsByDataset[visualReportDatasetKey(card)] || [],
      visualReportDatasetKey(card),
      report.publicFilters || [],
    ),
  ])), [report.publicFilters, rowsByDataset, visibleCards]);

  useEffect(() => {
    const group = `visual-report:${report.id}`;
    replaceVisualAnalysisSourceGroup(railPageKey, group, visibleCards.filter((card) => visualReportCardHasData(card, filteredRowsByCardId[card.id] || [])).map((card) => ({
      id: `${report.id}:${card.id}`,
      label: card.title,
      tables: [datasetSelection(card) as unknown as Record<string, unknown>],
      question: card.title,
      summary: report.title,
      rows: boundedVisualRows(filteredRowsByCardId[card.id]),
    })));
    return () => { replaceVisualAnalysisSourceGroup(railPageKey, group, []); };
  }, [filteredRowsByCardId, railPageKey, report.id, report.title, visibleCards]);

  const updateCard = (cardId: string, patch: Partial<VisualReportCard>) => {
    if (extraCards.some((card) => card.id === cardId)) {
      setExtraCards((current) => current.map((card) => card.id === cardId ? { ...card, ...patch } : card));
      return;
    }
    if (!editable || !onChange) return;
    onChange({ ...report, cards: report.cards.map((card) => card.id === cardId ? { ...card, ...patch } : card) });
  };
  const removeCard = (cardId: string) => {
    const target = visibleCards.find((card) => card.id === cardId);
    void askConfirm({ title: "删除图表", description: `确定删除图表「${target?.title || "该图表"}」？`, hint: "此操作不可撤销。" }).then((ok) => {
      if (!ok) return;
      removeCardAfterConfirm(cardId);
    });
  };
  const removeCardAfterConfirm = (cardId: string) => {
    if (extraCards.some((card) => card.id === cardId)) {
      setExtraCards((current) => current.filter((card) => card.id !== cardId));
      return;
    }
    if (!editable || !onChange) return;
    onChange({ ...report, cards: report.cards.filter((card) => card.id !== cardId) });
  };
  const createTextCard = (card: VisualReportCard, config: import("../visualization/visualizationDataModel").VisualizationCardConfig) => {
    const index = visibleCards.findIndex((item) => item.id === card.id);
    const nextCard: VisualReportCard = {
      ...card,
      id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      type: "text",
      title: `${card.title} · 结论`,
      config: { ...config, noteTitle: "", noteBody: "", noteItems: [], noteTitleHidden: false, ...visualDuplicateLayout(card.id) },
    };
    if (onChange) {
      const next = [...report.cards];
      const reportIndex = report.cards.findIndex((item) => item.id === card.id);
      next.splice((reportIndex < 0 ? report.cards.length : reportIndex) + 1, 0, nextCard);
      onChange({ ...report, cards: next });
      return;
    }
    setExtraCards((current) => {
      const following = [...current];
      const extraIndex = following.findIndex((item) => item.id === card.id);
      following.splice((extraIndex < 0 ? following.length : extraIndex) + 1, 0, nextCard);
      return following;
    });
    const merged = [...report.cards];
    merged.splice((index < 0 ? merged.length : Math.min(index, merged.length - 1)) + 1, 0, nextCard);
    void upsertVisualReport({ tenantId, userId, report: { ...report, cards: merged } }).catch(() => undefined);
  };

  if (!report.cards.length) return null;
  const renderedCards = editable
    ? visibleCards
    : visibleCards.filter((card) => visualReportCardHasData(card, filteredRowsByCardId[card.id] || []));
  const waitingForFirstRows = loading && !renderedCards.length;
  if (waitingForFirstRows) {
    return (
      <div data-visual-report-cards="true">
        <div className="mb-3 flex min-h-[48px] items-center justify-center rounded-xl border border-dashed border-[#dfe7e2] bg-[#fbfdfc] text-[11px] text-[#8d9791]" role="status" data-visual-report-data-loading="true">正在读取报表数据…</div>
      </div>
    );
  }
  if (!renderedCards.length) return null;
  return (
    <div data-visual-report-cards="true">
      {editable && errorsByDataset.catalog && <ReportDataError message={errorsByDataset.catalog} />}
      <ReportPublicFilterControls
        datasets={filterDatasets}
        groups={report.publicFilters || []}
        editable={editable}
        onChange={(publicFilters) => onChange?.({ ...report, publicFilters })}
      />
      <ResizableVisualizationGrid
        editable={layoutEditable}
        onLayoutChange={(cardId, size) => {
          const card = visibleCards.find((item) => item.id === cardId);
          if (!card) return;
          updateCard(cardId, { config: { ...card.config, layoutSpan: size.span, layoutHeight: size.height } });
        }}
      >
        {renderedCards.map((card) => {
          const datasetKey = visualReportDatasetKey(card);
          const rows = filteredRowsByCardId[card.id] || [];
          const selectedTable = datasetSelection(card);
          return <div key={card.id} className="flex h-full min-h-0 flex-col" data-visual-grid-span={card.config?.layoutSpan} data-visual-grid-height={card.config?.layoutHeight} data-visual-grid-max-span={card.config?.maxLayoutSpan} data-visual-grid-max-height={card.config?.maxLayoutHeight}>
            {editable && errorsByDataset[datasetKey] && <ReportDataError message={errorsByDataset[datasetKey]} compact />}
            <div className="min-h-0 flex-1">
              {visualReportCardHasData(card, rows) ? <AnalysisVisualCard
                id={card.id}
                stateKey={`visual-report:${report.id}:${card.id}`}
                title={card.title}
                type={card.type}
                rows={rows}
                initialConfig={card.config}
                configAuthority="server"
                fillHeight
                analysisSource={[selectedTable]}
                onFollowUp={(detail) => revealVisualFollowUp({ key: "primary", title: card.title, type: card.type, rows, reportId: report.id, question: report.title, summary: "可视化报表配置", plan: "基于已授权数据集的可视化报表", selectedDataTables: detail?.dataTables?.length ? detail.dataTables : [selectedTable], railPageKey })}
                onComment={(detail) => revealVisualComment({ key: "primary", title: card.title, type: card.type, rows, reportId: report.id, question: report.title, summary: "可视化报表配置", plan: "基于已授权数据集的可视化报表", selectedDataTables: detail?.dataTables?.length ? detail.dataTables : [selectedTable], railPageKey })}
                onTypeChange={(type) => updateCard(card.id, { type })}
                onTitleChange={editable || card.type === "text" ? (title) => updateCard(card.id, { title }) : undefined}
                onConfigChange={editable || card.type === "text" ? (config) => updateCard(card.id, { config }) : undefined}
                visualGridSpan={card.config?.layoutSpan}
                visualGridHeight={card.config?.layoutHeight}
                visualGridMaxSpan={card.config?.maxLayoutSpan}
                visualGridMaxHeight={card.config?.maxLayoutHeight}
                onCreateText={(config) => createTextCard(card, config)}
                onDuplicate={editable ? (config, options) => {
                  if (options?.asText) { createTextCard(card, config); return; }
                  const index = report.cards.findIndex((item) => item.id === card.id);
                  const next = [...report.cards];
                  next.splice(index + 1, 0, {
                    ...card,
                    id: `visual_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
                    title: `${card.title} · 副本`,
                    config,
                  });
                  onChange?.({ ...report, cards: next });
                } : undefined}
                onDelete={editable || extraCards.some((item) => item.id === card.id) ? () => removeCard(card.id) : undefined}
              /> : null}
            </div>
          </div>;
        })}
      </ResizableVisualizationGrid>
    </div>
  );
}

function visualReportDatasetKey(card: VisualReportCard) {
  return `${card.dataset.kind}:${card.dataset.id}`;
}

function visualReportCardHasData(card: VisualReportCard, rows: AnalysisRow[]) {
  return card.type === "text" || rows.length > 0;
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
