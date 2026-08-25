import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { zhCN } from "date-fns/locale";
import { useLocation } from "react-router";
import {
  AlertTriangle,
  Activity,
  BookOpen,
  CalendarDays,
  CalendarClock,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CheckCircle2,
  Clock3,
  Database,
  Eye,
  FilePlus2,
  GitBranch,
  History,
  Layers3,
  Link2,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Shield,
  Sparkles,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import type { MetricDictionaryItem } from "../data/metricDictionary";
import { operatingTenantNames } from "../data/operatingTenants";
import {
  dateFieldFormat,
  formatFieldValue,
  metricFieldTypes,
  normalizeFieldSemantics,
  primaryKeyFields,
  updateFieldSemanticValue,
} from "../data/fieldSemantics";
import { usePlatformContext } from "../platform/PlatformContext";
import { fetchAccessRolePolicies, type AccessRoleConfig } from "../services/accessControlApi";
import {
  deleteMetricDictionaryItem,
  createMetricVersion,
  fetchMetricDictionary,
  fetchMetricVersionImpact,
  fetchMetricVersionDiff,
  fetchMetricVersions,
  importMetricDictionaryWorkbook,
  rollbackMetricVersion,
  saveMetricDictionaryItem,
  transitionMetricVersion,
  type MetricSemanticVersion,
  type MetricVersionDiff,
} from "../services/metricDictionaryApi";
import { getSystemHealth, type SystemHealthResponse } from "../services/systemHealthApi";
import {
  fetchDataAcquisition,
  type AcquisitionJob,
  type DataQualityResult,
} from "../services/dataAcquisitionApi";
import {
  clearDataCrawlerSchedule,
  executeDataCrawlerSchedule,
  fetchAutomationRun,
  fetchDataCrawlerSchedule,
  fetchDataCrawlerScheduleExecution,
  fetchDataCrawlerScheduleStatuses,
  refreshDataCrawlerSchedule,
  saveDataCrawlerSchedule,
  testDataCrawlerSchedule,
  type DataCrawlerScheduleDraft,
  type DataCrawlerScheduleListStatus,
  type DataCrawlerScheduleState,
} from "../services/dataCrawlerScheduleApi";
import { apiErrorMessage } from "../services/apiClient";
import { demoFallbackDisabledMessage, isDemoFallbackEnabled } from "../services/apiContext";
import {
  deleteDataAssetItem,
  fetchDataAssets,
  fetchMultiInstitutionPageDataCandidates,
  fetchTopicData,
  type AnalysisExperienceAsset,
  type BehaviorHabitAsset,
  type DataAssetBundle,
  type IntentAsset,
  type KnowledgeFileAsset,
  type PageDataAsset,
  type PageDataInstitutionScope,
  type MultiInstitutionPageDataCandidate,
  type RawTableAsset,
  type RawFileUpload,
  type RawField,
  type TableRelationshipAsset,
  type TopicTableAsset,
  type TopicDataSnapshot,
  saveDataAssetItem,
  updateRawTableExternalReference,
  uploadRawDataFile,
} from "../services/dataAssetApi";
import { customerDetailTableKey, PageDataAssetList, PageDataCreateButton, PageDataCreateModal } from "./data-assets/PageDataAssets";
import { pageDataScope } from "./page-data/assignment";
import { TableRelationshipWorkspace } from "./data-assets/TableRelationshipBuilder";
import { DataPageSelector } from "./ui/DataPageSelector";
import { Calendar } from "./ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "./ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "./ui/select";

type DataAssetSection = "metrics" | "knowledge" | "data-management" | "quality";
type DataManagementTab = "raw" | "single_page" | "multi_page" | "customer_segment_page" | "topic";
type KnowledgeMemoryTab = "all" | "intent" | "files" | "experience";
type MetricForm = MetricDictionaryItem;
type MetricDataSource = "backend" | "local" | "syncing" | "unavailable";
type MetricColumnKey =
  | "metricId"
  | "metricName"
  | "definition"
  | "valueLogic"
  | "sourceTable"
  | "dimension"
  | "description";

const emptyMetricForm: MetricForm = {
  metricId: "",
  metricName: "",
  definition: "",
  valueLogic: "",
  sourceTable: "",
  dimension: "",
  description: "",
  applicationScene: "",
  systemSource: "",
  statTime: "",
  referenceDocument: "",
  visibleInstitutions: [],
  visibleRoles: [],
};

const sectionCopy: Record<
  DataAssetSection,
  { title: string; subtitle: string; searchPlaceholder: string }
> = {
  metrics: {
    title: "指标管理",
    subtitle: "基于金科标准指标体系维护指标名称、口径、取值逻辑和数据来源",
    searchPlaceholder: "搜索指标ID、指标名称、口径或表名",
  },
  knowledge: {
    title: "知识记忆",
    subtitle: "按意图、知识文件、分析经验和用户行为习惯沉淀可复用业务语义",
    searchPlaceholder: "搜索意图、知识文件、分析经验或用户行为习惯",
  },
  "data-management": {
    title: "站内数据",
    subtitle: "原始表仅读取当前机构 Data Crawler 文件夹中的 CSV；主题表和分析结果统一复用 Topic_Data 中的最新数据资产",
    searchPlaceholder: "搜索原始表、主题表、字段或 SQL",
  },
  quality: {
    title: "质量监控",
    subtitle: "监控数据完整性、准确性、时效性和口径一致性",
    searchPlaceholder: "搜索质量规则或数据表",
  },
};

const metricDictionaryStorageKey = "smart_data_agent_metric_dictionary_v2";
const metricPageSize = 10;
const dataTablePageSize = 10;

const metricColumns: {
  key: MetricColumnKey;
  label: string;
  defaultWidth: number;
  minWidth: number;
  multiline?: boolean;
  readonly?: boolean;
}[] = [
  { key: "metricId", label: "指标ID", defaultWidth: 84, minWidth: 78, readonly: true },
  { key: "metricName", label: "指标名称", defaultWidth: 124, minWidth: 110 },
  { key: "definition", label: "指标口径", defaultWidth: 160, minWidth: 140, multiline: true },
  { key: "valueLogic", label: "取值逻辑", defaultWidth: 180, minWidth: 150, multiline: true },
  { key: "sourceTable", label: "取值表名", defaultWidth: 150, minWidth: 130, multiline: true },
  { key: "dimension", label: "指标维度", defaultWidth: 150, minWidth: 140, multiline: true },
  { key: "description", label: "指标描述", defaultWidth: 220, minWidth: 180, multiline: true },
];

const defaultColumnWidths = metricColumns.reduce(
  (widths, column) => ({ ...widths, [column.key]: column.defaultWidth }),
  {} as Record<MetricColumnKey, number>,
);

function getSection(pathname: string): DataAssetSection {
  if (pathname.endsWith("/knowledge")) return "knowledge";
  if (pathname.endsWith("/data-management")) return "data-management";
  if (pathname.endsWith("/quality")) return "quality";
  return "metrics";
}

function metricDictionaryStorageKeyForTenant(tenantId: string) {
  return `${metricDictionaryStorageKey}_${tenantId}`;
}

async function loadInitialMetricDictionary() {
  const module = await import("../data/metricDictionary");
  return module.initialMetricDictionary;
}

async function loadMetricDictionary(tenantId: string) {
  const initialMetricDictionary = await loadInitialMetricDictionary();
  if (typeof window === "undefined") return initialMetricDictionary;
  try {
    const raw =
      window.localStorage.getItem(metricDictionaryStorageKeyForTenant(tenantId)) ||
      window.localStorage.getItem(metricDictionaryStorageKey);
    const parsed = raw ? (JSON.parse(raw) as MetricDictionaryItem[]) : null;
    return parsed?.[0]?.metricId &&
      parsed.length >= initialMetricDictionary.length &&
      hasUniqueMetricNames(parsed)
      ? parsed
      : initialMetricDictionary;
  } catch {
    return initialMetricDictionary;
  }
}

function hasUniqueMetricNames(metrics: MetricDictionaryItem[]) {
  const names = new Set<string>();
  for (const metric of metrics) {
    const name = metric.metricName.trim();
    if (!name || names.has(name)) return false;
    names.add(name);
  }
  return true;
}

function getNextMetricId(metrics: MetricDictionaryItem[]) {
  const maxId = metrics.reduce((max, metric) => {
    const match = /^M(\d+)$/.exec(metric.metricId);
    return match ? Math.max(max, Number(match[1])) : max;
  }, -1);
  return `M${String(maxId + 1).padStart(5, "0")}`;
}

function matchesMetric(metric: MetricDictionaryItem, keyword: string) {
  if (!keyword) return true;
  const haystack = [
    metric.metricId,
    metric.metricName,
    metric.definition,
    metric.valueLogic,
    metric.sourceTable,
    metric.dimension,
    metric.description,
    metric.applicationScene,
    metric.systemSource,
    metric.statTime,
    metric.referenceDocument,
  ]
    .join(" ")
    .toLowerCase();
  return haystack.includes(keyword.toLowerCase());
}

function extractReferencedFields(metrics: MetricDictionaryItem[]) {
  const fieldSet = new Set<string>();
  metrics.forEach((metric) => {
    const text = `${metric.valueLogic} ${metric.dimension}`;
    text.match(/[A-Za-z][A-Za-z0-9_.$]{1,}/g)?.forEach((field) => fieldSet.add(field));
    metric.dimension
      .split(/[、,，/\\s]+/)
      .map((field) => field.trim())
      .filter((field) => field.length >= 2)
      .forEach((field) => fieldSet.add(field));
  });
  return fieldSet;
}

function canEditMetric(
  metric: MetricDictionaryItem,
  context: { isSuperAdmin: boolean; tenantId: string; userId: string },
) {
  if (context.isSuperAdmin) return true;
  return metric.createdBy === context.userId && (metric.tenantId || context.tenantId) === context.tenantId;
}

function normalizeMetricVisibilityForCurrentUser(
  metric: MetricDictionaryItem,
  context: { isSuperAdmin: boolean; isInstitutionAdmin: boolean },
) {
  if (context.isSuperAdmin) {
    return { ...metric, visibleRoles: [] };
  }
  if (context.isInstitutionAdmin) {
    return { ...metric, visibleInstitutions: [] };
  }
  return { ...metric, visibleInstitutions: [], visibleRoles: [] };
}

function toggleListValue(values: string[], value: string) {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

export function DataAssets() {
  const location = useLocation();
  const { isInstitutionAdmin, isSuperAdmin, selectedInstitution, tenantId, userId } = usePlatformContext();
  const section = getSection(location.pathname);
  const copy = sectionCopy[section];
  const sectionSubtitle = section === "data-management"
    ? `原始表仅读取当前机构 Data Crawler 已下载的 CSV；主题表和分析结果统一复用 Topic_Data 中的最新数据资产`
    : copy.subtitle;
  const [searchTerm, setSearchTerm] = useState("");
  const [metrics, setMetrics] = useState<MetricDictionaryItem[]>([]);
  const [metricDataSource, setMetricDataSource] = useState<MetricDataSource>("syncing");
  const [metricEditorOpen, setMetricEditorOpen] = useState(false);
  const [editingMetricId, setEditingMetricId] = useState<string | null>(null);
  const [metricForm, setMetricForm] = useState<MetricForm>(emptyMetricForm);
  const [metricVisibilityRoles, setMetricVisibilityRoles] = useState<string[]>(["操作员"]);
  const [metricNotice, setMetricNotice] = useState("");
  const [metricPage, setMetricPage] = useState(1);
  const [editingMetricTenantId, setEditingMetricTenantId] = useState<string | null>(null);
  const [metricImportOpen, setMetricImportOpen] = useState(false);
  const [metricImportFile, setMetricImportFile] = useState<File | null>(null);
  const [metricImportNotice, setMetricImportNotice] = useState("");
  const [metricImporting, setMetricImporting] = useState(false);
  const [versionMetric, setVersionMetric] = useState<MetricDictionaryItem | null>(null);

  const filteredMetrics = useMemo(
    () => metrics.filter((metric) => matchesMetric(metric, searchTerm)),
    [metrics, searchTerm],
  );

  const metricPageCount = Math.max(1, Math.ceil(filteredMetrics.length / metricPageSize));
  const boundedMetricPage = Math.min(metricPage, metricPageCount);
  const shownMetrics = filteredMetrics.slice(
    (boundedMetricPage - 1) * metricPageSize,
    boundedMetricPage * metricPageSize,
  );

  useEffect(() => {
    if (!isDemoFallbackEnabled() || metricDataSource !== "local") return;
    window.localStorage.setItem(metricDictionaryStorageKeyForTenant(tenantId), JSON.stringify(metrics));
  }, [metricDataSource, metrics, tenantId]);

  useEffect(() => {
    if (section !== "metrics") return;
    let cancelled = false;
    setMetricDataSource("syncing");
    setMetricNotice("");

    const syncMetrics = async () => {
      const demoMetrics = isDemoFallbackEnabled() ? await loadMetricDictionary(tenantId) : [];
      if (cancelled) return;
      try {
        // Visibility is evaluated against the authenticated account. Omitting
        // userId silently fell back to the legacy development identity and made
        // the saved, account-owned dictionary appear empty after a real login.
        const response = await fetchMetricDictionary({ tenantId, userId });
        if (cancelled) return;
        if (response.metrics.length) {
          setMetrics(response.metrics);
          setMetricDataSource("backend");
          setMetricNotice(`已连接后端指标字典：${selectedInstitution}`);
          return;
        }
        setMetricDataSource("backend");
        setMetricNotice(`后端指标字典为空：${selectedInstitution}，请由管理员导入或新增指标。`);
      } catch (error) {
        if (cancelled) return;
        if (isDemoFallbackEnabled()) {
          setMetrics(demoMetrics);
          setMetricDataSource("local");
          setMetricNotice(`后端指标字典暂不可用，已使用显式 demo 本地缓存。${apiErrorMessage(error, "")}`);
          return;
        }
        setMetrics([]);
        setMetricDataSource("unavailable");
        setMetricNotice(`${demoFallbackDisabledMessage("指标字典加载")} ${apiErrorMessage(error, "")}`);
      }
    };

    void syncMetrics();
    return () => {
      cancelled = true;
    };
  }, [section, selectedInstitution, tenantId, userId]);

  useEffect(() => {
    if (section !== "metrics" || !isInstitutionAdmin || isSuperAdmin) return;
    let cancelled = false;
    const syncRoleOptions = async () => {
      try {
        const response = await fetchAccessRolePolicies({ tenantId });
        if (cancelled) return;
        const permission = response.permissions.find((item) => item.institution === selectedInstitution);
        const roles = (permission?.roleConfigs || [])
          .filter((role) => role.name !== "管理员")
          .map((role) => role.name);
        setMetricVisibilityRoles(roles.length ? roles : ["操作员"]);
      } catch {
        if (!cancelled) setMetricVisibilityRoles(["操作员"]);
      }
    };
    void syncRoleOptions();
    return () => {
      cancelled = true;
    };
  }, [isInstitutionAdmin, isSuperAdmin, section, selectedInstitution, tenantId]);

  useEffect(() => {
    setMetricPage(1);
  }, [searchTerm, section]);

  useEffect(() => {
    setMetricPage((current) => Math.min(current, metricPageCount));
  }, [metricPageCount]);

  const openMetricEditor = (metric?: MetricDictionaryItem) => {
    if (metric) {
      setEditingMetricId(metric.metricId);
      setEditingMetricTenantId(metric.tenantId || tenantId);
      setMetricForm({
        ...metric,
        visibleInstitutions: metric.visibleInstitutions || [],
        visibleRoles: metric.visibleRoles || [],
      });
    } else {
      setEditingMetricId(null);
      setEditingMetricTenantId(null);
      setMetricForm({
        ...emptyMetricForm,
        metricId: getNextMetricId(metrics),
        visibleInstitutions: [],
        visibleRoles: isInstitutionAdmin && !isSuperAdmin ? metricVisibilityRoles : [],
      });
    }
    setMetricEditorOpen(true);
    setMetricNotice("");
  };

  const closeMetricEditor = () => {
    setMetricEditorOpen(false);
    setEditingMetricId(null);
    setEditingMetricTenantId(null);
    setMetricForm(emptyMetricForm);
  };

  const saveMetric = async () => {
    const metricName = metricForm.metricName.trim();
    if (!metricForm.metricId.trim() || !metricName) {
      setMetricNotice("请至少填写指标ID和指标名称。");
      return;
    }
    const duplicateMetric = metrics.some(
      (metric) => metric.metricName.trim() === metricName && metric.metricId !== editingMetricId,
    );
    if (duplicateMetric) {
      setMetricNotice(`${metricName}指标有重名，请检查指标`);
      return;
    }

    const nextMetric = normalizeMetricVisibilityForCurrentUser(
      { ...metricForm, metricName },
      { isSuperAdmin, isInstitutionAdmin },
    );
    const previousMetrics = metrics;
    if (editingMetricId) {
      setMetrics((current) =>
        current.map((metric) =>
          metric.metricId === editingMetricId ? { ...nextMetric, metricId: editingMetricId } : metric,
        ),
      );
      try {
        await saveMetricDictionaryItem({ tenantId: editingMetricTenantId || tenantId, userId, metric: { ...nextMetric, metricId: editingMetricId } });
        setMetricDataSource("backend");
        setMetricNotice("指标已修改并同步到后端。");
      } catch (error) {
        if (isDemoFallbackEnabled()) {
          setMetricDataSource("local");
          setMetricNotice(`指标已在 demo 本地缓存中修改，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        } else {
          setMetrics(previousMetrics);
          setMetricDataSource("unavailable");
          setMetricNotice(`${demoFallbackDisabledMessage("指标修改")} ${apiErrorMessage(error, "未知错误")}`);
          return;
        }
      }
    } else {
      setMetrics((current) => [nextMetric, ...current]);
      try {
        await saveMetricDictionaryItem({ tenantId, userId, metric: nextMetric });
        setMetricDataSource("backend");
        setMetricNotice("指标已新增并同步到后端。");
      } catch (error) {
        if (isDemoFallbackEnabled()) {
          setMetricDataSource("local");
          setMetricNotice(`指标已在 demo 本地缓存中新增，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        } else {
          setMetrics(previousMetrics);
          setMetricDataSource("unavailable");
          setMetricNotice(`${demoFallbackDisabledMessage("指标新增")} ${apiErrorMessage(error, "未知错误")}`);
          return;
        }
      }
    }
    closeMetricEditor();
  };

  const deleteMetric = async (metric: MetricDictionaryItem) => {
    const previousMetrics = metrics;
    setMetrics((current) => current.filter((item) => item.metricId !== metric.metricId));
    try {
      await deleteMetricDictionaryItem({ tenantId: metric.tenantId || tenantId, userId, metricId: metric.metricId });
      setMetricDataSource("backend");
      setMetricNotice("指标已删除并同步到后端。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setMetricDataSource("local");
        setMetricNotice(`指标已在 demo 本地缓存中删除，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
      } else {
        setMetrics(previousMetrics);
        setMetricDataSource("unavailable");
        setMetricNotice(`${demoFallbackDisabledMessage("指标删除")} ${apiErrorMessage(error, "未知错误")}`);
      }
    }
  };

  const closeMetricImport = () => {
    if (metricImporting) return;
    setMetricImportOpen(false);
    setMetricImportFile(null);
    setMetricImportNotice("");
  };

  const importMetrics = async () => {
    if (!metricImportFile) {
      setMetricImportNotice("请选择要导入的 .xlsx 指标文件。");
      return;
    }
    setMetricImporting(true);
    setMetricImportNotice("正在校验并同步指标，原有指标不会被覆盖…");
    try {
      const result = await importMetricDictionaryWorkbook({ tenantId, userId, file: metricImportFile });
      setMetrics((current) => [...result.created, ...current]);
      setMetricDataSource("backend");
      setMetricPage(1);
      const skippedNotice = result.skipped_count
        ? `；已合并 ${result.skipped_count} 条完全相同的重复行（${result.skipped_names.join("、")}）`
        : "";
      setMetricNotice(`已新增 ${result.created_count} 条指标${skippedNotice}，原指标未被覆盖。`);
      setMetricImportOpen(false);
      setMetricImportFile(null);
      setMetricImportNotice("");
    } catch (error) {
      setMetricImportNotice(`批量导入失败：${apiErrorMessage(error, "未知错误")}`);
    } finally {
      setMetricImporting(false);
    }
  };

  return (
    <div className="p-7">
      <div className="flex flex-col gap-4 mb-7 xl:flex-row xl:items-center xl:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">{copy.title}</h2>
            {section === "metrics" && metricNotice && (
              <span className={`text-[11px] ${/失败|不可用|错误/.test(metricNotice) ? "text-[#d93025]" : "text-[#258a3f]"}`}>
                {metricNotice}
              </span>
            )}
          </div>
          <p className="text-[13px] text-[#aeaeb2] mt-1">{sectionSubtitle}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[#aeaeb2]" />
            <input
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={copy.searchPlaceholder}
              className="h-9 w-[280px] rounded-lg border border-[#e5e5ea] bg-white pl-9 pr-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
            />
          </div>
          {section === "metrics" && (
            <>
              <button
                type="button"
                onClick={() => setMetricImportOpen(true)}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7] transition-colors"
              >
                <Upload className="w-3.5 h-3.5" />
                批量添加指标
              </button>
              <button
                type="button"
                onClick={() => openMetricEditor()}
                className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e] transition-colors"
              >
                <Plus className="w-3.5 h-3.5" />
                新增指标
              </button>
            </>
          )}
          {section === "data-management" && (
            <span className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366]">
              <Layers3 className="h-3.5 w-3.5 text-[#8a8a8e]" />
              原始表 / 主题表
            </span>
          )}
          {section === "knowledge" && (
            <span className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366]">
              <BookOpen className="h-3.5 w-3.5 text-[#8a8a8e]" />
              意图 / 文件 / 经验 / 行为习惯
            </span>
          )}
        </div>
      </div>

      {section === "metrics" && (
        <MetricManagement
          metrics={metrics}
          filteredMetrics={filteredMetrics}
          shownMetrics={shownMetrics}
          page={boundedMetricPage}
          pageCount={metricPageCount}
          onPageChange={setMetricPage}
          notice=""
          tenantId={tenantId}
          institutionName={selectedInstitution}
          dataSource={metricDataSource}
          onEdit={openMetricEditor}
          onDelete={deleteMetric}
          canEditMetric={(metric) => canEditMetric(metric, { isSuperAdmin, tenantId, userId })}
          canDeleteMetric={(metric) => canEditMetric(metric, { isSuperAdmin, tenantId, userId })}
          onVersions={setVersionMetric}
        />
      )}

      {section === "knowledge" && (
        <KnowledgeMemory
          searchTerm={searchTerm}
          tenantId={tenantId}
          userId={userId}
          canManage={isSuperAdmin || isInstitutionAdmin}
        />
      )}

      {section === "data-management" && <DataManagement searchTerm={searchTerm} tenantId={tenantId} userId={userId} isSuperAdmin={isSuperAdmin} />}

      {section === "quality" && <QualityMonitor searchTerm={searchTerm} tenantId={tenantId} userId={userId} />}

      {metricEditorOpen && (
        <MetricEditor
          editing={editingMetricId !== null}
          form={metricForm}
          notice={metricNotice}
          institutionName={selectedInstitution}
          isInstitutionAdmin={isInstitutionAdmin}
          isSuperAdmin={isSuperAdmin}
          roleOptions={metricVisibilityRoles}
          onChange={(key, value) => setMetricForm((current) => ({ ...current, [key]: value }))}
          onListChange={(key, value) => setMetricForm((current) => ({ ...current, [key]: value }))}
          onClose={closeMetricEditor}
          onSave={saveMetric}
        />
      )}
      {metricImportOpen && (
        <MetricBatchImportModal
          file={metricImportFile}
          importing={metricImporting}
          notice={metricImportNotice}
          onFileChange={setMetricImportFile}
          onClose={closeMetricImport}
          onImport={importMetrics}
        />
      )}
      {versionMetric && (
        <MetricVersionDrawer
          metric={versionMetric}
          tenantId={tenantId}
          userId={userId}
          onClose={() => setVersionMetric(null)}
        />
      )}
    </div>
  );
}

function MetricManagement({
  metrics,
  filteredMetrics,
  shownMetrics,
  page,
  pageCount,
  onPageChange,
  notice,
  tenantId,
  institutionName,
  dataSource,
  onEdit,
  onDelete,
  canEditMetric,
  canDeleteMetric,
  onVersions,
}: {
  metrics: MetricDictionaryItem[];
  filteredMetrics: MetricDictionaryItem[];
  shownMetrics: MetricDictionaryItem[];
  page: number;
  pageCount: number;
  onPageChange: (page: number) => void;
  notice: string;
  tenantId: string;
  institutionName: string;
  dataSource: MetricDataSource;
  onEdit: (metric: MetricDictionaryItem) => void;
  onDelete: (metric: MetricDictionaryItem) => void | Promise<void>;
  canEditMetric: (metric: MetricDictionaryItem) => boolean;
  canDeleteMetric: (metric: MetricDictionaryItem) => boolean;
  onVersions: (metric: MetricDictionaryItem) => void;
}) {
  const [columnWidths, setColumnWidths] = useState<Record<MetricColumnKey, number>>(defaultColumnWidths);
  const completeValueLogicCount = metrics.filter((metric) => metric.valueLogic.trim()).length;
  const valueLogicCompleteness = metrics.length
    ? `${Math.round((completeValueLogicCount / metrics.length) * 100)}%`
    : "0%";
  const referencedFieldCount = extractReferencedFields(metrics).size;
  const totalTableWidth =
    metricColumns.reduce((total, column) => total + columnWidths[column.key], 0) + 92;

  const startColumnResize = (key: MetricColumnKey, event: MouseEvent<HTMLSpanElement>) => {
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startWidth = columnWidths[key];
    const minWidth = metricColumns.find((column) => column.key === key)?.minWidth ?? 80;

    const onMouseMove = (moveEvent: globalThis.MouseEvent) => {
      const nextWidth = Math.max(minWidth, startWidth + moveEvent.clientX - startX);
      setColumnWidths((current) => ({ ...current, [key]: nextWidth }));
    };
    const onMouseUp = () => {
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    };
    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  };

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#f0f0f2] bg-white overflow-hidden">
        <div className="flex flex-col gap-2 border-b border-[#f0f0f2] px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-[13px] text-[#1d1d1f]">指标全集</div>
          </div>
          <DataPageSelector page={page} totalPages={pageCount} shownCount={filteredMetrics.length} totalCount={metrics.length} onChange={onPageChange} ariaLabel="指标分页" />
        </div>
        <div className="overflow-x-auto">
          <table className="table-fixed text-[12px]" style={{ width: totalTableWidth }}>
            <thead>
              <tr className="border-b border-[#f0f0f2] bg-[#fafbfc] text-[#8a8a8e]">
                {metricColumns.map((column) => (
                  <th
                    key={column.key}
                    style={{ width: columnWidths[column.key], minWidth: column.minWidth }}
                    className="relative px-3 py-2.5 text-left font-normal"
                  >
                    {column.label}
                    <span
                      role="separator"
                      aria-label={`调整${column.label}列宽`}
                      onMouseDown={(event) => startColumnResize(column.key, event)}
                      className="absolute right-0 top-1/2 h-5 w-1.5 -translate-y-1/2 cursor-col-resize rounded-full hover:bg-[#c7c7cc]"
                    />
                  </th>
                ))}
                <th className="sticky right-0 min-w-[92px] bg-[#fafbfc] px-3 py-2.5 text-left font-normal">
                  操作
                </th>
              </tr>
            </thead>
            <tbody>
              {shownMetrics.map((metric) => (
                <tr key={metric.metricId} className="border-b border-[#f8f8f8] last:border-b-0 hover:bg-[#fafbfc]">
                  {metricColumns.map((column) => (
                    <td
                      key={column.key}
                      style={{ width: columnWidths[column.key], minWidth: column.minWidth }}
                      className={`px-3 py-2.5 align-top text-[#3a3a3c] ${column.multiline ? "break-words leading-[1.6]" : "whitespace-nowrap"}`}
                    >
                      {metric[column.key] || <span className="text-[#c7c7cc]">未配置</span>}
                    </td>
                  ))}
                  <td className="sticky right-0 bg-white px-3 py-2.5 align-top">
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={() => onVersions(metric)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] text-[#636366] hover:bg-[#f2f2f7]"
                        aria-label={`查看${metric.metricName}版本`}
                      >
                        <History className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onEdit(metric)}
                        disabled={!canEditMetric(metric)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] text-[#636366] hover:bg-[#f2f2f7]"
                        aria-label={`编辑${metric.metricName}`}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(metric)}
                        disabled={!canDeleteMetric(metric)}
                        className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025] disabled:cursor-not-allowed disabled:opacity-30"
                        aria-label={`删除${metric.metricName}`}
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!shownMetrics.length && (
                <tr>
                  <td colSpan={metricColumns.length + 1} className="px-3 py-10 text-center text-[12px] text-[#aeaeb2]">
                    没有匹配的指标
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function MetricVersionDrawer({ metric, tenantId, userId, onClose }: { metric: MetricDictionaryItem; tenantId: string; userId: string; onClose: () => void }) {
  const [versions, setVersions] = useState<MetricSemanticVersion[]>([]);
  const [impact, setImpact] = useState<{ reports: string[]; skills: string[]; analysis_tasks: string[]; cache_entries: string[]; impact_count: number }>({ reports: [], skills: [], analysis_tasks: [], cache_entries: [], impact_count: 0 });
  const [expandedVersionId, setExpandedVersionId] = useState("");
  const [diff, setDiff] = useState<MetricVersionDiff>();
  const [notice, setNotice] = useState("正在加载版本…");
  const [busy, setBusy] = useState(false);

  const reload = async () => {
    try {
      const [versionResult, impact] = await Promise.all([
        fetchMetricVersions({ tenantId, userId, metricId: metric.metricId }),
        fetchMetricVersionImpact({ tenantId, userId, metricId: metric.metricId }),
      ]);
      setVersions(versionResult.versions);
      setImpact(impact);
      setNotice(versionResult.versions.length ? "" : "当前指标尚未创建语义版本。");
    } catch (error) {
      setNotice(apiErrorMessage(error, "指标版本加载失败。"));
    }
  };

  useEffect(() => { void reload(); }, [metric.metricId, tenantId, userId]);

  const createDraft = async () => {
    setBusy(true);
    try {
      await createMetricVersion({ tenantId, userId, metricId: metric.metricId, definition: { ...metric, semanticStatus: "draft", semanticVersion: `v${versions.length + 1}` } });
      await reload();
    } catch (error) { setNotice(apiErrorMessage(error, "创建版本草稿失败。")); }
    finally { setBusy(false); }
  };

  const transition = async (version: MetricSemanticVersion, action: "submit" | "publish" | "reject" | "archive") => {
    setBusy(true);
    try { await transitionMetricVersion({ tenantId, userId, versionId: version.version_id, action }); await reload(); }
    catch (error) { setNotice(apiErrorMessage(error, "版本状态更新失败。")); }
    finally { setBusy(false); }
  };

  const rollback = async (version: MetricSemanticVersion) => {
    setBusy(true);
    try { await rollbackMetricVersion({ tenantId, userId, metricId: metric.metricId, versionId: version.version_id }); await reload(); }
    catch (error) { setNotice(apiErrorMessage(error, "版本回滚失败。")); }
    finally { setBusy(false); }
  };

  const toggleDetails = async (version: MetricSemanticVersion) => {
    if (expandedVersionId === version.version_id) {
      setExpandedVersionId("");
      setDiff(undefined);
      return;
    }
    setExpandedVersionId(version.version_id);
    setDiff(undefined);
    const previous = versions.find((item) => item.version_no === version.version_no - 1);
    if (!previous) return;
    try {
      setDiff(await fetchMetricVersionDiff({ tenantId, userId, metricId: metric.metricId, leftVersionId: previous.version_id, rightVersionId: version.version_id }));
    } catch (error) {
      setNotice(apiErrorMessage(error, "版本差异加载失败。"));
    }
  };

  return <div className="fixed inset-0 z-[125] bg-black/10" role="dialog" aria-modal="true" aria-label={`${metric.metricName}版本管理`} onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <aside className="absolute bottom-0 right-0 top-0 flex w-[420px] max-w-full flex-col border-l border-[#e5e5ea] bg-white shadow-2xl shadow-black/10">
      <div className="flex items-center gap-2 border-b border-[#ececf0] px-4 py-3"><GitBranch className="h-4 w-4 text-[#636366]" /><div className="min-w-0 flex-1"><div className="truncate text-[13px] text-[#1d1d1f]">{metric.metricName} · 版本管理</div><div className="text-[10px] text-[#8a8a8e]">影响 {impact.impact_count} 个报表、Skill、任务或缓存</div></div><button type="button" onClick={onClose} className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭版本管理"><X className="h-4 w-4" /></button></div>
      <div className="flex-1 space-y-2 overflow-y-auto bg-[#f8f8fa] p-3">
        {impact.impact_count ? <MetricImpactSummary impact={impact} /> : null}
        {versions.map((version) => <div key={version.version_id} className="rounded-lg border border-[#e5e5ea] bg-white p-3"><button type="button" onClick={() => void toggleDetails(version)} className="flex w-full items-center justify-between text-left"><span className="text-[12px] text-[#1d1d1f]">v{version.version_no}</span><span className="flex items-center gap-1.5"><span className="rounded-full bg-[#f2f2f7] px-2 py-0.5 text-[9px] text-[#636366]">{version.status}</span>{expandedVersionId === version.version_id ? <ChevronUp className="h-3 w-3 text-[#8a8a8e]" /> : <ChevronDown className="h-3 w-3 text-[#8a8a8e]" />}</span></button><div className="mt-1 truncate font-mono text-[9px] text-[#aeaeb2]">{version.checksum}</div>{expandedVersionId === version.version_id ? <MetricVersionDetails version={version} diff={diff} /> : null}<div className="mt-3 flex flex-wrap gap-1.5">{version.status === "draft" && <button disabled={busy} onClick={() => void transition(version, "submit")} className="rounded-md border border-[#e5e5ea] px-2 py-1 text-[10px]">提交复核</button>}{version.status === "review" && <><button disabled={busy} onClick={() => void transition(version, "publish")} className="rounded-md bg-[#1d1d1f] px-2 py-1 text-[10px] text-white">批准发布</button><button disabled={busy} onClick={() => void transition(version, "reject")} className="rounded-md border border-[#e5e5ea] px-2 py-1 text-[10px]">驳回</button></>}{["draft", "rejected", "superseded"].includes(version.status) && <button disabled={busy} onClick={() => void transition(version, "archive")} className="rounded-md border border-[#e5e5ea] px-2 py-1 text-[10px]">归档</button>}{version.status !== "draft" && <button disabled={busy} onClick={() => void rollback(version)} className="rounded-md border border-[#e5e5ea] px-2 py-1 text-[10px]">创建回滚草稿</button>}</div></div>)}
        {notice && <div className="rounded-lg border border-dashed border-[#d9d9de] bg-white px-4 py-8 text-center text-[11px] text-[#8a8a8e]">{notice}</div>}
      </div>
      <div className="border-t border-[#ececf0] p-3"><button type="button" disabled={busy} onClick={() => void createDraft()} className="w-full rounded-lg bg-[#1d1d1f] px-3 py-2 text-[11px] text-white disabled:opacity-40">新建当前口径草稿</button></div>
    </aside>
  </div>;
}

function MetricImpactSummary({ impact }: { impact: { reports: string[]; skills: string[]; analysis_tasks: string[]; cache_entries: string[] } }) {
  const groups = [["报表", impact.reports], ["Skill", impact.skills], ["分析任务", impact.analysis_tasks], ["缓存", impact.cache_entries]] as const;
  return <div className="rounded-lg border border-[#e5e5ea] bg-white p-3"><div className="text-[11px] text-[#1d1d1f]">发布前影响分析</div><div className="mt-2 grid grid-cols-2 gap-1.5">{groups.map(([label, items]) => <div key={label} className="rounded-md bg-[#fafbfc] px-2 py-1.5 text-[9px] text-[#8a8a8e]"><span className="text-[#3a3a3c]">{label} {items.length}</span>{items.length ? <div className="mt-0.5 truncate font-mono" title={items.join("、")}>{items.slice(0, 3).join("、")}</div> : null}</div>)}</div></div>;
}

function MetricVersionDetails({ version, diff }: { version: MetricSemanticVersion; diff?: MetricVersionDiff }) {
  return <div className="mt-2 rounded-md bg-[#fafbfc] p-2.5 text-[9px] leading-4 text-[#636366]"><div className="grid grid-cols-2 gap-x-3 gap-y-1">{Object.entries(version.definition).slice(0, 12).map(([field, value]) => <div key={field} className="min-w-0"><span className="text-[#aeaeb2]">{field}：</span><span className="break-all">{formatVersionValue(value)}</span></div>)}</div><div className="mt-2 border-t border-[#ececf0] pt-2"><span className="text-[#8a8a8e]">相邻版本差异：</span>{diff ? `${diff.changed_count} 项` : version.version_no === 1 ? "初始版本" : "正在加载"}{diff?.changed_fields.map((item) => <div key={item.field} className="mt-1"><span className="text-[#3a3a3c]">{item.field}</span>：{formatVersionValue(item.before)} → {formatVersionValue(item.after)}</div>)}</div>{version.review_comment ? <div className="mt-2 border-t border-[#ececf0] pt-2">复核意见：{version.review_comment}</div> : null}</div>;
}

function formatVersionValue(value: unknown) {
  if (Array.isArray(value)) return value.map(String).join("、") || "空";
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "空");
}

function MetricBatchImportModal({
  file,
  importing,
  notice,
  onFileChange,
  onClose,
  onImport,
}: {
  file: File | null;
  importing: boolean;
  notice: string;
  onFileChange: (file: File | null) => void;
  onClose: () => void;
  onImport: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[620px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">批量添加指标</h3>
            <p className="mt-0.5 text-[11px] text-[#8a8a8e]">上传标准 Excel 后新增指标；完全相同的重复行只导入一次，口径冲突时整批不写入。</p>
          </div>
          <button type="button" onClick={onClose} disabled={importing} className="rounded-lg px-3 py-1.5 text-[12px] text-[#8a8a8e] hover:bg-[#f2f2f7] disabled:opacity-40">关闭</button>
        </div>
        <div className="space-y-4 p-5">
          <label className="block rounded-xl border border-dashed border-[#d1d1d6] bg-[#fafbfc] p-5 text-center hover:bg-[#f7f7f8]">
            <Upload className="mx-auto h-5 w-5 text-[#636366]" />
            <span className="mt-2 block text-[13px] text-[#1d1d1f]">{file ? file.name : "选择指标 Excel 文件"}</span>
            <span className="mt-1 block text-[11px] text-[#8a8a8e]">仅支持 .xlsx，最大 8MB</span>
            <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only" onChange={(event) => onFileChange(event.target.files?.[0] || null)} />
          </label>
          <div className="grid gap-2 rounded-lg border border-[#f0f0f2] bg-white p-3 text-[11px] text-[#636366] sm:grid-cols-2">
            <span>✓ 读取：名称、口径、取值逻辑、表名与维度</span>
            <span>✓ 同步：场景、来源、统计时间与引用文档</span>
            <span>✓ 保留：原指标名称、数据机构与备注</span>
            <span>✓ 规则：相同重复行自动合并，冲突名称整批失败</span>
          </div>
          {notice && <div className={`rounded-lg px-3 py-2 text-[12px] leading-[1.6] ${/失败|无效|无法|缺少|为空|超过|冲突|重名/.test(notice) ? "bg-[#fff5f4] text-[#c5221f]" : "bg-[#fafbfc] text-[#636366]"}`}>{notice}</div>}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[#f0f0f2] px-5 py-4">
          <button type="button" onClick={onClose} disabled={importing} className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-40">取消</button>
          <button type="button" onClick={onImport} disabled={!file || importing} className="inline-flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40">
            <Upload className="h-3.5 w-3.5" />
            {importing ? "正在导入" : "开始导入"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MetricEditor({
  editing,
  form,
  notice,
  institutionName,
  isInstitutionAdmin,
  isSuperAdmin,
  roleOptions,
  onChange,
  onListChange,
  onClose,
  onSave,
}: {
  editing: boolean;
  form: MetricForm;
  notice: string;
  institutionName: string;
  isInstitutionAdmin: boolean;
  isSuperAdmin: boolean;
  roleOptions: string[];
  onChange: (key: keyof MetricForm, value: string) => void;
  onListChange: (key: "visibleInstitutions" | "visibleRoles", value: string[]) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[880px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">{editing ? "修改指标" : "新增指标"}</h3>
            <p className="mt-0.5 text-[11px] text-[#aeaeb2]">
              指标ID由系统自动生成；指标名称建议采用“客群 + 业务节点 + 计算逻辑”的命名规则
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-[12px] text-[#8a8a8e] hover:bg-[#f2f2f7]"
          >
            关闭
          </button>
        </div>
        <div className="grid max-h-[70vh] gap-4 overflow-y-auto p-5 md:grid-cols-2">
          {metricColumns.map((column) => (
            <label key={column.key} className={column.multiline ? "md:col-span-2" : ""}>
              <span className="mb-1.5 block text-[12px] text-[#636366]">{column.label}</span>
              {column.multiline ? (
                <textarea
                  value={form[column.key]}
                  onChange={(event) => onChange(column.key, event.target.value)}
                  disabled={column.readonly}
                  className="min-h-[82px] w-full rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-3 py-2 text-[12px] leading-[1.7] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                />
              ) : (
                <input
                  value={form[column.key]}
                  onChange={(event) => onChange(column.key, event.target.value)}
                  disabled={column.readonly}
                  className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc] disabled:text-[#8a8a8e]"
                />
              )}
            </label>
          ))}
          <MetricVisibilityEditor
            institutionName={institutionName}
            isInstitutionAdmin={isInstitutionAdmin}
            isSuperAdmin={isSuperAdmin}
            roleOptions={roleOptions}
            visibleInstitutions={form.visibleInstitutions || []}
            visibleRoles={form.visibleRoles || []}
            onChange={onListChange}
          />
        </div>
        <div className="flex items-center justify-between border-t border-[#f0f0f2] px-5 py-4">
          <span className="text-[12px] text-[#d93025]">{notice}</span>
          <button
            type="button"
            onClick={onSave}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e]"
          >
            <FilePlus2 className="w-3.5 h-3.5" />
            保存指标
          </button>
        </div>
      </div>
    </div>
  );
}

function MetricVisibilityEditor({
  institutionName,
  isInstitutionAdmin,
  isSuperAdmin,
  roleOptions,
  visibleInstitutions,
  visibleRoles,
  onChange,
}: {
  institutionName: string;
  isInstitutionAdmin: boolean;
  isSuperAdmin: boolean;
  roleOptions: string[];
  visibleInstitutions: string[];
  visibleRoles: string[];
  onChange: (key: "visibleInstitutions" | "visibleRoles", value: string[]) => void;
}) {
  if (isSuperAdmin) {
    const allSelected = operatingTenantNames.every((tenant) => visibleInstitutions.includes(tenant));
    return (
      <div className="md:col-span-2 rounded-lg border border-[#f0f0f2] bg-white p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-[13px] text-[#1d1d1f]">可见机构</div>
            <div className="mt-0.5 text-[11px] text-[#8a8a8e]">不勾选时仅创建人自己可见。</div>
          </div>
          <button
            type="button"
            onClick={() => onChange("visibleInstitutions", allSelected ? [] : operatingTenantNames)}
            className="text-[11px] text-[#1d1d1f] hover:underline"
          >
            {allSelected ? "取消" : "全部机构"}
          </button>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          {operatingTenantNames.map((tenant) => (
            <MetricVisibilityCheckbox
              key={tenant}
              label={tenant}
              checked={visibleInstitutions.includes(tenant)}
              onChange={() => onChange("visibleInstitutions", toggleListValue(visibleInstitutions, tenant))}
            />
          ))}
        </div>
      </div>
    );
  }

  if (isInstitutionAdmin) {
    const allSelected = roleOptions.every((role) => visibleRoles.includes(role));
    return (
      <div className="md:col-span-2 rounded-lg border border-[#f0f0f2] bg-white p-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-[13px] text-[#1d1d1f]">可见角色</div>
            <div className="mt-0.5 text-[11px] text-[#8a8a8e]">
              仅限 {institutionName} 的操作员和自定义角色；不勾选时仅创建人自己可见。
            </div>
          </div>
          <button
            type="button"
            onClick={() => onChange("visibleRoles", allSelected ? [] : roleOptions)}
            className="text-[11px] text-[#1d1d1f] hover:underline"
          >
            {allSelected ? "取消" : "全选"}
          </button>
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {roleOptions.map((role) => (
            <MetricVisibilityCheckbox
              key={role}
              label={role}
              checked={visibleRoles.includes(role)}
              onChange={() => onChange("visibleRoles", toggleListValue(visibleRoles, role))}
            />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="md:col-span-2 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4 text-[12px] text-[#636366]">
      当前角色新增的指标仅自己可见，不能授权给其他机构或角色。
    </div>
  );
}

function MetricVisibilityCheckbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <label className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[12px] ${checked ? "border-[#d1d1d6] bg-[#f8f8fa] text-[#1d1d1f]" : "border-[#f0f0f2] bg-white text-[#636366]"}`}>
      <input type="checkbox" checked={checked} onChange={onChange} className="h-3.5 w-3.5 accent-[#1d1d1f]" />
      {label}
    </label>
  );
}

const emptyAssetBundle: DataAssetBundle = {
  tenant_id: "",
  source_mode: "csv_folder",
  csv_source: {
    mode: "csv_folder",
    root: "",
    available: false,
    file_count: 0,
    scanned_at: "",
    files: [],
  },
  raw_tables: [],
  topic_tables: [],
  intents: [],
  analysis_experiences: [],
      behavior_habits: [],
      knowledge_files: [],
      analysis_skills: [],
      external_tools: [],
      analysis_shortcuts: [],
      page_data: [],
      table_relationships: [],
      relationships: [],
      count: {},
};

function useDataAssetBundle(tenantId: string, userId: string, scope?: "knowledge") {
  const [bundle, setBundle] = useState<DataAssetBundle>(emptyAssetBundle);
  const [notice, setNotice] = useState("资产配置同步中...");
  const [refreshToken, setRefreshToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const syncAssets = async () => {
      setNotice("资产配置同步中...");
      try {
        const response = await fetchDataAssets({ tenantId, userId, scope });
        if (response.status === "loading") {
          if (!cancelled) {
            setNotice(response.message || "当前机构 Data Crawler 原始数据正在准备中，请稍候...");
            retryTimer = window.setTimeout(() => void syncAssets(), 700);
          }
          return;
        }
        if (!cancelled) {
          setBundle(response);
          setNotice("");
        }
      } catch (error) {
        if (!cancelled) {
          setBundle(emptyAssetBundle);
          setNotice(`${demoFallbackDisabledMessage("数据资产配置加载")} ${apiErrorMessage(error, "未知错误")}`);
        }
      }
    };
    void syncAssets();
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    };
  }, [tenantId, userId, scope, refreshToken]);

  const upsertRawTable = (item: RawTableAsset) => {
    setBundle((current) => ({
      ...current,
      raw_tables: current.raw_tables.some((existing) => existing.id === item.id)
        ? current.raw_tables.map((existing) => (existing.id === item.id ? item : existing))
        : [item, ...current.raw_tables],
    }));
  };

  const upsertTopicTable = (item: TopicTableAsset) => {
    setBundle((current) => ({
      ...current,
      topic_tables: current.topic_tables.some((existing) => existing.id === item.id)
        ? current.topic_tables.map((existing) => (existing.id === item.id ? item : existing))
        : [item, ...current.topic_tables],
    }));
  };

  const upsertPageData = (item: PageDataAsset) => {
    setBundle((current) => ({
      ...current,
      page_data: current.page_data.some((existing) => existing.id === item.id)
        ? current.page_data.map((existing) => (existing.id === item.id ? item : existing))
        : [item, ...current.page_data],
    }));
  };

  const upsertTableRelationship = (item: TableRelationshipAsset) => {
    setBundle((current) => ({
      ...current,
      table_relationships: current.table_relationships.some((existing) => existing.id === item.id)
        ? current.table_relationships.map((existing) => (existing.id === item.id ? item : existing))
        : [item, ...current.table_relationships],
    }));
  };

  const removeTable = (itemType: "raw_table" | "topic_table" | "page_data", itemId: string) => {
    setBundle((current) => itemType === "raw_table"
      ? { ...current, raw_tables: current.raw_tables.filter((item) => item.id !== itemId) }
      : itemType === "topic_table"
        ? { ...current, topic_tables: current.topic_tables.filter((item) => item.id !== itemId) }
        : { ...current, page_data: current.page_data.filter((item) => item.id !== itemId) });
  };

  return {
    bundle,
    notice,
    upsertRawTable,
    upsertTopicTable,
    upsertPageData,
    upsertTableRelationship,
    removeTable,
    setNotice,
    reload: () => setRefreshToken((current) => current + 1),
  };
}

function DataManagement({ searchTerm, tenantId, userId, isSuperAdmin }: { searchTerm: string; tenantId: string; userId: string; isSuperAdmin: boolean }) {
  const [activeTab, setActiveTab] = useState<DataManagementTab | "relationships">("raw");
  const [rawPage, setRawPage] = useState(1);
  const [singlePageDataPage, setSinglePageDataPage] = useState(1);
  const [multiPageDataPage, setMultiPageDataPage] = useState(1);
  const [customerSegmentPage, setCustomerSegmentPage] = useState(1);
  const [topicPage, setTopicPage] = useState(1);
  const [createType, setCreateType] = useState<"topic" | null>(null);
  const [rawUploadOpen, setRawUploadOpen] = useState(false);
  const [relationshipCreateRequestId, setRelationshipCreateRequestId] = useState(0);
  const [pageDataEditor, setPageDataEditor] = useState<{ scope: PageDataInstitutionScope; asset: PageDataAsset | null } | null>(null);
  const [multiInstitutionCandidates, setMultiInstitutionCandidates] = useState<MultiInstitutionPageDataCandidate[]>([]);
  const [multiCandidatesLoading, setMultiCandidatesLoading] = useState(false);
  const [multiCandidatesError, setMultiCandidatesError] = useState("");
  const [pendingDelete, setPendingDelete] = useState<{ itemType: "raw_table" | "topic_table"; item: RawTableAsset | TopicTableAsset } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [dataCrawlerScheduleStatuses, setDataCrawlerScheduleStatuses] = useState<Record<string, DataCrawlerScheduleListStatus>>({});
  const [dataCrawlerScheduleStatusError, setDataCrawlerScheduleStatusError] = useState("");
  const [dataCrawlerScheduleStatusRefreshToken, setDataCrawlerScheduleStatusRefreshToken] = useState(0);
  const { bundle, notice, upsertRawTable, upsertTopicTable, upsertPageData, upsertTableRelationship, removeTable, setNotice, reload } = useDataAssetBundle(tenantId, userId);
  const keyword = searchTerm.trim().toLowerCase();
  const rawTables = bundle.raw_tables.filter((item) => assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const topicTables = bundle.topic_tables.filter((item) => assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const singlePageDataAssets = bundle.page_data.filter((item) => pageDataScope(item) === "single_institution" && assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const multiPageDataAssets = bundle.page_data.filter((item) => pageDataScope(item) === "multi_institution" && assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const customerSegmentPageDataAssets = bundle.page_data.filter((item) => pageDataScope(item) === "customer_segment" && assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const customerDetailTables = bundle.raw_tables.filter((item) => Boolean(customerDetailTableKey(item)));
  const rawPageCount = Math.max(1, Math.ceil(rawTables.length / dataTablePageSize));
  const topicPageCount = Math.max(1, Math.ceil(topicTables.length / dataTablePageSize));
  const singlePageDataPageCount = Math.max(1, Math.ceil(singlePageDataAssets.length / dataTablePageSize));
  const multiPageDataPageCount = Math.max(1, Math.ceil(multiPageDataAssets.length / dataTablePageSize));
  const customerSegmentPageCount = Math.max(1, Math.ceil(customerSegmentPageDataAssets.length / dataTablePageSize));
  const pagedRawTables = rawTables.slice((Math.min(rawPage, rawPageCount) - 1) * dataTablePageSize, Math.min(rawPage, rawPageCount) * dataTablePageSize);
  const pagedTopicTables = topicTables.slice((Math.min(topicPage, topicPageCount) - 1) * dataTablePageSize, Math.min(topicPage, topicPageCount) * dataTablePageSize);
  const pagedSinglePageDataAssets = singlePageDataAssets.slice((Math.min(singlePageDataPage, singlePageDataPageCount) - 1) * dataTablePageSize, Math.min(singlePageDataPage, singlePageDataPageCount) * dataTablePageSize);
  const pagedMultiPageDataAssets = multiPageDataAssets.slice((Math.min(multiPageDataPage, multiPageDataPageCount) - 1) * dataTablePageSize, Math.min(multiPageDataPage, multiPageDataPageCount) * dataTablePageSize);
  const pagedCustomerSegmentPageDataAssets = customerSegmentPageDataAssets.slice((Math.min(customerSegmentPage, customerSegmentPageCount) - 1) * dataTablePageSize, Math.min(customerSegmentPage, customerSegmentPageCount) * dataTablePageSize);
  const currentPage = activeTab === "raw" ? Math.min(rawPage, rawPageCount) : activeTab === "single_page" ? Math.min(singlePageDataPage, singlePageDataPageCount) : activeTab === "multi_page" ? Math.min(multiPageDataPage, multiPageDataPageCount) : activeTab === "customer_segment_page" ? Math.min(customerSegmentPage, customerSegmentPageCount) : Math.min(topicPage, topicPageCount);
  const currentPageCount = activeTab === "raw" ? rawPageCount : activeTab === "single_page" ? singlePageDataPageCount : activeTab === "multi_page" ? multiPageDataPageCount : activeTab === "customer_segment_page" ? customerSegmentPageCount : topicPageCount;
  const currentTotal = activeTab === "raw" ? rawTables.length : activeTab === "single_page" ? singlePageDataAssets.length : activeTab === "multi_page" ? multiPageDataAssets.length : activeTab === "customer_segment_page" ? customerSegmentPageDataAssets.length : topicTables.length;
  const setCurrentPage = activeTab === "raw" ? setRawPage : activeTab === "single_page" ? setSinglePageDataPage : activeTab === "multi_page" ? setMultiPageDataPage : activeTab === "customer_segment_page" ? setCustomerSegmentPage : setTopicPage;

  useEffect(() => {
    setRawPage(1);
    setSinglePageDataPage(1);
    setMultiPageDataPage(1);
    setCustomerSegmentPage(1);
    setTopicPage(1);
  }, [activeTab, keyword, tenantId]);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    setDataCrawlerScheduleStatusError("");
    const syncStatuses = async (attempt: number) => {
      try {
        const response = await fetchDataCrawlerScheduleStatuses({ tenantId, userId });
        if (cancelled) return;
        setDataCrawlerScheduleStatuses(response.items || {});
        setDataCrawlerScheduleStatusError("");
      } catch (error) {
        if (cancelled) return;
        if (attempt < 2) {
          retryTimer = window.setTimeout(() => void syncStatuses(attempt + 1), 800 * (attempt + 1));
          return;
        }
        setDataCrawlerScheduleStatuses({});
        setDataCrawlerScheduleStatusError(apiErrorMessage(error, "定时任务状态同步失败。"));
      }
    };
    void syncStatuses(0);
    return () => {
      cancelled = true;
      if (retryTimer) window.clearTimeout(retryTimer);
    };
  }, [tenantId, userId, dataCrawlerScheduleStatusRefreshToken]);

  const saveAsset = async (itemType: "topic_table", item: TopicTableAsset) => {
    const creating = !item.id;
    try {
      const response = await saveDataAssetItem({ tenantId, itemType, item });
      upsertTopicTable(response.item as TopicTableAsset);
      setNotice(creating ? "数据表已新增并显示在列表最上方；资产版本已提交复核。" : "资产新版本已提交复核；发布前不会进入智能分析运行时。");
      return response.item;
    } catch (error) {
      setNotice(`资产配置保存失败：${apiErrorMessage(error, "未知错误")}`);
      throw error;
    }
  };

  const savePageData = async (item: PageDataAsset) => {
    try {
      const response = await saveDataAssetItem({ tenantId, userId, itemType: "page_data", item });
      upsertPageData(response.item as PageDataAsset);
      const savedScope = pageDataScope(response.item as PageDataAsset);
      setNotice(`${savedScope === "multi_institution" ? "多机构" : savedScope === "customer_segment" ? "分客群" : "单机构"}页面数据已保存并进入对应页面的数据下拉框；原始 CSV 保持只读。`);
    } catch (error) {
      setNotice(`页面数据保存失败：${apiErrorMessage(error, "未知错误")}`);
      throw error;
    }
  };

  const openPageDataEditor = async (scope: PageDataInstitutionScope, asset: PageDataAsset | null = null) => {
    setPageDataEditor({ scope, asset });
    if (scope !== "multi_institution") return;
    setMultiCandidatesLoading(true);
    setMultiCandidatesError("");
    try {
      const response = await fetchMultiInstitutionPageDataCandidates({ tenantId, userId });
      setMultiInstitutionCandidates(response.candidates);
    } catch (error) {
      setMultiInstitutionCandidates([]);
      setMultiCandidatesError(apiErrorMessage(error, "多机构关联数据集读取失败。"));
    } finally {
      setMultiCandidatesLoading(false);
    }
  };

  const saveRawTableMetadata = async (table: RawTableAsset, fields: RawField[]) => {
    if (!table.sourceKey || !table.schemaFingerprint) throw new Error("当前原始表缺少稳定来源或结构指纹，不能保存字段配置。");
    const normalizedFields = normalizeFieldSemantics(fields);
    const keys = primaryKeyFields(normalizedFields);
    try {
      const response = await saveDataAssetItem({
        tenantId,
        itemType: "raw_table",
        item: {
          id: table.metadataConfigId || `raw_metadata_${table.sourceKey}`,
          lockVersion: table.metadataConfigLockVersion,
          sourceKey: table.sourceKey,
          schemaFingerprint: table.schemaFingerprint,
          fields: normalizedFields,
        },
      });
      const saved = response.item as RawTableAsset;
      upsertRawTable({
        ...table,
        fields: normalizedFields,
        primaryKey: keys[0] || "",
        primaryKeys: keys,
        dateField: normalizedFields.find((field) => field.semanticRole === "date")?.fieldNameEn || "",
        metadataConfigId: saved.id,
        metadataConfigLockVersion: saved.lockVersion,
      } as RawTableAsset);
      setNotice(`字段配置已保存：${keys.length > 1 ? `联合主键 ${keys.join(" + ")}` : `主键 ${keys[0]}`}；原始 CSV 保持只读。`);
    } catch (error) {
      setNotice(`字段配置保存失败：${apiErrorMessage(error, "未知错误")}`);
      throw error;
    }
  };

  const updateExternalReference = async (table: RawTableAsset, mode: "private" | "shared") => {
    if (!table.sourceKey || !table.schemaFingerprint) {
      setNotice("当前原始表缺少可验证的数据源身份，暂不能设置外部引用。");
      return;
    }
    const previous = table.externalReferenceMode || "private";
    upsertRawTable({ ...table, externalReferenceMode: mode, externalReferenceSchemaChanged: false });
    try {
      const response = await updateRawTableExternalReference({
        tenantId,
        sourceKey: table.sourceKey,
        mode,
        schemaFingerprint: table.schemaFingerprint,
      });
      upsertRawTable({
        ...table,
        externalReferenceMode: response.external_reference.mode,
        externalReferenceUpdatedAt: response.external_reference.updatedAt,
        externalReferenceSchemaChanged: false,
      });
      setNotice(mode === "shared" ? "已授权 WorkBuddy、Codex、QWork Bridge 引用该原始表；CSV 文件保持只读。" : "该原始表已改为单独使用，三个 Bridge 渠道均不再可读取。 ");
    } catch (error) {
      upsertRawTable({ ...table, externalReferenceMode: previous });
      setNotice(`外部引用设置失败：${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteDataAssetItem({ tenantId, itemType: pendingDelete.itemType, itemId: pendingDelete.item.id });
      removeTable(pendingDelete.itemType, pendingDelete.item.id);
      setNotice("数据表记录已删除并同步到后端。");
      setPendingDelete(null);
    } catch (error) {
      setNotice(`数据表删除失败：${apiErrorMessage(error, "未知错误")}`);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-5">
      <AssetNotice notice={notice} />
      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex items-center justify-between gap-3">
          <h3 className="shrink-0 text-[14px] leading-8 text-[#1d1d1f]">站内数据</h3>
          <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
            <div className="flex max-w-full flex-nowrap items-center gap-2 overflow-x-auto [&>*]:shrink-0" data-data-management-control-row="true">
              {activeTab === "raw" && (
                <button
                  type="button"
                  onClick={() => setRawUploadOpen(true)}
                  className="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-[#0f8f58] px-3 text-[12px] text-white hover:bg-[#0b7d4c]"
                  data-active-tab-action="upload-static-workbook"
                >
                  <Upload className="h-3.5 w-3.5" />
                  上传Excel文件
                </button>
              )}
              {activeTab === "relationships" && (
                <button
                  type="button"
                  onClick={() => setRelationshipCreateRequestId((value) => value + 1)}
                  className="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-[#0f8f58] px-3 text-[12px] text-white hover:bg-[#0b7d4c]"
                  data-active-tab-action="create-table-relationship"
                >
                  <Plus className="h-3.5 w-3.5" />
                  新增表关系
                </button>
              )}
              {activeTab === "topic" && (
                <button
                  type="button"
                  aria-label="新增主题表"
                  onClick={() => setCreateType("topic")}
                  className="inline-flex h-8 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e]"
                >
                  <Plus className="h-3.5 w-3.5" />
                  新增主题表
                </button>
              )}
              {isSuperAdmin && activeTab === "single_page" && <PageDataCreateButton scope="single_institution" onClick={() => void openPageDataEditor("single_institution")} />}
              {isSuperAdmin && activeTab === "multi_page" && <PageDataCreateButton scope="multi_institution" onClick={() => void openPageDataEditor("multi_institution")} />}
              {isSuperAdmin && activeTab === "customer_segment_page" && <PageDataCreateButton scope="customer_segment" onClick={() => void openPageDataEditor("customer_segment")} />}
              <SegmentedTabs
                tabs={[
                  { key: "raw", label: `原始表 ${rawTables.length}` },
                  { key: "single_page", label: `单机构页面 ${singlePageDataAssets.length}` },
                  { key: "relationships", label: `表关系 ${bundle.table_relationships.length}` },
                  { key: "multi_page", label: `多机构页面 ${multiPageDataAssets.length}` },
                  { key: "customer_segment_page", label: `分客群页面 ${customerSegmentPageDataAssets.length}` },
                  { key: "topic", label: `主题表 ${topicTables.length}` },
                ]}
                activeKey={activeTab}
                onChange={(key) => setActiveTab(key as DataManagementTab | "relationships")}
              />
            </div>
            {activeTab !== "relationships" && currentTotal > dataTablePageSize && (
              <div data-data-management-pagination="true">
                <DataTablePagination
                  compact
                  page={currentPage}
                  totalPages={currentPageCount}
                  total={currentTotal}
                  onChange={setCurrentPage}
                />
              </div>
            )}
          </div>
        </div>

        {activeTab === "raw" ? (
          <div className="space-y-3">
            {dataCrawlerScheduleStatusError && <div role="status" className="flex items-center justify-between gap-3 rounded-lg border border-[#f3d5d0] bg-[#fff8f7] px-3 py-2 text-[11px] text-[#a83c32]"><span>定时状态同步失败，列表不会显示未经确认的“已定时”标签。</span><button type="button" onClick={() => setDataCrawlerScheduleStatusRefreshToken((current) => current + 1)} className="shrink-0 rounded-md border border-[#e8bbb4] bg-white px-2.5 py-1 text-[10px] font-medium text-[#9b3027] hover:bg-[#fff3f1]">重试</button></div>}
            {pagedRawTables.map((table) => (
              <RawTableCard
                key={table.id}
                table={table}
                tenantId={tenantId}
                userId={userId}
                scheduleStatus={table.sourceKey ? dataCrawlerScheduleStatuses[table.sourceKey] : undefined}
                onScheduleStatusChange={(sourceKey, status) => setDataCrawlerScheduleStatuses((current) => {
                  const next = { ...current };
                  if (status) next[sourceKey] = status;
                  else delete next[sourceKey];
                  return next;
                })}
                onExternalReferenceChange={updateExternalReference}
                onSave={saveRawTableMetadata}
              />
            ))}
            {!rawTables.length && <EmptyAssetState text="暂无匹配的原始表配置" />}
          </div>
        ) : activeTab === "single_page" ? (
          <PageDataAssetList
            assets={pagedSinglePageDataAssets}
            keyword={keyword}
            scope="single_institution"
            canManage={isSuperAdmin}
            onEdit={(asset) => void openPageDataEditor("single_institution", asset)}
            onPageChange={async (asset, page) => { await savePageData({ ...asset, institutionScope: "single_institution", targetPages: [page] }); }}
            onDelete={async (asset) => {
              await deleteDataAssetItem({ tenantId, userId, itemType: "page_data", itemId: asset.id });
              removeTable("page_data", asset.id);
              setNotice("单机构页面数据配置已删除；对应页面会在下次读取时移除该入口。");
            }}
          />
        ) : activeTab === "multi_page" ? (
          <PageDataAssetList
            assets={pagedMultiPageDataAssets}
            keyword={keyword}
            scope="multi_institution"
            canManage={isSuperAdmin}
            onEdit={(asset) => void openPageDataEditor("multi_institution", asset)}
            onPageChange={async () => undefined}
            onDelete={async (asset) => {
              await deleteDataAssetItem({ tenantId, userId, itemType: "page_data", itemId: asset.id });
              removeTable("page_data", asset.id);
              setNotice("多机构页面数据配置已删除；多机构分析会在下次读取时移除该入口。");
            }}
          />
        ) : activeTab === "customer_segment_page" ? (
          <PageDataAssetList
            assets={pagedCustomerSegmentPageDataAssets}
            keyword={keyword}
            scope="customer_segment"
            canManage={isSuperAdmin}
            onEdit={(asset) => void openPageDataEditor("customer_segment", asset)}
            onPageChange={async () => undefined}
            onDelete={async (asset) => {
              await deleteDataAssetItem({ tenantId, userId, itemType: "page_data", itemId: asset.id });
              removeTable("page_data", asset.id);
              setNotice("分客群页面数据配置已删除；分客群分析会在下次读取时移除该入口。");
            }}
          />
        ) : activeTab === "topic" ? (
          <div className="space-y-3">
            {pagedTopicTables.map((topic) => (
              <TopicTableCard
                key={topic.id}
                tenantId={tenantId}
                topic={topic}
                onSave={async (item) => { await saveAsset("topic_table", item); }}
                onDelete={() => setPendingDelete({ itemType: "topic_table", item: topic })}
              />
            ))}
            {!topicTables.length && <EmptyAssetState text="暂无匹配的主题表配置" />}
          </div>
        ) : <TableRelationshipWorkspace tenantId={tenantId} userId={userId} relationships={bundle.table_relationships} keyword={keyword} onNotice={setNotice} onChanged={(saved) => { if (saved) upsertTableRelationship(saved); else reload(); }} createRequestId={relationshipCreateRequestId} />}
      </div>
      {rawUploadOpen && <StaticWorkbookUploadModal
        tenantId={tenantId}
        userId={userId}
        onClose={() => setRawUploadOpen(false)}
        onUploaded={(result) => {
          setRawUploadOpen(false);
          setNotice(result.duplicate ? `该工作簿已上传过，已保留原有 ${result.table_count || result.tables?.length || 0} 张静态原始表。` : `工作簿上传成功，已按非空 Sheet 生成 ${result.table_count || result.tables?.length || 0} 张静态原始表。`);
          reload();
        }}
      />}
      {createType && (
        <DataTableCreateModal
          tenantId={tenantId}
          tableType={createType}
          onClose={() => setCreateType(null)}
          onSave={async (item) => {
            await saveAsset("topic_table", item as TopicTableAsset);
            setCreateType(null);
          }}
        />
      )}
      {pageDataEditor && <PageDataCreateModal
        scope={pageDataEditor.scope}
        rawTables={pageDataEditor.scope === "customer_segment" ? customerDetailTables : rawTables}
        multiInstitutionCandidates={multiInstitutionCandidates}
        candidatesLoading={multiCandidatesLoading}
        candidatesError={multiCandidatesError}
        initialAsset={pageDataEditor.asset}
        onClose={() => setPageDataEditor(null)}
        onSave={async (asset) => { await savePageData(asset); setPageDataEditor(null); }}
      />}
      {pendingDelete && (
        <DataTableDeleteConfirm
          itemType={pendingDelete.itemType}
          item={pendingDelete.item}
          deleting={deleting}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void confirmDelete()}
        />
      )}
    </div>
  );
}

function StaticWorkbookUploadModal({
  tenantId,
  userId,
  onClose,
  onUploaded,
}: {
  tenantId: string;
  userId: string;
  onClose: () => void;
  onUploaded: (result: RawFileUpload) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !uploading) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, uploading]);

  const upload = async () => {
    if (!file) {
      setError("请选择 Excel 工作簿。");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setError("仅支持 .xlsx 文件；飞书表格请先导出为 Excel 工作簿后上传。");
      return;
    }
    setUploading(true);
    setError("");
    try {
      const response = await uploadRawDataFile({ tenantId, userId, file });
      onUploaded(response.file);
    } catch (uploadError) {
      setError(apiErrorMessage(uploadError, "工作簿上传失败。"));
    } finally {
      setUploading(false);
    }
  };

  return createPortal(<div className="fixed inset-0 z-[160] flex items-center justify-center bg-[rgba(18,33,27,0.32)] p-4 sm:p-6" data-static-workbook-modal-overlay="true" onMouseDown={(event) => { if (event.target === event.currentTarget && !uploading) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="static-workbook-dialog-title" aria-describedby="static-workbook-dialog-description" aria-busy={uploading} data-static-workbook-dialog="true" className="flex max-h-[82vh] w-full max-w-[600px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15" style={{ contain: "layout paint" }} onMouseDown={(event) => event.stopPropagation()}>
      <div className="flex items-start justify-between border-b border-[#ecefed] px-5 py-4">
        <div><h3 id="static-workbook-dialog-title" className="text-[17px] font-semibold text-[#1d1d1f]">上传Excel文件</h3><p id="static-workbook-dialog-description" className="mt-1 text-[11px] leading-5 text-[#8b938e]">支持 Excel 工作簿及飞书表格导出的 .xlsx 文件；每个非空 Sheet 会生成一张不可变、只读的静态原始表。</p></div>
        <button type="button" onClick={onClose} disabled={uploading} className="rounded-lg p-2 text-[#8a8f8c] hover:bg-[#f2f4f3] disabled:opacity-50" aria-label="关闭上传弹窗"><X className="h-5 w-5" /></button>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
        <label className="flex min-h-[150px] cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-[#b9d2c3] bg-[#f8fcf9] px-5 text-center hover:border-[#76af8f]">
          <Upload className="h-7 w-7 text-[#31835b]" />
          <span className="mt-3 text-[13px] text-[#3d4a42]">{file ? file.name : "选择 Excel / 飞书表格导出文件"}</span>
          <span className="mt-1 text-[10px] text-[#919a94]">最大 8 MB，最多 30 个 Sheet；上传相同内容不会重复生成。</span>
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only" onChange={(event) => { setFile(event.target.files?.[0] || null); setError(""); }} />
        </label>
        <div className="rounded-lg bg-[#f7f8f7] px-3 py-2.5 text-[10px] leading-5 text-[#747d77]">静态表会进入原始表、智能分析和表关系目录；它不会覆盖 Data Crawler 文件，也不会随采集任务自动更新。</div>
        {error && <div className="rounded-lg border border-[#f3d5d0] bg-[#fff8f7] px-3 py-2 text-[11px] text-[#b8493e]">{error}</div>}
      </div>
      <div className="flex justify-end gap-2 border-t border-[#ecefed] px-5 py-3"><button type="button" onClick={onClose} disabled={uploading} className="h-9 rounded-lg border border-[#dfe3e1] bg-white px-4 text-[12px] text-[#5f6762] hover:bg-[#f7f8f7] disabled:opacity-50">取消</button><button type="button" onClick={() => void upload()} disabled={uploading || !file} className="h-9 rounded-lg bg-[#0f8f58] px-5 text-[12px] text-white hover:bg-[#0b7d4c] disabled:cursor-not-allowed disabled:opacity-50">{uploading ? "上传并生成中…" : "上传并生成"}</button></div>
    </section>
  </div>, document.body);
}

function DataTablePagination({
  page,
  totalPages,
  total,
  onChange,
  compact = false,
}: {
  page: number;
  totalPages: number;
  total: number;
  onChange: (page: number) => void;
  compact?: boolean;
}) {
  return <DataPageSelector page={page} totalPages={totalPages} shownCount={total} onChange={onChange} compact={compact} className={compact ? "" : "flex-wrap justify-between border-t border-[#f0f0f2] pt-3"} />;
}

function sortAssetNewestFirst(
  left: { id: string; updatedAt?: string },
  right: { id: string; updatedAt?: string },
) {
  const leftTime = Date.parse(left.updatedAt || "");
  const rightTime = Date.parse(right.updatedAt || "");
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime) && leftTime !== rightTime) return rightTime - leftTime;
  return right.id.localeCompare(left.id);
}



function emptyRawField(): RawField {
  return {
    fieldNameEn: "",
    fieldNameCn: "",
    type: "string",
    semanticRole: "dimension",
    isPrimaryKey: false,
    isMetric: false,
    isTime: false,
    explanation: "",
    exampleUsage: "",
  };
}

function emptyRawTableDraft(): RawTableAsset {
  return {
    id: "",
    tableNameEn: "",
    tableNameCn: "",
    source: "",
    tableType: "file",
    primaryKey: "",
    dateField: "",
    orgField: "",
    customerField: "",
    description: "",
    updateFrequency: "",
    restrictions: "",
    exampleSql: "",
    fields: normalizeFieldSemantics([emptyRawField()]),
    updatedAt: new Date().toISOString(),
  };
}

function rawTableSourcePlatform(table: RawTableAsset): "毓数" | "智能运营" {
  if (table.sourcePlatform === "毓数" || table.sourcePlatform === "智能运营") return table.sourcePlatform;
  return table.source.includes("毓数") ? "毓数" : "智能运营";
}

function emptyTopicTableDraft(): TopicTableAsset {
  return {
    id: "",
    name: "",
    code: "",
    description: "",
    sql: "",
    fields: normalizeFieldSemantics([emptyRawField()]),
    fieldExplanations: "",
    applicableScene: "",
    relatedIntent: "",
    relatedExperience: "",
    quickDisplay: false,
    reportReference: "",
    source: "智能分析页面",
    updatedAt: new Date().toISOString(),
    datasetId: "",
  };
}

type RawSourceInspection = {
  tableNameEn: string;
  tableNameCn: string;
  primaryKey: string;
  dateField: string;
  orgField: string;
  customerField: string;
  rowCount: number;
  fields: RawField[];
};

async function inspectRawSourceFile(file: File): Promise<RawSourceInspection> {
  if (!file.size || file.size > 8 * 1024 * 1024) throw new Error("文件大小必须在 8MB 以内。");
  const extension = file.name.includes(".") ? file.name.split(".").pop()?.toLowerCase() || "" : "";
  if (!["csv", "tsv", "json"].includes(extension)) throw new Error("仅支持 CSV、TSV 或 JSON 文件。");
  const text = (await file.text()).replace(/^\uFEFF/, "");
  if (!text.trim()) throw new Error("所选文件为空。");

  let rows: Array<Record<string, unknown>> = [];
  let headers: string[] = [];
  if (extension === "json") {
    const parsed = JSON.parse(text) as unknown;
    const candidateRows = Array.isArray(parsed)
      ? parsed
      : parsed && typeof parsed === "object"
        ? Object.values(parsed as Record<string, unknown>).find((value) => Array.isArray(value)) || [parsed]
        : [];
    rows = (candidateRows as unknown[]).filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row));
    headers = Array.from(new Set(rows.slice(0, 1000).flatMap((row) => Object.keys(row))));
  } else {
    const parsedRows = parseDelimitedRows(text, extension === "tsv" ? "\t" : ",");
    const sourceHeaders = parsedRows.shift() || [];
    headers = sourceHeaders.map((header, index) => String(header).trim() || `field_${index + 1}`);
    rows = parsedRows.map((values) => Object.fromEntries(headers.map((header, index) => [header, values[index] ?? ""])));
  }
  if (!headers.length) throw new Error("未识别到文件字段，请确认首行包含字段名。");

  const usedNames = new Set<string>();
  const inferredFields = headers.map((header, index) => {
    const fieldNameEn = uniqueFieldIdentifier(header, index, usedNames);
    const fieldNameCn = /^[A-Za-z_][A-Za-z0-9_.]*$/.test(header) ? "" : header;
    return {
      fieldNameEn,
      fieldNameCn,
      type: inferRawFieldType(rows.slice(0, 500).map((row) => row[header])),
      explanation: fieldNameCn || header,
      exampleUsage: "原始文件字段",
    } satisfies RawField;
  });
  const nameWithoutExtension = file.name.replace(/\.[^.]+$/, "").trim() || "raw_file";
  const fieldByHeader = (pattern: RegExp) => inferredFields[headers.findIndex((header) => pattern.test(header))]?.fieldNameEn || "";
  const inferredPrimaryKey = fieldByHeader(/(^id$|_id$|编号|主键)/i);
  const fields = normalizeFieldSemantics(inferredFields, [inferredPrimaryKey]);
  return {
    tableNameEn: normalizeTableIdentifier(nameWithoutExtension),
    tableNameCn: nameWithoutExtension,
    primaryKey: primaryKeyFields(fields)[0] || "",
    dateField: fieldByHeader(/(date|time|日期|时间)/i),
    orgField: fieldByHeader(/(org|branch|institution|机构|分行|支行)/i),
    customerField: fieldByHeader(/(customer|client|cust|客户)/i),
    rowCount: rows.length,
    fields,
  };
}

function parseDelimitedRows(text: string, delimiter: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        value += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        value += character;
      }
    } else if (character === '"' && !value) {
      quoted = true;
    } else if (character === delimiter) {
      row.push(value);
      value = "";
    } else if (character === "\n" || character === "\r") {
      row.push(value);
      if (row.some((cell) => cell.trim())) rows.push(row);
      row = [];
      value = "";
      if (character === "\r" && text[index + 1] === "\n") index += 1;
    } else {
      value += character;
    }
  }
  row.push(value);
  if (row.some((cell) => cell.trim())) rows.push(row);
  return rows;
}

function uniqueFieldIdentifier(header: string, index: number, usedNames: Set<string>) {
  const ascii = header.trim().replace(/\s+/g, "_").replace(/[^A-Za-z0-9_.]/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
  const base = /^[A-Za-z_]/.test(ascii) && /[A-Za-z0-9]/.test(ascii) ? ascii : `field_${index + 1}`;
  let candidate = base;
  let suffix = 2;
  while (usedNames.has(candidate)) {
    candidate = `${base}_${suffix}`;
    suffix += 1;
  }
  usedNames.add(candidate);
  return candidate;
}

function normalizeTableIdentifier(value: string) {
  const normalized = value.replace(/\s+/g, "_").replace(/[^A-Za-z0-9_.]/g, "_").replace(/_+/g, "_").replace(/^[_\.]+|[_\.]+$/g, "");
  return /^[A-Za-z_]/.test(normalized) && /[A-Za-z0-9]/.test(normalized) ? normalized : "raw_file";
}

function inferRawFieldType(values: unknown[]) {
  const samples = values.map((value) => String(value ?? "").trim()).filter(Boolean);
  if (!samples.length) return "string";
  if (samples.every((value) => /^(true|false)$/i.test(value))) return "boolean";
  if (samples.every((value) => /^-?(0|[1-9]\d*)$/.test(value))) return "integer";
  if (samples.every((value) => /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value))) return "decimal";
  if (samples.every((value) => /^\d{4}-\d{2}-\d{2}$/.test(value))) return "date";
  if (samples.every((value) => /^\d{4}-\d{2}-\d{2}[T\s]/.test(value))) return "datetime";
  return "string";
}

function DataTableCreateModal({
  tenantId,
  tableType,
  onClose,
  onSave,
}: {
  tenantId: string;
  tableType: DataManagementTab;
  onClose: () => void;
  onSave: (item: RawTableAsset | TopicTableAsset) => Promise<void>;
}) {
  const [rawDraft, setRawDraft] = useState<RawTableAsset>(emptyRawTableDraft);
  const [topicDraft, setTopicDraft] = useState<TopicTableAsset>(emptyTopicTableDraft);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [rawSourceFile, setRawSourceFile] = useState<File | null>(null);
  const isRaw = tableType === "raw";
  const fields = isRaw ? rawDraft.fields : normalizeTopicFields(topicDraft);
  const tableLabel = isRaw ? "原始表" : "主题表";

  const setFields = (nextFields: RawField[]) => {
    if (isRaw) {
      setRawDraft((current) => ({ ...current, fields: nextFields }));
    } else {
      setTopicDraft((current) => ({ ...current, fields: nextFields }));
    }
  };

  const updateField = (index: number, key: keyof RawField, value: string | boolean) => {
    if (["semanticRole", "type", "isPrimaryKey", "explanation", "exampleUsage"].includes(key)) {
      setFields(updateFieldSemanticValue(fields, index, key as "semanticRole" | "type" | "isPrimaryKey" | "explanation" | "exampleUsage", value));
      return;
    }
    setFields(fields.map((field, fieldIndex) => fieldIndex === index ? { ...field, [key]: value } : field));
  };

  const selectRawSourceFile = async (file: File | null) => {
    if (!file) return;
    setError("");
    try {
      const inspection = await inspectRawSourceFile(file);
      setRawSourceFile(file);
      setRawDraft((current) => ({
        ...current,
        tableNameEn: current.tableNameEn || inspection.tableNameEn,
        tableNameCn: current.tableNameCn || inspection.tableNameCn,
        source: file.name,
        tableType: "file",
        primaryKey: current.primaryKey || inspection.primaryKey,
        dateField: inspection.dateField,
        orgField: inspection.orgField,
        customerField: inspection.customerField,
        description: current.description || `由文件 ${file.name} 导入的原始数据。`,
        fields: inspection.fields,
        fileName: file.name,
        rowCount: inspection.rowCount,
      }));
    } catch (fileError) {
      setRawSourceFile(null);
      setError(apiErrorMessage(fileError, "文件读取失败"));
    }
  };

  const save = async () => {
    const validationError = validateNewDataTable(isRaw ? "raw" : "topic", isRaw ? rawDraft : topicDraft, fields);
    if (validationError) {
      setError(validationError);
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (isRaw) {
        if (!rawSourceFile) {
          setError("请选择原始表的数据源文件。");
          return;
        }
        const uploaded = await uploadRawDataFile({ tenantId, file: rawSourceFile });
        await onSave({
          ...rawDraft,
          source: rawSourceFile.name,
          fileName: rawSourceFile.name,
          objectFileName: uploaded.file.object_uri.split("/").pop() || rawSourceFile.name,
          artifactId: uploaded.file.artifact_id,
          artifactObjectUri: uploaded.file.object_uri,
          artifactContentHash: uploaded.file.content_hash,
          artifactContentType: uploaded.file.content_type,
          artifactSizeBytes: uploaded.file.size_bytes,
          fields,
          updatedAt: new Date().toISOString(),
        });
      } else {
        await onSave({
          ...topicDraft,
          source: "智能分析页面",
          quickDisplay: false,
          datasetId: undefined,
          fields,
          fieldExplanations: fields.map((field) => field.fieldNameCn || field.explanation).filter(Boolean).join("、"),
          updatedAt: new Date().toISOString(),
        });
      }
    } catch (saveError) {
      setError(`保存失败：${apiErrorMessage(saveError, "未知错误")}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4 py-6">
      <div role="dialog" aria-modal="true" aria-label={`新增${tableLabel}`} className="flex max-h-[calc(100vh-48px)] w-full max-w-[960px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">新增{tableLabel}</h3>
            <p className="mt-0.5 text-[11px] text-[#aeaeb2]">按照{tableLabel}资产要求填写基础信息和字段语义，带 * 的项目为必填。</p>
          </div>
          <button type="button" aria-label={`关闭新增${tableLabel}弹窗`} onClick={onClose} className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-[#8a8a8e] hover:bg-[#f2f2f7]">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          {isRaw ? (
            <div className="grid gap-4 md:grid-cols-2">
              <DataTableFormField label="表英文名" required value={rawDraft.tableNameEn} placeholder="loan_operation_fact" onChange={(value) => setRawDraft((current) => ({ ...current, tableNameEn: value }))} />
              <DataTableFormField label="表中文名" required value={rawDraft.tableNameCn} placeholder="信贷经营明细表" onChange={(value) => setRawDraft((current) => ({ ...current, tableNameCn: value }))} />
              <label>
                <span className="mb-1.5 block text-[12px] text-[#636366]">数据来源<span className="ml-0.5 text-[#d93025]">*</span></span>
                <input
                  type="file"
                  aria-label="选择原始表数据源文件"
                  accept=".csv,.tsv,.json,text/csv,text/tab-separated-values,application/json"
                  className="sr-only"
                  onChange={(event) => void selectRawSourceFile(event.target.files?.[0] || null)}
                />
                <span className="flex h-9 cursor-pointer items-center justify-between gap-3 rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-3 text-[12px] text-[#3a3a3c] hover:border-[#c7c7cc]">
                  <span className={`min-w-0 truncate ${rawSourceFile ? "" : "text-[#aeaeb2]"}`}>{rawSourceFile?.name || "选择 CSV、TSV 或 JSON 文件"}</span>
                  <FilePlus2 className="h-3.5 w-3.5 shrink-0 text-[#8a8a8e]" />
                </span>
                {rawSourceFile && <span className="mt-1 block text-[10px] text-[#8a8a8e]">已识别 {rawDraft.fields.length} 个字段、{rawDraft.rowCount || 0} 行数据</span>}
              </label>
              <DataTableFormField label="主键" value={rawDraft.primaryKey} placeholder="loan_id" onChange={(value) => setRawDraft((current) => ({ ...current, primaryKey: value }))} />
              <DataTableFormField className="md:col-span-2" label="表说明" required multiline value={rawDraft.description} placeholder="说明该原始表包含的数据范围和业务用途" onChange={(value) => setRawDraft((current) => ({ ...current, description: value }))} />
              <DataTableFormField className="md:col-span-2" label="示例 SQL" multiline value={rawDraft.exampleSql} placeholder="select ... where tenant_id = :tenant_id" onChange={(value) => setRawDraft((current) => ({ ...current, exampleSql: value }))} />
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              <DataTableFormField label="主题表名称" required value={topicDraft.name} placeholder="分行放款排名分析" onChange={(value) => setTopicDraft((current) => ({ ...current, name: value }))} />
              <DataTableFormField label="主题表编码" required value={topicDraft.code} placeholder="weekly_branch_loan_rank" onChange={(value) => setTopicDraft((current) => ({ ...current, code: value }))} />
              <DataTableFormField className="md:col-span-2" label="数据来源" value="智能分析页面" readOnly onChange={() => undefined} />
              <DataTableFormField className="md:col-span-2" label="主题说明" required multiline value={topicDraft.description} placeholder="说明主题表解决的业务问题和分析范围" onChange={(value) => setTopicDraft((current) => ({ ...current, description: value }))} />
              <DataTableFormField label="适用场景" value={topicDraft.applicableScene} placeholder="经营周报、智能分析" onChange={(value) => setTopicDraft((current) => ({ ...current, applicableScene: value }))} />
              <DataTableFormField label="关联意图" value={topicDraft.relatedIntent} placeholder="经营分析 / 机构排名" onChange={(value) => setTopicDraft((current) => ({ ...current, relatedIntent: value }))} />
              <DataTableFormField label="关联经验" value={topicDraft.relatedExperience} placeholder="分析经验编码" onChange={(value) => setTopicDraft((current) => ({ ...current, relatedExperience: value }))} />
              <DataTableFormField label="周报引用" value={topicDraft.reportReference} placeholder="经营周报-业绩与业务波动" onChange={(value) => setTopicDraft((current) => ({ ...current, reportReference: value }))} />
              <DataTableFormField className="md:col-span-2" label="主题 SQL" required multiline value={topicDraft.sql} placeholder="select ... from ... where tenant_id = :tenant_id" onChange={(value) => setTopicDraft((current) => ({ ...current, sql: value }))} />
            </div>
          )}

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <div>
                <h4 className="text-[13px] text-[#1d1d1f]">字段定义 *</h4>
                <p className="mt-0.5 text-[10px] text-[#aeaeb2]">至少添加一个字段；字段英文名必须唯一并使用字母、数字、下划线或点号。</p>
              </div>
              <button type="button" onClick={() => setFields([...fields, emptyRawField()])} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[11px] text-[#636366] hover:bg-[#f2f2f7]">
                <Plus className="h-3.5 w-3.5" />添加字段
              </button>
            </div>
            <div className="overflow-x-auto rounded-lg border border-[#f0f0f2]">
              <div className="min-w-[1120px]">
                <div className="grid grid-cols-[1fr_1fr_0.72fr_0.8fr_0.66fr_1.25fr_1.15fr_36px] gap-2 bg-[#fafbfc] px-3 py-2 text-[10px] text-[#8a8a8e]">
                  <span>字段英文 *</span><span>字段中文</span><span>字段角色</span><span>类型 *</span><span>是否主键</span><span>语义解释</span><span>示例用法</span><span />
                </div>
                {fields.map((field, index) => (
                  <div key={index} className="grid grid-cols-[1fr_1fr_0.72fr_0.8fr_0.66fr_1.25fr_1.15fr_36px] gap-2 border-t border-[#f8f8f8] p-3">
                    <input aria-label={`字段${index + 1}英文名`} value={field.fieldNameEn} onChange={(event) => updateField(index, "fieldNameEn", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <input aria-label={`字段${index + 1}中文名`} value={field.fieldNameCn} onChange={(event) => updateField(index, "fieldNameCn", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <select aria-label={`字段${index + 1}字段角色`} value={field.semanticRole} onChange={(event) => updateField(index, "semanticRole", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]"><option value="metric">指标</option><option value="dimension">维度</option><option value="date">日期</option></select>
                    <select aria-label={`字段${index + 1}类型`} value={field.semanticRole === "date" ? dateFieldFormat : field.type} disabled={field.semanticRole !== "metric"} onChange={(event) => updateField(index, "type", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc] disabled:bg-[#fafbfc]">{field.semanticRole === "metric" ? metricFieldTypes.map((type) => <option key={type} value={type}>{type}</option>) : <option value={field.semanticRole === "date" ? dateFieldFormat : "string"}>{field.semanticRole === "date" ? dateFieldFormat : "string"}</option>}</select>
                    <select aria-label={`字段${index + 1}是否主键`} value={field.isPrimaryKey ? "yes" : "no"} onChange={(event) => updateField(index, "isPrimaryKey", event.target.value === "yes")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]"><option value="no">否</option><option value="yes">是</option></select>
                    <input aria-label={`字段${index + 1}语义解释`} value={field.explanation} onChange={(event) => updateField(index, "explanation", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <input aria-label={`字段${index + 1}示例用法`} value={field.exampleUsage || ""} onChange={(event) => updateField(index, "exampleUsage", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <button type="button" aria-label={`删除字段${index + 1}`} onClick={() => setFields(fields.filter((_, fieldIndex) => fieldIndex !== index))} className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-[#f0f0f2] px-5 py-4">
          <span className="min-w-0 text-[11px] text-[#d93025]">{error}</span>
          <div className="flex shrink-0 items-center gap-2">
            <button type="button" onClick={onClose} disabled={saving} className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50">取消</button>
            <button type="button" onClick={() => void save()} disabled={saving} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-50">
              <Save className="h-3.5 w-3.5" />{saving ? "保存中..." : `保存${tableLabel}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function DataTableFormField({
  label,
  value,
  onChange,
  placeholder,
  required = false,
  multiline = false,
  readOnly = false,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  required?: boolean;
  multiline?: boolean;
  readOnly?: boolean;
  className?: string;
}) {
  const controlClass = "w-full rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-3 text-[12px] text-[#3a3a3c] outline-none placeholder:text-[#c7c7cc] focus:border-[#c7c7cc]";
  return (
    <label className={className}>
      <span className="mb-1.5 block text-[12px] text-[#636366]">{label}{required && <span className="ml-0.5 text-[#d93025]">*</span>}</span>
      {multiline ? (
        <textarea aria-label={label} value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className={`${controlClass} min-h-[78px] py-2 leading-[1.6] ${readOnly ? "cursor-default text-[#8a8a8e]" : ""}`} />
      ) : (
        <input aria-label={label} value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} className={`${controlClass} h-9 ${readOnly ? "cursor-default text-[#8a8a8e]" : ""}`} />
      )}
    </label>
  );
}

function validateNewDataTable(
  tableType: DataManagementTab,
  item: RawTableAsset | TopicTableAsset,
  fields: RawField[],
) {
  const identifier = /^[A-Za-z_][A-Za-z0-9_.]{0,199}$/;
  if (tableType === "raw") {
    const raw = item as RawTableAsset;
    if (!raw.tableNameEn.trim() || !raw.tableNameCn.trim() || !raw.source.trim() || !raw.description.trim()) return "请填写表英文名、表中文名、数据来源和表说明。";
    if (!identifier.test(raw.tableNameEn.trim())) return "表英文名格式不正确，请使用字母开头，并仅包含字母、数字、下划线或点号。";
  } else {
    const topic = item as TopicTableAsset;
    if (!topic.name.trim() || !topic.code.trim() || !topic.description.trim() || !topic.sql.trim()) return "请填写主题表名称、主题表编码、主题说明和主题 SQL。";
    if (!identifier.test(topic.code.trim())) return "主题表编码格式不正确，请使用字母开头，并仅包含字母、数字、下划线或点号。";
    if (!/^(select|with)\b/i.test(topic.sql.trim())) return "主题 SQL 只能使用 SELECT 或 WITH 查询。";
    if (!/(?::tenant_id\b|\btenant_id\s*=\s*\?)/i.test(topic.sql)) return "主题 SQL 必须包含 :tenant_id 机构隔离条件。";
  }
  if (!fields.length) return "请至少添加一个字段。";
  if (fields.some((field) => !identifier.test(field.fieldNameEn.trim()) || !field.type.trim())) return "请完整填写字段英文名和字段类型，并检查英文名格式。";
  const fieldNames = fields.map((field) => field.fieldNameEn.trim());
  if (new Set(fieldNames).size !== fieldNames.length) return "字段英文名不能重复。";
  return "";
}

function DataTableDeleteConfirm({
  itemType,
  item,
  deleting,
  onCancel,
  onConfirm,
}: {
  itemType: "raw_table" | "topic_table";
  item: RawTableAsset | TopicTableAsset;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const topic = itemType === "topic_table" ? item as TopicTableAsset : null;
  const protectedAsset = Boolean(topic?.systemManaged || topic?.deletable === false);
  const itemName = itemType === "raw_table" ? (item as RawTableAsset).tableNameCn : (item as TopicTableAsset).name;
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/20 px-4">
      <div role="dialog" aria-modal="true" aria-label={`删除${itemName}`} className="w-full max-w-[420px] rounded-xl border border-[#e5e5ea] bg-white p-5 shadow-2xl shadow-black/20">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fff0f0] text-[#d93025]"><Trash2 className="h-4 w-4" /></div>
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">你正在删除这条记录</h3>
            <p className="mt-1.5 text-[12px] leading-[1.7] text-[#636366]">{itemName}</p>
            <p className="mt-1 text-[11px] leading-[1.6] text-[#aeaeb2]">
              {protectedAsset ? "该主题表是系统内置资产，关联经营周报和智能分析，不能删除。" : "确认后将从站内数据列表和后端资产配置中删除，操作不可撤销。"}
            </p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={deleting} className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50">取消</button>
          <button type="button" onClick={onConfirm} disabled={deleting || protectedAsset} className="h-9 rounded-lg bg-[#d93025] px-4 text-[12px] text-white hover:bg-[#c5221f] disabled:cursor-not-allowed disabled:opacity-40">{deleting ? "删除中..." : "确认删除"}</button>
        </div>
      </div>
    </div>
  );
}

type MemoryItemType = "intent" | "knowledge_file" | "analysis_experience" | "user_behavior_habit";
type ManagedMemoryAsset = IntentAsset | KnowledgeFileAsset | AnalysisExperienceAsset | BehaviorHabitAsset;
type MemoryEditorMode = "view" | "edit" | "create";
type MemoryEditorState = {
  mode: MemoryEditorMode;
  itemType: MemoryItemType;
  draft: Record<string, unknown>;
  allowTypeChange: boolean;
};

function KnowledgeMemory({
  searchTerm,
  tenantId,
  userId,
  canManage,
}: {
  searchTerm: string;
  tenantId: string;
  userId: string;
  canManage: boolean;
}) {
  const [activeTab, setActiveTab] = useState<KnowledgeMemoryTab>("all");
  const [memorySort, setMemorySort] = useState<"time" | "weight">("time");
  const [memoryStatus, setMemoryStatus] = useState<"all" | "当前有效" | "历史归档">("all");
  const [editor, setEditor] = useState<MemoryEditorState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ itemType: MemoryItemType; item: ManagedMemoryAsset } | null>(null);
  const [operationNotice, setOperationNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const { bundle, notice, reload } = useDataAssetBundle(tenantId, userId, "knowledge");
  const keyword = searchTerm.trim().toLowerCase();

  const matchesMemory = (item: object) =>
    assetMatches(item, keyword) && (memoryStatus === "all" || knowledgeMemoryStatus(item) === memoryStatus);
  const intents = sortMemoryItems(bundle.intents.filter(matchesMemory), memorySort);
  const files = sortMemoryItems(bundle.knowledge_files.filter(matchesMemory), memorySort);
  const experiences = sortMemoryItems(bundle.analysis_experiences.filter(matchesMemory), memorySort);
  const allKnowledgeCount = intents.length + files.length + experiences.length;

  const openCreate = (itemType?: MemoryItemType) => {
    const resolvedType = itemType || memoryItemTypeForTab(activeTab);
    setOperationNotice("");
    setEditor({
      mode: "create",
      itemType: resolvedType,
      draft: emptyMemoryDraft(resolvedType),
      allowTypeChange: activeTab === "all" && !itemType,
    });
  };

  const openItem = (mode: "view" | "edit", itemType: MemoryItemType, item: ManagedMemoryAsset) => {
    setOperationNotice("");
    setEditor({ mode, itemType, draft: { ...item }, allowTypeChange: false });
  };

  const saveMemory = async () => {
    if (!editor || editor.mode === "view") return;
    const validation = validateMemoryDraft(editor.itemType, editor.draft, editor.mode);
    if (validation) {
      setOperationNotice(validation);
      return;
    }
    const item = normalizeMemoryDraft(editor.itemType, editor.draft);
    setBusy(true);
    setOperationNotice("正在保存记忆版本…");
    try {
      await saveDataAssetItem({ tenantId, userId, itemType: editor.itemType, item });
      setOperationNotice(editor.mode === "create" ? "记忆已新增并提交复核。" : "记忆修改已提交复核。");
      setEditor(null);
      reload();
    } catch (error) {
      setOperationNotice(apiErrorMessage(error, "记忆保存失败，请稍后重试。"));
    } finally {
      setBusy(false);
    }
  };

  const deleteMemory = async () => {
    if (!pendingDelete) return;
    setBusy(true);
    setOperationNotice("正在删除记忆…");
    try {
      await deleteDataAssetItem({
        tenantId,
        userId,
        itemType: pendingDelete.itemType,
        itemId: pendingDelete.item.id,
      });
      setOperationNotice("记忆已删除并同步到后端。");
      setPendingDelete(null);
      reload();
    } catch (error) {
      setOperationNotice(apiErrorMessage(error, "记忆删除失败，请稍后重试。"));
    } finally {
      setBusy(false);
    }
  };

  const itemActions = (itemType: MemoryItemType) => ({
    canManage,
    onView: (item: ManagedMemoryAsset) => openItem("view", itemType, item),
    onEdit: (item: ManagedMemoryAsset) => openItem("edit", itemType, item),
    onDelete: (item: ManagedMemoryAsset) => setPendingDelete({ itemType, item }),
  });

  const toolbarItemType = memoryItemTypeForTab(activeTab);
  const toolbarAddLabel = activeTab === "all" ? "新增记忆" : `新增${memoryItemTypeLabel(toolbarItemType)}`;

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">知识记忆</h3>
            <p className="mt-1 text-[11px] text-[#aeaeb2]">知识文件仅用于提炼意图、分析经验和行为习惯；Skill 与分析运行只召回提炼后的记忆。</p>
          </div>
          <SegmentedTabs
            tabs={[
              { key: "all", label: `全部 ${allKnowledgeCount}` },
              { key: "intent", label: `意图管理 ${intents.length}` },
              { key: "files", label: `知识文件 ${files.length}` },
              { key: "experience", label: `分析经验 ${experiences.length}` },
            ]}
            activeKey={activeTab}
            onChange={(key) => setActiveTab(key as KnowledgeMemoryTab)}
          />
        </div>
        <MemoryToolbar
          sort={memorySort}
          status={memoryStatus}
          onSortChange={setMemorySort}
          onStatusChange={setMemoryStatus}
          action={canManage ? { label: toolbarAddLabel, onClick: () => openCreate() } : undefined}
        />

        {operationNotice && (
          <div role={/失败|请|冲突|无权限/.test(operationNotice) ? "alert" : "status"} className={`mt-3 text-[11px] ${/失败|请|冲突|无权限/.test(operationNotice) ? "text-[#d93025]" : "text-[#258a3f]"}`}>
            {operationNotice}
          </div>
        )}

        {notice === "资产配置同步中..." && <div className="mt-4 rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-4 py-5 text-[12px] text-[#8a8a8e]">正在加载知识记忆…</div>}

        {notice !== "资产配置同步中..." && activeTab === "all" && (
          <div className="mt-4 space-y-5" data-knowledge-memory-all>
            {!allKnowledgeCount && <EmptyAssetState text="暂无匹配的知识类记忆" />}
            {intents.length > 0 && (
              <KnowledgeMemoryGroup title="意图管理" count={intents.length}>
                <MemoryList itemType="intent" items={intents} {...itemActions("intent")} />
              </KnowledgeMemoryGroup>
            )}
            {files.length > 0 && (
              <KnowledgeMemoryGroup title="知识文件" count={files.length}>
                <MemoryList itemType="knowledge_file" items={files} {...itemActions("knowledge_file")} />
              </KnowledgeMemoryGroup>
            )}
            {experiences.length > 0 && (
              <KnowledgeMemoryGroup title="分析经验" count={experiences.length}>
                <MemoryList itemType="analysis_experience" items={experiences} {...itemActions("analysis_experience")} />
              </KnowledgeMemoryGroup>
            )}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "intent" && (
          <div className="mt-4">
            {intents.length > 0 && <MemoryList itemType="intent" items={intents} {...itemActions("intent")} />}
            {!intents.length && <EmptyAssetState text="暂无匹配的意图配置" />}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "files" && (
          <div className="mt-4">
            {files.length > 0 && <MemoryList itemType="knowledge_file" items={files} {...itemActions("knowledge_file")} />}
            {!files.length && <EmptyAssetState text="暂无匹配的知识文件" />}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "experience" && (
          <div className="mt-4">
            {experiences.length > 0 && <MemoryList itemType="analysis_experience" items={experiences} {...itemActions("analysis_experience")} />}
            {!experiences.length && <EmptyAssetState text="暂无匹配的分析经验" />}
          </div>
        )}
      </div>
      <BehaviorHabits
        searchTerm={searchTerm}
        bundle={bundle}
        loading={notice === "资产配置同步中..."}
        canManage={canManage}
        onCreate={() => openCreate("user_behavior_habit")}
        onView={(item) => openItem("view", "user_behavior_habit", item)}
        onEdit={(item) => openItem("edit", "user_behavior_habit", item)}
        onDelete={(item) => setPendingDelete({ itemType: "user_behavior_habit", item })}
      />
      {editor && (
        <MemoryItemEditor
          state={editor}
          busy={busy}
          notice={operationNotice}
          canManage={canManage}
          onChange={setEditor}
          onClose={() => setEditor(null)}
          onSave={() => void saveMemory()}
        />
      )}
      {pendingDelete && (
        <MemoryDeleteConfirm
          itemType={pendingDelete.itemType}
          item={pendingDelete.item}
          deleting={busy}
          onCancel={() => setPendingDelete(null)}
          onConfirm={() => void deleteMemory()}
        />
      )}
    </div>
  );
}

function KnowledgeMemoryGroup({ title, count, children }: { title: string; count: number; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-[13px] text-[#1d1d1f]">{title}</h4>
        <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-[#8a8a8e]">{count} 条</span>
      </div>
      {children}
    </section>
  );
}

function BehaviorHabits({
  searchTerm,
  bundle,
  loading,
  canManage,
  onCreate,
  onView,
  onEdit,
  onDelete,
}: {
  searchTerm: string;
  bundle: DataAssetBundle;
  loading: boolean;
  canManage: boolean;
  onCreate: () => void;
  onView: (item: BehaviorHabitAsset) => void;
  onEdit: (item: BehaviorHabitAsset) => void;
  onDelete: (item: BehaviorHabitAsset) => void;
}) {
  const [activeType, setActiveType] = useState<"all" | "分析习惯" | "运营习惯" | "汇报习惯">("all");
  const [sort, setSort] = useState<"time" | "weight">("time");
  const [status, setStatus] = useState<"all" | "当前有效" | "历史归档">("all");
  const keyword = searchTerm.trim().toLowerCase();

  const shownHabits = sortMemoryItems(
    (bundle.behavior_habits || [])
      .filter((habit) => assetMatches(habit, keyword))
      .filter((habit) => activeType === "all" || habit.habitType === activeType)
      .filter((habit) => status === "all" || (habit.status || "当前有效") === status),
    sort,
  );

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">用户行为习惯</h3>
            <p className="mt-1 text-[11px] text-[#aeaeb2]">从经营周报历史版本中沉淀用户分析、运营和汇报偏好，按时间衰减与权重持续更新。</p>
          </div>
          <SegmentedTabs
            tabs={[
              { key: "all", label: `全部 ${shownHabits.length}` },
              { key: "分析习惯", label: "分析习惯" },
              { key: "运营习惯", label: "运营习惯" },
              { key: "汇报习惯", label: "汇报习惯" },
            ]}
            activeKey={activeType}
            onChange={(key) => setActiveType(key as typeof activeType)}
          />
        </div>
        <MemoryToolbar
          sort={sort}
          status={status}
          onSortChange={setSort}
          onStatusChange={setStatus}
          action={canManage ? { label: "新增行为习惯", onClick: onCreate } : undefined}
        />
        <div className="mt-3">
          {loading && <div className="rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-4 py-5 text-[12px] text-[#8a8a8e]">正在加载行为习惯…</div>}
          {!loading && shownHabits.length > 0 && (
            <MemoryList
              itemType="user_behavior_habit"
              items={shownHabits}
              canManage={canManage}
              onView={onView}
              onEdit={onEdit}
              onDelete={onDelete}
            />
          )}
          {!shownHabits.length && <EmptyAssetState text="暂无匹配的用户行为习惯，保存经营周报版本后会自动生成。" />}
        </div>
      </div>
    </div>
  );
}

function formatLocalDateTime(value: Date): string {
  const part = (number: number) => String(number).padStart(2, "0");
  return `${value.getFullYear()}-${part(value.getMonth() + 1)}-${part(value.getDate())}T${part(value.getHours())}:${part(value.getMinutes())}`;
}

function legacyScheduleBinding(rule: string, parameterType: string): string {
  if (!rule) return "";
  if (rule === "reference" || rule.startsWith("before:")) return rule;
  if (rule === "previous_date" || rule === "previous_month") return "before:1";
  if (
    (parameterType === "month" && ["execution_month", "year_start_month"].includes(rule))
    || (parameterType === "datetime" && ["execution_datetime", "day_start", "day_end"].includes(rule))
    || (parameterType === "date" && ["execution_date", "month_start", "month_end", "previous_month_start", "previous_month_end"].includes(rule))
  ) return "reference";
  return "reference";
}

function defaultDataCrawlerDraft(state: DataCrawlerScheduleState): DataCrawlerScheduleDraft {
  const taskConfig = state.task?.task_config || {};
  const binding = state.binding;
  const expression = String(state.task?.schedule_expression || "").split(" ");
  const minute = Number(expression[0] || 0);
  const hour = Number(expression[1] || 9);
  const recurrence = (taskConfig.recurrence as DataCrawlerScheduleDraft["recurrence"]) || (binding?.defaultLoopEnabled ? "daily" : "none");
  const bindings = Object.fromEntries(Object.entries(taskConfig.parameter_bindings || {}).map(([name, rule]) => {
    const parameterType = binding?.parameters.find((item) => item.name === name)?.type || "date";
    return [name, legacyScheduleBinding(String(rule || ""), parameterType)];
  }));
  if (!state.task) {
    for (const parameter of binding?.parameters || []) {
      if (["date", "month", "datetime"].includes(parameter.type)) bindings[parameter.name] = "reference";
    }
  }
  const execution = new Date();
  execution.setSeconds(0, 0);
  execution.setHours(hour, minute, 0, 0);
  if (taskConfig.execution_at) {
    const stored = new Date(taskConfig.execution_at);
    if (!Number.isNaN(stored.getTime())) {
      execution.setFullYear(stored.getFullYear(), stored.getMonth(), stored.getDate());
      execution.setHours(stored.getHours(), stored.getMinutes(), 0, 0);
    }
  } else if (recurrence === "weekly" || recurrence === "biweekly") {
    const targetWeekday = Number(expression[4] || 1);
    execution.setDate(execution.getDate() + ((targetWeekday - execution.getDay() + 7) % 7));
  } else if (recurrence === "monthly") {
    const targetDay = Math.max(1, Math.min(28, Number(expression[2] || 1)));
    execution.setDate(targetDay);
  }
  return {
    sqlId: binding?.sqlId || state.available_bindings[0]?.sqlId || "",
    recurrence,
    executionAt: formatLocalDateTime(execution),
    parameters: { ...(taskConfig.parameters || {}) },
    parameterBindings: bindings,
  };
}

function scheduleParameterMode(rule: string): "fixed" | "reference" | "before" {
  if (rule === "reference") return "reference";
  if (rule.startsWith("before:")) return "before";
  return "fixed";
}

function scheduleParameterOffset(rule: string): string {
  return rule.startsWith("before:") ? rule.slice("before:".length) : "";
}

function temporalParameterLabel(name: string, type: string): string {
  const normalized = name.toLowerCase();
  const suffix = type === "month" ? "月份" : type === "datetime" ? "时间" : "日期";
  if (normalized.startsWith("start_") || normalized.endsWith("_start") || normalized === "start") return `开始${suffix}`;
  if (normalized.startsWith("end_") || normalized.endsWith("_end") || normalized === "end") return `结束${suffix}`;
  return type === "month" ? "取值月份" : type === "datetime" ? "取值时间" : "取值日期";
}

function temporalReferencePreview(executionAt: string, parameterType: string, offset = 0): string {
  const value = new Date(executionAt);
  if (Number.isNaN(value.getTime())) return "请先选择执行日期与时间";
  if (parameterType === "month" && offset) value.setFullYear(value.getFullYear(), value.getMonth() - offset, 1);
  else if (offset) value.setDate(value.getDate() - offset);
  const part = (number: number) => String(number).padStart(2, "0");
  if (parameterType === "month") return `${value.getFullYear()}-${part(value.getMonth() + 1)}`;
  const date = `${value.getFullYear()}-${part(value.getMonth() + 1)}-${part(value.getDate())}`;
  return parameterType === "datetime" ? `${date} ${part(value.getHours())}:${part(value.getMinutes())}` : date;
}

const scheduleControlClass = "h-9 w-full rounded-lg border border-[#dfe4e1] bg-white px-3 text-[12px] font-normal text-[#303633] shadow-none outline-none transition-colors hover:border-[#cbd4cf] focus-visible:border-[#8fb9a2] focus-visible:ring-2 focus-visible:ring-[#dceee4] disabled:cursor-not-allowed disabled:bg-[#f7f8f7] disabled:text-[#9aa19d]";
const scheduleMenuClass = "z-[80] rounded-lg border-[#e1e6e3] bg-white p-1 text-[12px] text-[#303633] shadow-[0_12px_32px_rgba(45,63,54,0.12)]";

function ScheduleSelect({
  label,
  value,
  onValueChange,
  options,
  disabled = false,
}: {
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
  disabled?: boolean;
}) {
  return (
    <Select value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectTrigger aria-label={label} className={`${scheduleControlClass} [&>svg]:h-3.5 [&>svg]:w-3.5 [&>svg]:text-[#7d8781]`}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent align="start" className={scheduleMenuClass}>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value} disabled={option.disabled} className="h-8 rounded-md px-2 pr-8 text-[12px] focus:bg-[#f0f6f2] focus:text-[#1f5f43]">
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function parseLocalScheduleValue(value: string): Date | null {
  const [datePart, timePart = "00:00"] = String(value || "").split("T");
  const [year, month, day] = datePart.split("-").map(Number);
  const [hour, minute] = timePart.split(":").map(Number);
  if (![year, month, day, hour, minute].every(Number.isFinite)) return null;
  const result = new Date(year, month - 1, day, hour, minute, 0, 0);
  return Number.isNaN(result.getTime()) ? null : result;
}

function formatLocalDate(value: Date): string {
  const part = (number: number) => String(number).padStart(2, "0");
  return `${value.getFullYear()}-${part(value.getMonth() + 1)}-${part(value.getDate())}`;
}

function ScheduleDateControl({
  label,
  value,
  onChange,
  includeTime = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  includeTime?: boolean;
}) {
  const selected = parseLocalScheduleValue(includeTime ? value : `${value}T00:00`);
  const display = selected
    ? includeTime
      ? `${formatLocalDate(selected).replaceAll("-", "/")} ${String(selected.getHours()).padStart(2, "0")}:${String(selected.getMinutes()).padStart(2, "0")}`
      : formatLocalDate(selected).replaceAll("-", "/")
    : "请选择日期";
  const setDate = (date: Date | undefined) => {
    if (!date) return;
    const next = selected || new Date();
    next.setFullYear(date.getFullYear(), date.getMonth(), date.getDate());
    next.setSeconds(0, 0);
    onChange(includeTime ? formatLocalDateTime(next) : formatLocalDate(next));
  };
  const setTime = (part: "hour" | "minute", nextValue: string) => {
    const next = selected || new Date();
    if (part === "hour") next.setHours(Number(nextValue));
    else next.setMinutes(Number(nextValue));
    next.setSeconds(0, 0);
    onChange(formatLocalDateTime(next));
  };
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" aria-label={label} className={`${scheduleControlClass} flex items-center justify-between gap-3 text-left`}>
          <span className={selected ? "truncate" : "truncate text-[#9aa19d]"}>{display}</span>
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-[#7d8781]" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="z-[80] w-auto overflow-hidden rounded-xl border-[#e1e6e3] bg-white p-0 shadow-[0_14px_38px_rgba(45,63,54,0.14)]">
        <Calendar
          mode="single"
          locale={zhCN}
          selected={selected || undefined}
          onSelect={setDate}
          className="p-2.5 text-[12px]"
          classNames={{
            month: "flex flex-col gap-2",
            caption: "relative flex w-full items-center justify-center pt-0",
            caption_label: "text-[12px] font-medium text-[#303633]",
            head_cell: "w-7 rounded-md text-[10px] font-normal text-[#929a96]",
            row: "mt-1 flex w-full",
            day: "size-7 rounded-md p-0 text-[11px] font-normal text-[#3f4743] hover:bg-[#f0f6f2]",
            day_selected: "bg-[#0f8f58] text-white hover:bg-[#0f8f58] hover:text-white focus:bg-[#0f8f58] focus:text-white",
            day_today: "bg-[#eef5f1] text-[#176944]",
            day_outside: "text-[#c0c5c2]",
          }}
        />
        {includeTime && (
          <div className="flex items-center gap-2 border-t border-[#edf0ee] px-3 py-2.5">
            <Clock3 className="h-3.5 w-3.5 text-[#7d8781]" />
            <span className="mr-auto text-[11px] text-[#69726d]">执行时间</span>
            <Select value={String(selected?.getHours() ?? 9).padStart(2, "0")} onValueChange={(next) => setTime("hour", next)}>
              <SelectTrigger aria-label={`${label}小时`} className="h-8 w-[72px] rounded-md border-[#dfe4e1] bg-white px-2 text-[11px] shadow-none focus:ring-2 focus:ring-[#dceee4]"><SelectValue /></SelectTrigger>
              <SelectContent className={`${scheduleMenuClass} max-h-56 min-w-[72px]`}>{Array.from({ length: 24 }, (_, index) => String(index).padStart(2, "0")).map((hour) => <SelectItem key={hour} value={hour} className="h-7 text-[11px] focus:bg-[#f0f6f2]">{hour}</SelectItem>)}</SelectContent>
            </Select>
            <span className="text-[11px] text-[#8b938f]">:</span>
            <Select value={String(selected?.getMinutes() ?? 0).padStart(2, "0")} onValueChange={(next) => setTime("minute", next)}>
              <SelectTrigger aria-label={`${label}分钟`} className="h-8 w-[72px] rounded-md border-[#dfe4e1] bg-white px-2 text-[11px] shadow-none focus:ring-2 focus:ring-[#dceee4]"><SelectValue /></SelectTrigger>
              <SelectContent className={`${scheduleMenuClass} max-h-56 min-w-[72px]`}>{Array.from({ length: 60 }, (_, index) => String(index).padStart(2, "0")).map((minute) => <SelectItem key={minute} value={minute} className="h-7 text-[11px] focus:bg-[#f0f6f2]">{minute}</SelectItem>)}</SelectContent>
            </Select>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

function ScheduleMonthControl({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  const [year, setYear] = useState(() => Number(String(value || "").split("-")[0]) || new Date().getFullYear());
  const selectedMonth = Number(String(value || "").split("-")[1]) || 0;
  const months = ["一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"];
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button type="button" aria-label={label} className={`${scheduleControlClass} flex items-center justify-between gap-3 text-left`}>
          <span className={value ? "truncate" : "truncate text-[#9aa19d]"}>{value ? value.replace("-", " / ") : "请选择月份"}</span>
          <CalendarDays className="h-3.5 w-3.5 shrink-0 text-[#7d8781]" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" sideOffset={6} className="z-[80] w-[280px] rounded-xl border-[#e1e6e3] bg-white p-3 shadow-[0_14px_38px_rgba(45,63,54,0.14)]">
        <div className="mb-3 flex items-center justify-between">
          <button type="button" aria-label="上一年" onClick={() => setYear((current) => current - 1)} className="grid h-7 w-7 place-items-center rounded-md text-[#7d8781] hover:bg-[#f0f4f2]"><ChevronLeft className="h-3.5 w-3.5" /></button>
          <span className="text-[12px] font-medium text-[#303633]">{year} 年</span>
          <button type="button" aria-label="下一年" onClick={() => setYear((current) => current + 1)} className="grid h-7 w-7 place-items-center rounded-md text-[#7d8781] hover:bg-[#f0f4f2]"><ChevronRight className="h-3.5 w-3.5" /></button>
        </div>
        <div className="grid grid-cols-3 gap-1.5">{months.map((month, index) => {
          const active = year === Number(String(value || "").split("-")[0]) && selectedMonth === index + 1;
          return <button key={month} type="button" onClick={() => onChange(`${year}-${String(index + 1).padStart(2, "0")}`)} className={`h-8 rounded-md text-[11px] transition-colors ${active ? "bg-[#0f8f58] text-white" : "text-[#4b544f] hover:bg-[#f0f6f2] hover:text-[#176944]"}`}>{month}</button>;
        })}</div>
      </PopoverContent>
    </Popover>
  );
}

function dataCrawlerScheduleListStatus(
  task: DataCrawlerScheduleState["task"],
  draft: DataCrawlerScheduleDraft,
): DataCrawlerScheduleListStatus | null {
  if (!task || task.status !== "active" || draft.recurrence === "none") return null;
  return {
    scheduled: true,
    recurrence: draft.recurrence,
    schedule_expression: String(task.schedule_expression || ""),
    next_run_at: String(task.next_run_at || ""),
  };
}

function DataCrawlerSchedulePanel({
  table,
  tenantId,
  userId,
  onScheduleStatusChange,
}: {
  table: RawTableAsset;
  tenantId: string;
  userId: string;
  onScheduleStatusChange: (sourceKey: string, status: DataCrawlerScheduleListStatus | null) => void;
}) {
  const [state, setState] = useState<DataCrawlerScheduleState | null>(null);
  const [draft, setDraft] = useState<DataCrawlerScheduleDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [testing, setTesting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState("");
  const [configurationUnavailable, setConfigurationUnavailable] = useState(false);
  const [selectedSqlId, setSelectedSqlId] = useState("");

  const reload = async () => {
    if (!table.sourceKey) return null;
    setLoading(true);
    try {
      const response = await fetchDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey });
      const nextDraft = defaultDataCrawlerDraft(response);
      setState(response);
      setDraft(nextDraft);
      setSelectedSqlId(nextDraft.sqlId);
      setConfigurationUnavailable(false);
      if (!refreshing) setNotice("");
      return response;
    } catch {
      setConfigurationUnavailable(true);
      return null;
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void reload(); }, [table.sourceKey, table.contentHash, tenantId, userId]);

  const runRefresh = async (sqlId = selectedSqlId) => {
    if (!table.sourceKey) return;
    setRefreshing(true);
    setNotice("正在触发 Data Crawler SQL 运行并拆解时间参数…");
    try {
      const result = await refreshDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey, sqlId });
      const deadline = Date.now() + 30 * 60 * 1000;
      let status = result.run.status;
      while (Date.now() < deadline && !["succeeded", "failed"].includes(status)) {
        await new Promise((resolve) => window.setTimeout(resolve, 1_500));
        const current = await fetchDataCrawlerScheduleExecution({ tenantId, userId, runId: result.run.run_id });
        status = String(current.run.status || "");
        if (["failed", "cancelled"].includes(status)) throw new Error(current.run.message || "SQL 运行失败");
        if (status === "succeeded") break;
      }
      if (status !== "succeeded") throw new Error("SQL 运行等待超时");
      const refreshed = await reload();
      const nextState = {
        ...(refreshed || state || {}),
        tenant_id: refreshed?.tenant_id || state?.tenant_id || tenantId,
        source_key: table.sourceKey,
        institution_id: refreshed?.institution_id || state?.institution_id || "",
        institution_directory: refreshed?.institution_directory || state?.institution_directory || "",
        validation_required: true,
        available_bindings: refreshed?.available_bindings || state?.available_bindings || [],
        task: refreshed?.task || state?.task || null,
        binding: result.binding || refreshed?.binding || null,
      };
      const nextDraft = defaultDataCrawlerDraft(nextState);
      setState(nextState);
      setDraft(nextDraft);
      setSelectedSqlId(result.binding?.sqlId || nextDraft.sqlId);
      setNotice("数据已开始刷新；SQL 时间参数已拆解到本页，可继续完成定时配置。");
    } catch (error) {
      setNotice(apiErrorMessage(error, "刷新失败，请确认 Data Crawler 可连通后重试。"));
    } finally {
      setRefreshing(false);
    }
  };

  const refreshButton = (
    <button
      type="button"
      disabled={refreshing || loading || !table.sourceKey}
      onClick={() => void runRefresh()}
      className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-lg border border-[#d9dedb] bg-white px-3.5 text-[12px] font-medium text-[#3f4843] transition-colors hover:bg-[#f4f6f5] focus:outline-none focus:ring-2 focus:ring-[#dceee4] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {refreshing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
      {refreshing ? "刷新中…" : "刷新"}
    </button>
  );

  if (!table.sourceKey) return <div className="p-4"><div className="flex items-start gap-3 rounded-lg border border-[#f3d5d0] bg-[#fff8f7] px-4 py-3 text-[11px] leading-5 text-[#a83c32]"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" /><div><div className="font-medium">暂时无法设置定时任务</div><div className="mt-0.5 text-[#8d5b55]">当前 CSV 缺少稳定来源标识，请先重新同步数据资产。</div></div></div></div>;
  if (loading && !state && !refreshing) return <div className="flex min-h-[140px] items-center justify-center gap-2 p-4 text-[11px] text-[#8a8a8e]"><RefreshCw className="h-3.5 w-3.5 animate-spin" />正在读取定时任务配置…</div>;
  if (!state || !draft) {
    return (
      <div className="flex items-start justify-between gap-4 px-5 py-5">
        <div className="min-w-0 text-[11px] leading-5 text-[#7a837e]">
          <div className="font-medium text-[#4e5752]">暂未读取到定时任务配置</div>
          <div className="mt-1">打开 Tab 不会自动执行 SQL。点击刷新将触发 Data Crawler 中该 SQL 的「运行」，并拆解时间参数到本页。{configurationUnavailable ? "若连接失败，请确认 Data Crawler 可用后重试。" : ""}</div>
          {notice ? <div className={`mt-2 ${notice.includes("失败") ? "text-[#a83c32]" : "text-[#087647]"}`}>{notice}</div> : null}
        </div>
        {refreshButton}
      </div>
    );
  }

  const binding = state.binding;
  const unsupported = (binding?.parameters || []).filter((item) => !["date", "month", "datetime"].includes(item.type));
  const mutateParameter = (name: string, mode: string) => {
    setDraft((current) => {
      if (!current) return current;
      const parameterBindings = { ...current.parameterBindings };
      const parameters = { ...current.parameters };
      if (mode === "fixed") delete parameterBindings[name];
      else {
        parameterBindings[name] = mode === "before" ? "before:" : "reference";
        delete parameters[name];
      }
      return { ...current, parameterBindings, parameters };
    });
  };

  const updateParameterOffset = (name: string, value: string) => {
    setDraft((current) => current ? {
      ...current,
      parameterBindings: { ...current.parameterBindings, [name]: `before:${value.replace(/\D/g, "")}` },
    } : current);
  };

  const testConnection = async () => {
    if (!binding || unsupported.length) return;
    setTesting(true);
    setNotice("正在测试机构连接、SQL 绑定、CSV 回执与时间参数…");
    try {
      const result = await testDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey!, draft });
      setNotice(`连接测试通过：${result.institution_id}、关联 SQL 与 ${result.parameter_count} 个时间参数均可用。`);
    } catch (error) {
      setNotice(apiErrorMessage(error, "连接测试失败"));
    } finally {
      setTesting(false);
    }
  };

  const save = async (execute: boolean) => {
    if (!binding || unsupported.length) return;
    setLoading(true);
    setNotice(execute ? "正在校验连接与交付回执，验证通过后立即执行…" : "正在校验连接与交付回执，验证通过后保存配置…");
    try {
      if (execute) {
        const result = await executeDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey!, draft });
        onScheduleStatusChange(table.sourceKey!, dataCrawlerScheduleListStatus(result.task, draft));
        const deadline = Date.now() + 30 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((resolve) => window.setTimeout(resolve, 1_500));
          const current = await fetchAutomationRun({ tenantId, userId, runId: result.run.automation_run_id });
          if (current.run.status === "succeeded") {
            await reload();
            setNotice("数据拉取完成，当前机构 CSV 已生成并通过回执校验。");
            return;
          }
          if (["failed", "cancelled", "dead_letter"].includes(current.run.status)) throw new Error(current.run.error_summary || "数据拉取失败");
        }
        throw new Error("数据拉取等待超时");
      } else {
        const result = await saveDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey!, draft });
        onScheduleStatusChange(table.sourceKey!, dataCrawlerScheduleListStatus(result.task, draft));
        await reload();
        setNotice(draft.recurrence === "none" ? "参数已保存；点击执行可立即拉取一次。" : "定时任务已保存，将按设置自动执行。");
      }
    } catch (error) {
      setNotice(apiErrorMessage(error, execute ? "数据拉取失败" : "定时任务保存失败"));
    } finally {
      setLoading(false);
    }
  };

  const clear = async () => {
    setLoading(true);
    try {
      await clearDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey! });
      const refreshed = await fetchDataCrawlerSchedule({ tenantId, userId, sourceKey: table.sourceKey! });
      setState(refreshed);
      setDraft(defaultDataCrawlerDraft({ ...refreshed, task: null }));
      onScheduleStatusChange(table.sourceKey!, null);
      setNotice("设置已清空，Data Crawler 本地任务不再受 SDA 控制。");
    } catch (error) {
      setNotice(apiErrorMessage(error, "取消定时任务失败"));
    } finally {
      setLoading(false);
    }
  };

  const successfulNotice = notice.includes("完成") || notice.includes("已保存") || notice.includes("已清空") || notice.includes("通过") || notice.includes("拆解");
  const pendingNotice = notice.includes("正在");

  return (
    <div className="px-5 py-4 text-[12px] text-[#3a3a3c]">
      {!binding ? (
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 leading-5 text-[#7a837e]">
            <div className="font-medium text-[#4e5752]">暂未识别到唯一的关联 SQL</div>
            <p className="mt-1 text-[10px]">点击刷新将按 Data Crawler「运行」执行一次 SQL，并把时间参数拆解到本页。打开 Tab 不会自动执行。</p>
            {state.available_bindings.length > 1 ? (
              <label className="mt-3 block max-w-md">
                <span className="mb-1.5 block text-[11px] font-medium text-[#626b66]">选择要运行的 SQL</span>
                <select aria-label="选择要运行的 SQL" className={scheduleControlClass} value={selectedSqlId} onChange={(event) => setSelectedSqlId(event.target.value)}>
                  <option value="">请选择 SQL</option>
                  {state.available_bindings.map((item) => (
                    <option key={item.sqlId} value={item.sqlId}>{item.sqlName}</option>
                  ))}
                </select>
              </label>
            ) : null}
            {notice ? <div className={`mt-2 text-[11px] ${notice.includes("失败") ? "text-[#a83c32]" : "text-[#087647]"}`}>{notice}</div> : null}
          </div>
          {refreshButton}
        </div>
      ) : (
        <>
          <div className="grid items-start gap-3 md:grid-cols-[minmax(0,1.15fr)_minmax(0,0.8fr)_minmax(0,1fr)_auto]">
              <div>
                <div className="mb-1.5 text-[11px] font-medium text-[#626b66]">关联 SQL</div>
                <div className="flex h-9 min-w-0 items-center gap-2 rounded-lg border border-[#e4e8e5] bg-[#f8faf9] px-3 text-[12px] text-[#303633]">
                  <Link2 className="h-3.5 w-3.5 shrink-0 text-[#818a85]" />
                  <span className="min-w-0 flex-1 truncate" title={binding.sqlName}>{binding.sqlName}</span>
                  <span className="shrink-0 text-[10px] text-[#25825a]">待校验</span>
                </div>
              </div>
              <div>
                <span className="mb-1.5 block text-[11px] font-medium text-[#626b66]">循环方式</span>
                <ScheduleSelect label="循环方式" value={draft.recurrence} onValueChange={(value) => setDraft({ ...draft, recurrence: value as DataCrawlerScheduleDraft["recurrence"] })} options={[{ value: "none", label: "不循环（仅手动执行）" }, { value: "daily", label: "每日", disabled: !binding.parameters.length }, { value: "weekly", label: "每周", disabled: !binding.parameters.length }, { value: "biweekly", label: "每双周", disabled: !binding.parameters.length }, { value: "monthly", label: "每月", disabled: !binding.parameters.length }]} />
                {!binding.parameters.length && <span className="mt-1.5 block text-[10px] text-[#8a928d]">无参数 SQL 仅支持手动执行一次。</span>}
              </div>
              {draft.recurrence !== "none" && <div><span className="mb-1.5 block text-[11px] font-medium text-[#626b66]">执行日期与时间</span><ScheduleDateControl label="执行日期与时间" value={draft.executionAt} includeTime onChange={(value) => setDraft({ ...draft, executionAt: value })} /></div>}
              <div className="flex h-9 items-end self-start pt-6">{refreshButton}</div>
          </div>
          <div className="mt-5 border-t border-[#e8ece9] pt-3.5">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2"><GitBranch className="h-3.5 w-3.5 text-[#7d8781]" /><div className="text-[12px] font-medium text-[#424b46]">SQL 时间参数</div></div>
                <span className="shrink-0 text-[10px] text-[#929a96]">{binding.parameters.length} 个</span>
              </div>
              {!binding.parameters.length && <div className="mt-3 flex items-center gap-2 text-[10px] text-[#7a837e]"><CheckCircle2 className="h-3.5 w-3.5 text-[#0f8f58]" />该 SQL 无参数，保持“不循环”后可直接执行一次。</div>}
              {Boolean(binding.parameters.length) && <div className="mt-1">{binding.parameters.map((parameter) => {
                const rule = draft.parameterBindings[parameter.name] || "fixed";
                const mode = scheduleParameterMode(rule);
                const offset = scheduleParameterOffset(rule);
                const unit = parameter.type === "month" ? "月" : "日";
                const referenceLabel = parameter.type === "month" ? "取值月" : "取值日";
                const fixedValue = draft.parameters[parameter.name] || "";
                return (
                  <div key={parameter.name} className="grid items-start gap-3 py-3 md:grid-cols-[minmax(170px,0.8fr)_minmax(220px,1fr)_minmax(250px,1.1fr)]">
                    <div className="min-w-0 self-center">
                      <div className="truncate text-[12px] font-medium text-[#303633]" title={parameter.name}>{temporalParameterLabel(parameter.name, parameter.type)}</div>
                      <div className="mt-1 truncate font-mono text-[10px] text-[#929a96]" title={parameter.name}>{parameter.name} · SQL 中使用 {parameter.occurrenceCount} 次 · {parameter.type}</div>
                    </div>
                    {["date", "month", "datetime"].includes(parameter.type) ? (
                      <>
                        <div>
                          <span className="mb-1.5 block text-[11px] font-medium text-[#626b66]">取值方式</span>
                          <ScheduleSelect label={`${parameter.name} 取值方式`} value={mode} onValueChange={(value) => mutateParameter(parameter.name, value)} options={[{ value: "fixed", label: "固定值" }, { value: "reference", label: referenceLabel }, { value: "before", label: `${referenceLabel}前第 N ${unit}` }]} />
                        </div>
                        <div>
                          <span className="mb-1.5 block text-[11px] font-medium text-[#626b66]">{mode === "fixed" ? "固定值" : mode === "reference" ? "取值结果" : `N（${unit}）`}</span>
                          {mode === "fixed" ? (
                            parameter.type === "month"
                              ? <ScheduleMonthControl label={`${parameter.name} 固定值`} value={fixedValue} onChange={(value) => setDraft({ ...draft, parameters: { ...draft.parameters, [parameter.name]: value } })} />
                              : <ScheduleDateControl label={`${parameter.name} 固定值`} value={fixedValue} includeTime={parameter.type === "datetime"} onChange={(value) => setDraft({ ...draft, parameters: { ...draft.parameters, [parameter.name]: value } })} />
                          ) : mode === "reference" ? (
                            <div className="flex h-9 items-center rounded-lg border border-[#e5e9e6] bg-[#f8faf9] px-3 text-[12px] text-[#5f6863]">{temporalReferencePreview(draft.executionAt, parameter.type)}</div>
                          ) : (
                            <div className="relative">
                              <input aria-label={`${parameter.name} 提前${unit}数`} type="text" inputMode="numeric" placeholder="请输入 N" className={`${scheduleControlClass} pr-9`} value={offset} onChange={(event) => updateParameterOffset(parameter.name, event.target.value)} />
                              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[11px] text-[#8b938f]">{unit}</span>
                            </div>
                          )}
                        </div>
                      </>
                    ) : <div className="flex min-h-9 items-center text-[11px] text-[#a83c32] md:col-span-2">非时间参数当前仅展示，暂不允许在 SDA 中改写。</div>}
                  </div>
                );
              })}</div>}
          </div>
        </>
      )}
      {notice && <div role="status" aria-live="polite" className={`mt-3 flex items-start gap-2 rounded-lg px-3 py-2 text-[11px] leading-5 ${successfulNotice ? "bg-[#f1f8f4] text-[#087647]" : pendingNotice ? "bg-[#f5f7f6] text-[#69726d]" : "bg-[#fff6f4] text-[#a83c32]"}`}>{successfulNotice ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" /> : pendingNotice ? <RefreshCw className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin" /> : <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />}<span>{notice}</span></div>}
      <div className="mt-4 flex items-center justify-end">
        <div className="flex shrink-0 items-center justify-end gap-2">
          <button type="button" title="清空 SDA 中的全部设置并释放控制权" disabled={loading || testing} onClick={() => void clear()} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-transparent px-3 text-[12px] text-[#707873] transition-colors hover:border-[#dfe3e1] hover:bg-[#fafbfa] disabled:cursor-not-allowed disabled:opacity-50"><RotateCcw className="h-3.5 w-3.5" />取消</button>
          <button type="button" disabled={loading || testing || !binding || Boolean(unsupported.length)} onClick={() => void testConnection()} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#d9dedb] bg-white px-3.5 text-[12px] font-medium text-[#3f4843] transition-colors hover:bg-[#f4f6f5] focus:outline-none focus:ring-2 focus:ring-[#dceee4] disabled:cursor-not-allowed disabled:opacity-50">{testing ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Activity className="h-3.5 w-3.5" />}{testing ? "测试中…" : "测试"}</button>
          <button type="button" disabled={loading || testing || !binding || Boolean(unsupported.length)} onClick={() => void save(false)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#d9dedb] bg-white px-3.5 text-[12px] font-medium text-[#3f4843] transition-colors hover:bg-[#f4f6f5] focus:outline-none focus:ring-2 focus:ring-[#dceee4] disabled:cursor-not-allowed disabled:opacity-50"><Save className="h-3.5 w-3.5" />确定</button>
          <button type="button" disabled={loading || testing || !binding || Boolean(unsupported.length)} onClick={() => void save(true)} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#0f8f58] px-4 text-[12px] font-medium text-white shadow-sm shadow-[#0f8f58]/15 transition-colors hover:bg-[#0b7d4c] focus:outline-none focus:ring-2 focus:ring-[#b9dfca] disabled:cursor-not-allowed disabled:opacity-50">{loading ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}{loading ? "处理中…" : "执行"}</button>
        </div>
      </div>
    </div>
  );
}

function RawTableCard({
  table,
  tenantId,
  userId,
  scheduleStatus,
  onScheduleStatusChange,
  onExternalReferenceChange,
  onSave,
}: {
  table: RawTableAsset;
  tenantId: string;
  userId: string;
  scheduleStatus?: DataCrawlerScheduleListStatus;
  onScheduleStatusChange: (sourceKey: string, status: DataCrawlerScheduleListStatus | null) => void;
  onExternalReferenceChange: (table: RawTableAsset, mode: "private" | "shared") => Promise<void>;
  onSave: (table: RawTableAsset, fields: RawField[]) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draftFields, setDraftFields] = useState(() => normalizeFieldSemantics(table.fields, [table.primaryKey]));
  const [activeDetailTab, setActiveDetailTab] = useState<"preview" | "metadata" | "schedule">("preview");
  const previewHeaders = Object.keys(table.previewRows?.[0] || {}).length
    ? Object.keys(table.previewRows?.[0] || {})
    : table.fields.map((field) => field.fieldNameCn || field.fieldNameEn);

  useEffect(() => {
    if (!editing) setDraftFields(normalizeFieldSemantics(table.fields, [table.primaryKey]));
  }, [editing, table]);

  const save = async () => {
    setSaving(true);
    try {
      await onSave(table, draftFields);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const previewField = (header: string) => table.fields.find((field) => field.fieldNameCn === header || field.fieldNameEn === header);

  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className={`${expanded ? "mb-3" : ""} flex flex-col items-stretch gap-3 lg:flex-row lg:items-start`} data-raw-table-summary="true">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2 overflow-hidden">
            <Database className="h-4 w-4 shrink-0 text-[#8a8a8e]" />
            <h4 className="min-w-0 max-w-[320px] truncate text-[13px] text-[#1d1d1f]" title={table.tableNameCn}>{table.tableNameCn}</h4>
            {scheduleStatus?.scheduled && <span className="inline-flex h-5 shrink-0 items-center gap-1 rounded-full bg-[#e5f5ec] px-2 text-[10px] font-medium text-[#087647]" title={`已启用${scheduleStatus.recurrence || "循环"}定时任务${scheduleStatus.next_run_at ? `；下次执行 ${scheduleStatus.next_run_at}` : ""}`}><CalendarClock className="h-3 w-3" />已定时</span>}
            <span className="shrink-0 font-mono text-[11px] text-[#8a8a8e]">{table.tableNameEn}</span>
            {table.fileName && <span className="min-w-0 max-w-[280px] truncate rounded-full border border-[#e5e5ea] bg-white px-2 py-0.5 text-[10px] text-[#636366]" title={table.fileName} data-raw-table-file-name="true">文件：{table.fileName}</span>}
          </div>
          <p className="mt-1 text-[11px] leading-[1.6] text-[#636366]">更新时间：{formatAssetTime(table.updatedAt)}</p>
        </div>
        <div className="flex shrink-0 flex-nowrap items-center gap-2 self-end whitespace-nowrap lg:self-start" data-raw-table-actions="true">
          <label className="flex shrink-0 items-center gap-1.5 whitespace-nowrap text-[11px] text-[#636366]">
            <span>外部引用</span>
            <select
              aria-label={`${table.tableNameCn} 外部引用`}
              value={table.externalReferenceMode || "private"}
              disabled={!table.sourceKey || !table.schemaFingerprint}
              onChange={(event) => void onExternalReferenceChange(table, event.target.value as "private" | "shared")}
              className="h-7 shrink-0 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none disabled:cursor-not-allowed disabled:text-[#aeaeb2]"
              title={table.externalReferenceSchemaChanged ? "文件字段结构已变化，已自动改为单独使用；如需继续授权，请重新选择可分享。" : "该设置仅管理 WorkBuddy、Codex、QWork Bridge 能否读取此 CSV，不会写入或修改 CSV 文件。"}
            >
              <option value="private">单独使用</option>
              <option value="shared">可分享</option>
            </select>
          </label>
          <span className="h-7 shrink-0 whitespace-nowrap rounded-md border border-[#e5e5ea] bg-white px-2 py-1 text-[11px] text-[#636366]">
            CSV 文件 · {table.rowCount ?? 0} 行
          </span>
          <AssetEditActions
            editing={editing}
            saving={saving}
            onEdit={() => { setExpanded(true); setActiveDetailTab("metadata"); setEditing(true); }}
            onCancel={() => { setDraftFields(normalizeFieldSemantics(table.fields, [table.primaryKey])); setEditing(false); }}
            onSave={save}
          />
          <AssetCollapseButton
            expanded={expanded}
            label={expanded ? `折叠${table.tableNameCn}` : `展开${table.tableNameCn}`}
            onClick={() => setExpanded((open) => !open)}
          />
        </div>
      </div>
      {expanded && (
        <div className="overflow-hidden rounded-lg border border-[#f0f0f2] bg-white">
          <div className="flex items-center gap-1 border-b border-[#f0f0f2] bg-[#fafbfc] px-3 pt-2">
            <button type="button" onClick={() => setActiveDetailTab("preview")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "preview" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>原始数据（前 10 行）</button>
            <button type="button" onClick={() => setActiveDetailTab("metadata")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "metadata" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>字段元数据及解读</button>
            <button type="button" onClick={() => setActiveDetailTab("schedule")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "schedule" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>定时任务</button>
          </div>
          {activeDetailTab === "preview" ? (
            <div className="max-h-[360px] overflow-auto">
              <table className="min-w-full text-left text-[11px]">
                <thead className="sticky top-0 bg-white text-[#8a8a8e]">
                  <tr>{previewHeaders.map((header) => <th key={header} className="whitespace-nowrap border-b border-[#f0f0f2] px-3 py-2 font-normal">{header}</th>)}</tr>
                </thead>
                <tbody>
                  {(table.previewRows || []).map((row, rowIndex) => <tr key={rowIndex} className="border-b border-[#f8f8f8] last:border-b-0">{previewHeaders.map((header) => { const value = formatFieldValue(row[header], previewField(header)); return <td key={header} className="max-w-[280px] truncate px-3 py-2 text-[#3a3a3c]" title={value}>{value}</td>; })}</tr>)}
                </tbody>
              </table>
              {!table.previewRows?.length && <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">文件没有可展示的数据行</div>}
            </div>
          ) : activeDetailTab === "metadata" ? (
            <AssetFieldTable
              fields={editing ? draftFields : normalizeFieldSemantics(table.fields, [table.primaryKey])}
              editing={editing}
              onChange={(index, key, value) => setDraftFields((current) => updateFieldSemanticValue(current, index, key, value))}
            />
          ) : (
            <DataCrawlerSchedulePanel table={table} tenantId={tenantId} userId={userId} onScheduleStatusChange={onScheduleStatusChange} />
          )}
        </div>
      )}
    </div>
  );
}

function TopicTableCard({
  tenantId,
  topic,
  onSave,
  onDelete,
}: {
  tenantId: string;
  topic: TopicTableAsset;
  onSave: (topic: TopicTableAsset) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [draftFields, setDraftFields] = useState<RawField[]>(() => normalizeTopicFields(topic));
  const [saving, setSaving] = useState(false);
  const [activeDetailTab, setActiveDetailTab] = useState<"data" | "raw" | "metadata">("data");
  const [snapshot, setSnapshot] = useState<TopicDataSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [snapshotError, setSnapshotError] = useState("");

  useEffect(() => {
    if (!editing) setDraftFields(normalizeTopicFields(topic));
  }, [editing, topic]);

  useEffect(() => {
    if (!expanded || activeDetailTab === "metadata") return;
    let cancelled = false;
    setSnapshotLoading(true);
    setSnapshotError("");
    void fetchTopicData({
      tenantId,
      referenceType: "topic",
      referenceId: topic.id,
      dataType: activeDetailTab === "raw" ? "raw" : "data",
    })
      .then((response) => {
        if (!cancelled) setSnapshot(response);
      })
      .catch((error) => {
        if (!cancelled) {
          setSnapshot(null);
          setSnapshotError(apiErrorMessage(error, "暂无 Topic_Data 结果；等待每日定时加工或从智能分析保存主题表。"));
        }
      })
      .finally(() => {
        if (!cancelled) setSnapshotLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeDetailTab, expanded, tenantId, topic.id]);

  const save = async () => {
    setSaving(true);
    try {
      await onSave({ ...topic, fields: draftFields });
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className={`${expanded ? "mb-3" : ""} flex flex-wrap items-start justify-between gap-3`}>
        <div>
          <div className="flex items-center gap-2">
            <Layers3 className="h-4 w-4 text-[#8a8a8e]" />
            <h4 className="text-[13px] text-[#1d1d1f]">{topic.name}</h4>
            <span className="font-mono text-[11px] text-[#8a8a8e]">{topic.code}</span>
          </div>
          <p className="mt-1 text-[11px] leading-[1.6] text-[#636366]">更新时间：{formatAssetTime(topic.dataSnapshot?.updated_at || topic.updatedAt)}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="h-7 rounded-md border border-[#e5e5ea] bg-white px-2 py-1 text-[11px] text-[#636366]">主题表 · {topic.dataSnapshot?.row_count ?? topic.rowCount ?? 0} 行</span>
          <AssetEditActions
            editing={editing}
            saving={saving}
            onEdit={() => {
              setExpanded(true);
              setEditing(true);
            }}
            onCancel={() => {
              setDraftFields(normalizeTopicFields(topic));
              setEditing(false);
            }}
            onSave={save}
          />
          <AssetDeleteButton label={`删除主题表${topic.name}`} disabled={editing || saving} onClick={onDelete} />
          <AssetCollapseButton
            expanded={expanded}
            label={expanded ? `折叠${topic.name}` : `展开${topic.name}`}
            onClick={() => setExpanded((open) => !open)}
          />
        </div>
      </div>
      {expanded && (
        <div className="overflow-hidden rounded-lg border border-[#f0f0f2] bg-white">
          <div className="flex items-center gap-1 border-b border-[#f0f0f2] bg-[#fafbfc] px-3 pt-2">
            <button type="button" onClick={() => setActiveDetailTab("data")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "data" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>数据</button>
            <button type="button" onClick={() => setActiveDetailTab("raw")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "raw" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>原始数据</button>
            <button type="button" onClick={() => setActiveDetailTab("metadata")} className={`rounded-t-md px-3 py-2 text-[11px] ${activeDetailTab === "metadata" ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>字段元数据及解读</button>
          </div>
          {activeDetailTab === "metadata" ? (
            <AssetFieldTable
              fields={editing ? draftFields : normalizeTopicFields(topic)}
              editing={editing}
              onChange={(index, key, value) => setDraftFields((current) => current.map((field, fieldIndex) => fieldIndex === index ? { ...field, [key]: value } : field))}
            />
          ) : snapshotLoading ? (
            <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">正在读取 Topic_Data 最新结果…</div>
          ) : snapshot ? (
            <TopicDataTable snapshot={snapshot} />
          ) : (
            <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">{snapshotError || "尚无 Topic_Data 结果；等待每日定时加工或从智能分析保存主题表。"}</div>
          )}
        </div>
      )}
    </div>
  );
}

function TopicDataTable({ snapshot }: { snapshot: TopicDataSnapshot }) {
  return (
    <div className="max-h-[360px] overflow-auto">
      <table className="min-w-full text-left text-[11px]">
        <thead className="sticky top-0 bg-white text-[#8a8a8e]"><tr>{snapshot.columns.map((column) => <th key={column} className="whitespace-nowrap border-b border-[#f0f0f2] px-3 py-2 font-normal">{column}</th>)}</tr></thead>
        <tbody>{snapshot.rows.map((row, rowIndex) => <tr key={rowIndex} className="border-b border-[#f8f8f8] last:border-b-0">{snapshot.columns.map((column) => <td key={column} title={row[column] || ""} className="max-w-[280px] truncate px-3 py-2 text-[#3a3a3c]">{row[column] || ""}</td>)}</tr>)}</tbody>
      </table>
      {!snapshot.rows.length && <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">当前最新快照没有可展示的数据行</div>}
      {snapshot.truncated && <div className="border-t border-[#f0f0f2] px-3 py-2 text-[10px] text-[#8a8a8e]">为保护页面性能，仅展示前 {snapshot.rows.length} 行；当前快照共 {snapshot.row_count} 行。</div>}
    </div>
  );
}

function formatAssetTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function AssetCollapseButton({
  expanded,
  label,
  onClick,
}: {
  expanded: boolean;
  label: string;
  onClick: () => void;
}) {
  const Icon = expanded ? ChevronUp : ChevronDown;
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-[#e5e5ea] bg-white text-[#636366] hover:bg-[#f2f2f7]"
    >
      <Icon className="h-3.5 w-3.5 text-[#8a8a8e]" />
    </button>
  );
}

function AssetEditActions({
  editing,
  saving,
  onEdit,
  onCancel,
  onSave,
}: {
  editing: boolean;
  saving: boolean;
  onEdit: () => void;
  onCancel: () => void;
  onSave: () => void | Promise<void>;
}) {
  if (!editing) {
    return (
      <button
        type="button"
        onClick={onEdit}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
      >
        <Pencil className="h-3.5 w-3.5 text-[#8a8a8e]" />
        编辑
      </button>
    );
  }
  return (
    <>
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md bg-[#1d1d1f] px-2 text-[11px] text-white hover:bg-[#2c2c2e] disabled:opacity-50"
      >
        <Save className="h-3.5 w-3.5" />
        保存
      </button>
      <button
        type="button"
        onClick={onCancel}
        disabled={saving}
        className="inline-flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50"
      >
        <X className="h-3.5 w-3.5 text-[#8a8a8e]" />
        取消
      </button>
    </>
  );
}

function AssetDeleteButton({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title="删除"
      disabled={disabled}
      onClick={onClick}
      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025] disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Trash2 className="h-3.5 w-3.5" />
    </button>
  );
}

function AssetFieldTable({
  fields,
  editing,
  onChange,
}: {
  fields: RawField[];
  editing: boolean;
  onChange: (index: number, key: "semanticRole" | "type" | "isPrimaryKey" | "explanation" | "exampleUsage", value: string | boolean) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[#f0f0f2] bg-white">
      <div className="grid min-w-[1040px] grid-cols-[1fr_1fr_0.72fr_0.8fr_0.66fr_1.45fr_1.3fr] gap-2 bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
        <span>字段英文</span>
        <span>字段中文</span>
        <span>字段角色</span>
        <span>类型</span>
        <span>是否主键</span>
        <span>语义解释</span>
        <span>示例用法</span>
      </div>
      {fields.map((field, index) => (
        <div key={`${field.fieldNameEn}_${index}`} className="grid min-w-[1040px] grid-cols-[1fr_1fr_0.72fr_0.8fr_0.66fr_1.45fr_1.3fr] items-start gap-2 border-t border-[#f8f8f8] px-3 py-2 text-[11px]">
          <span className="font-mono text-[#3a3a3c]">{field.fieldNameEn}</span>
          <span className="text-[#1d1d1f]">{field.fieldNameCn}</span>
          {editing ? (
            <>
              <select aria-label={`${field.fieldNameCn || field.fieldNameEn}字段角色`} value={field.semanticRole} onChange={(event) => onChange(index, "semanticRole", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#8fbfa4]"><option value="metric">指标</option><option value="dimension">维度</option><option value="date">日期</option></select>
              <select aria-label={`${field.fieldNameCn || field.fieldNameEn}字段类型`} value={field.semanticRole === "date" ? dateFieldFormat : field.type} onChange={(event) => onChange(index, "type", event.target.value)} disabled={field.semanticRole !== "metric"} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#8fbfa4] disabled:bg-[#fafbfc] disabled:text-[#8a8a8e]">{field.semanticRole === "metric" ? metricFieldTypes.map((type) => <option key={type} value={type}>{type}</option>) : <option value={field.semanticRole === "date" ? dateFieldFormat : "string"}>{field.semanticRole === "date" ? dateFieldFormat : "string"}</option>}</select>
              <select aria-label={`${field.fieldNameCn || field.fieldNameEn}是否主键`} value={field.isPrimaryKey ? "yes" : "no"} onChange={(event) => onChange(index, "isPrimaryKey", event.target.value === "yes")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#8fbfa4]"><option value="no">否</option><option value="yes">是</option></select>
              <textarea
                value={field.explanation}
                onChange={(event) => onChange(index, "explanation", event.target.value)}
                className="mr-2 min-h-[56px] rounded-md border border-[#e5e5ea] bg-white px-2 py-1.5 text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
              />
              <textarea
                value={field.exampleUsage || ""}
                onChange={(event) => onChange(index, "exampleUsage", event.target.value)}
                className="min-h-[56px] rounded-md border border-[#e5e5ea] bg-white px-2 py-1.5 text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
              />
            </>
          ) : (
            <>
              <span className="text-[#636366]">{field.semanticRole === "metric" ? "指标" : field.semanticRole === "date" ? "日期" : "维度"}</span>
              <span className="text-[#8a8a8e]">{field.semanticRole === "date" ? dateFieldFormat : field.type}</span>
              <span className={field.isPrimaryKey ? "text-[#178a53]" : "text-[#8a8a8e]"}>{field.isPrimaryKey ? "是" : "否"}</span>
              <span className="text-[#636366]">{field.explanation || "未配置"}</span>
              <span className="text-[#636366]">{field.exampleUsage || "未配置"}</span>
            </>
          )}
        </div>
      ))}
      {!fields.length && (
        <div className="border-t border-[#f8f8f8] px-3 py-6 text-center text-[11px] text-[#aeaeb2]">
          暂无字段元数据
        </div>
      )}
    </div>
  );
}

function normalizeTopicFields(topic: TopicTableAsset): RawField[] {
  if (Array.isArray(topic.fields)) return normalizeFieldSemantics(topic.fields);
  const fieldNames = String(topic.fields || "")
    .split(/[,\uFF0C、]/)
    .map((field) => field.trim())
    .filter(Boolean);
  const explanations = String(topic.fieldExplanations || "")
    .split(/[,\uFF0C、]/)
    .map((field) => field.trim());
  return normalizeFieldSemantics(fieldNames.map((fieldName, index) => ({
    fieldNameEn: fieldName,
    fieldNameCn: explanations[index] || fieldName,
    type: inferFieldType(fieldName),
    explanation: explanations[index] || "待补充字段语义解释。",
    exampleUsage: "智能分析、经营周报、主题表复用",
  })));
}

function inferFieldType(fieldName: string) {
  if (/date|time|日期|时间/i.test(fieldName)) return "date";
  if (/rate|ratio|percent|pct|率|占比|比例/i.test(fieldName)) return "rate";
  if (/amount|balance|rate|count|num|金额|余额|率|数/i.test(fieldName)) return "decimal";
  return "string";
}

function MemoryList({
  itemType,
  items,
  canManage,
  onView,
  onEdit,
  onDelete,
}: {
  itemType: MemoryItemType;
  items: ManagedMemoryAsset[];
  canManage: boolean;
  onView: (item: ManagedMemoryAsset) => void;
  onEdit: (item: ManagedMemoryAsset) => void;
  onDelete: (item: ManagedMemoryAsset) => void;
}) {
  return (
    <div role="list" className="overflow-hidden rounded-lg border border-[#e8e8ec] bg-white">
      {items.map((item) => {
        const title = memoryItemTitle(itemType, item);
        const summary = memoryItemSummary(itemType, item);
        const meta = memoryItemMeta(itemType, item);
        const status = memoryItemStatus(itemType, item);
        const MemoryIcon = itemType === "intent" ? Layers3 : itemType === "knowledge_file" ? BookOpen : itemType === "analysis_experience" ? Sparkles : Activity;
        return (
          <div key={item.id} role="listitem" className="flex min-h-[68px] items-center gap-3 border-b border-[#f0f0f2] px-4 py-3 last:border-b-0 hover:bg-[#fafbfc]">
            <div className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#f5f5f7] text-[#8a8a8e]">
              <MemoryIcon className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                <h5 className="max-w-full truncate text-[13px] font-medium text-[#1d1d1f]" title={title}>{title}</h5>
                <span className={`rounded-full px-2 py-0.5 text-[10px] ${status === "当前有效" || status === "已启用" ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`}>{status}</span>
              </div>
              <p className="mt-0.5 truncate text-[11px] leading-5 text-[#636366]" title={summary}>{summary || "暂无内容摘要"}</p>
              <p className="truncate text-[10px] leading-4 text-[#aeaeb2]" title={meta}>{meta}</p>
            </div>
            <div className="ml-auto flex shrink-0 items-center gap-0.5" aria-label={`${title}操作`}>
              <MemoryIconButton label={`查看${title}`} title="查看" onClick={() => onView(item)}><Eye className="h-3.5 w-3.5" /></MemoryIconButton>
              {canManage && <MemoryIconButton label={`编辑${title}`} title="编辑" onClick={() => onEdit(item)}><Pencil className="h-3.5 w-3.5" /></MemoryIconButton>}
              {canManage && <MemoryIconButton label={`删除${title}`} title="删除" danger onClick={() => onDelete(item)}><Trash2 className="h-3.5 w-3.5" /></MemoryIconButton>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function MemoryIconButton({ label, title, danger = false, onClick, children }: { label: string; title: string; danger?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      onClick={onClick}
      className={`inline-flex h-8 w-8 items-center justify-center rounded-md transition-colors ${danger ? "text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]" : "text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"}`}
    >
      {children}
    </button>
  );
}

function MemoryItemEditor({
  state,
  busy,
  notice,
  canManage,
  onChange,
  onClose,
  onSave,
}: {
  state: MemoryEditorState;
  busy: boolean;
  notice: string;
  canManage: boolean;
  onChange: (state: MemoryEditorState) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const readOnly = state.mode === "view";
  const setField = (field: string, value: unknown) => onChange({ ...state, draft: { ...state.draft, [field]: value } });
  const changeType = (itemType: MemoryItemType) => onChange({ ...state, itemType, draft: emptyMemoryDraft(itemType) });
  const dialogTitle = state.mode === "create" ? `新增${memoryItemTypeLabel(state.itemType)}` : `${readOnly ? "查看" : "编辑"}${memoryItemTypeLabel(state.itemType)}`;
  const text = (field: string) => String(state.draft[field] ?? "");

  return (
    <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/20 px-4 py-8" onMouseDown={(event) => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label={dialogTitle} className="flex max-h-full w-full max-w-[680px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] font-medium text-[#1d1d1f]">{dialogTitle}</h3>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">新增和编辑会生成待复核版本，批准后才进入 Skill 与分析运行召回。</p>
          </div>
          <button type="button" aria-label="关闭记忆窗口" onClick={onClose} disabled={busy} className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] disabled:opacity-40"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {state.allowTypeChange && state.mode === "create" && (
            <MemoryEditorField label="记忆类型" value={state.itemType} readOnly={false} onChange={(value) => changeType(value as MemoryItemType)} options={memoryTypeOptions} />
          )}
          {state.itemType === "intent" && (
            <div className="grid gap-3 md:grid-cols-2">
              <MemoryEditorField label="场景" required value={text("scenario")} readOnly={readOnly} onChange={(value) => setField("scenario", value)} />
              <MemoryEditorField label="目的" required value={text("purpose")} readOnly={readOnly} onChange={(value) => setField("purpose", value)} />
              <div className="md:col-span-2"><MemoryEditorField label="记忆内容" required multiline value={text("description")} readOnly={readOnly} onChange={(value) => setField("description", value)} /></div>
              <MemoryEditorField label="关键词" required value={text("keywords")} readOnly={readOnly} onChange={(value) => setField("keywords", value)} />
              <MemoryEditorField label="适用页面" value={text("pageScope")} readOnly={readOnly} onChange={(value) => setField("pageScope", value)} />
              <MemoryEditorField label="关联主题" value={text("relatedTopic")} readOnly={readOnly} onChange={(value) => setField("relatedTopic", value)} />
              <MemoryEditorField label="关联指标" value={text("relatedMetrics")} readOnly={readOnly} onChange={(value) => setField("relatedMetrics", value)} />
              <div className="md:col-span-2"><MemoryEditorField label="示例问题" multiline value={text("examples")} readOnly={readOnly} onChange={(value) => setField("examples", value)} /></div>
            </div>
          )}
          {state.itemType === "knowledge_file" && (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2"><MemoryEditorField label="知识标题" required value={text("title")} readOnly={readOnly} onChange={(value) => setField("title", value)} /></div>
              <div className="md:col-span-2"><MemoryEditorField label="记忆内容" multiline value={text("content")} readOnly={readOnly} onChange={(value) => setField("content", value)} /></div>
              <MemoryEditorField label="标签" value={text("tags")} readOnly={readOnly} onChange={(value) => setField("tags", value)} />
              <MemoryEditorField label="维护人" value={text("owner")} readOnly={readOnly} onChange={(value) => setField("owner", value)} />
              <MemoryEditorField label="覆盖状态" value={text("coverage")} readOnly={readOnly} onChange={(value) => setField("coverage", value)} options={["待复核", "已启用", "已归档"]} />
              <MemoryEditorField label="材料条数" inputType="number" value={text("items")} readOnly={readOnly} onChange={(value) => setField("items", Number(value || 0))} />
            </div>
          )}
          {state.itemType === "analysis_experience" && (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2"><MemoryEditorField label="经验名称" required value={text("title") || text("name")} readOnly={readOnly} onChange={(value) => { setField("title", value); }} /></div>
              <div className="md:col-span-2"><MemoryEditorField label="记忆内容" multiline value={text("description")} readOnly={readOnly} onChange={(value) => setField("description", value)} /></div>
              <div className="md:col-span-2"><MemoryEditorField label="分析路径" required multiline value={text("analysisSteps") || text("steps")} readOnly={readOnly} onChange={(value) => setField("steps", value)} /></div>
              <MemoryEditorField label="适用场景" value={text("scenario")} readOnly={readOnly} onChange={(value) => setField("scenario", value)} />
              <MemoryEditorField label="关联指标" value={text("relatedMetrics") || text("metrics")} readOnly={readOnly} onChange={(value) => setField("relatedMetrics", value)} />
              <MemoryEditorField label="状态" value={text("status") || "当前有效"} readOnly={readOnly} onChange={(value) => setField("status", value)} options={["当前有效", "历史归档"]} />
              <MemoryEditorField label="来源版本" value={text("sourceVersionName") || text("sourceVersionId")} readOnly={readOnly} onChange={(value) => setField("sourceVersionName", value)} />
              <div className="md:col-span-2"><MemoryEditorField label="来源证据" multiline value={text("evidence") || text("commonConclusions")} readOnly={readOnly} onChange={(value) => setField("evidence", value)} /></div>
            </div>
          )}
          {state.itemType === "user_behavior_habit" && (
            <div className="grid gap-3 md:grid-cols-2">
              <div className="md:col-span-2"><MemoryEditorField label="习惯名称" required value={text("title")} readOnly={readOnly} onChange={(value) => setField("title", value)} /></div>
              <MemoryEditorField label="习惯类型" value={text("habitType") || "分析习惯"} readOnly={readOnly} onChange={(value) => setField("habitType", value)} options={["分析习惯", "运营习惯", "汇报习惯"]} />
              <MemoryEditorField label="状态" value={text("status") || "当前有效"} readOnly={readOnly} onChange={(value) => setField("status", value)} options={["当前有效", "历史归档"]} />
              <div className="md:col-span-2"><MemoryEditorField label="记忆内容" required multiline value={text("description")} readOnly={readOnly} onChange={(value) => setField("description", value)} /></div>
              <div className="md:col-span-2"><MemoryEditorField label="具体表现" multiline value={text("behaviorDetail")} readOnly={readOnly} onChange={(value) => setField("behaviorDetail", value)} /></div>
              <MemoryEditorField label="关联指标" value={text("relatedMetrics")} readOnly={readOnly} onChange={(value) => setField("relatedMetrics", value)} />
              <MemoryEditorField label="关联机构" value={text("relatedOrgs")} readOnly={readOnly} onChange={(value) => setField("relatedOrgs", value)} />
              <MemoryEditorField label="来源版本 ID" required value={text("sourceVersionId")} readOnly={readOnly} onChange={(value) => setField("sourceVersionId", value)} />
              <MemoryEditorField label="来源版本名称" value={text("sourceVersionName")} readOnly={readOnly} onChange={(value) => setField("sourceVersionName", value)} />
              <div className="md:col-span-2"><MemoryEditorField label="来源证据" required multiline value={text("evidence")} readOnly={readOnly} onChange={(value) => setField("evidence", value)} /></div>
            </div>
          )}
          {notice && state.mode !== "view" && <div role={/失败|请|冲突|无权限/.test(notice) ? "alert" : "status"} className={`mt-4 rounded-lg px-3 py-2 text-[11px] ${/失败|请|冲突|无权限/.test(notice) ? "bg-[#fff0f0] text-[#d93025]" : "bg-[#eef8f1] text-[#258a3f]"}`}>{notice}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-[#f0f0f2] px-5 py-3">
          <button type="button" onClick={onClose} disabled={busy} className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-40">{readOnly ? "关闭" : "取消"}</button>
          {readOnly && canManage && <button type="button" onClick={() => onChange({ ...state, mode: "edit" })} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 text-[12px] text-white"><Pencil className="h-3.5 w-3.5" />编辑</button>}
          {!readOnly && <button type="button" onClick={onSave} disabled={busy} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 text-[12px] text-white disabled:opacity-40"><Save className="h-3.5 w-3.5" />{busy ? "保存中…" : "保存"}</button>}
        </div>
      </div>
    </div>
  );
}

function MemoryEditorField({ label, value, readOnly, onChange, required = false, multiline = false, inputType = "text", options }: { label: string; value: string; readOnly: boolean; onChange: (value: string) => void; required?: boolean; multiline?: boolean; inputType?: "text" | "number"; options?: string[] }) {
  const controlClass = `mt-1 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] leading-5 text-[#3a3a3c] outline-none focus:border-[#c7c7cc] ${readOnly ? "cursor-default bg-[#fafbfc] text-[#636366]" : ""}`;
  return (
    <label className="block text-[11px] text-[#636366]">
      {label}{required && <span className="ml-0.5 text-[#d93025]">*</span>}
      {options ? (
        <select aria-label={label} value={value} disabled={readOnly} onChange={(event) => onChange(event.target.value)} className={`${controlClass} h-9 disabled:opacity-100`}>{options.map((option) => <option key={option} value={option}>{memoryTypeOptionLabel(option)}</option>)}</select>
      ) : multiline ? (
        <textarea aria-label={label} value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} rows={3} className={`${controlClass} min-h-[82px] py-2`} />
      ) : (
        <input aria-label={label} type={inputType} value={value} readOnly={readOnly} onChange={(event) => onChange(event.target.value)} className={`${controlClass} h-9`} />
      )}
    </label>
  );
}

function MemoryDeleteConfirm({ itemType, item, deleting, onCancel, onConfirm }: { itemType: MemoryItemType; item: ManagedMemoryAsset; deleting: boolean; onCancel: () => void; onConfirm: () => void }) {
  const title = memoryItemTitle(itemType, item);
  return (
    <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/20 px-4">
      <div role="dialog" aria-modal="true" aria-label={`删除${title}`} className="w-full max-w-[420px] rounded-xl border border-[#e5e5ea] bg-white p-5 shadow-2xl shadow-black/20">
        <div className="flex items-start gap-3">
          <div className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fff0f0] text-[#d93025]"><Trash2 className="h-4 w-4" /></div>
          <div><h3 className="text-[14px] font-medium text-[#1d1d1f]">删除这条{memoryItemTypeLabel(itemType)}？</h3><p className="mt-1.5 text-[12px] leading-5 text-[#636366]">{title}</p><p className="mt-1 text-[11px] leading-5 text-[#8a8a8e]">删除会移除当前机构中的全部版本，并写入审计记录；此操作不可撤销。</p></div>
        </div>
        <div className="mt-5 flex justify-end gap-2"><button type="button" onClick={onCancel} disabled={deleting} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366] disabled:opacity-40">取消</button><button type="button" onClick={onConfirm} disabled={deleting} className="h-9 rounded-lg bg-[#d93025] px-4 text-[12px] text-white disabled:opacity-40">{deleting ? "删除中…" : "确认删除"}</button></div>
      </div>
    </div>
  );
}

const memoryTypeOptions: MemoryItemType[] = ["intent", "knowledge_file", "analysis_experience", "user_behavior_habit"];

function memoryItemTypeForTab(tab: KnowledgeMemoryTab): MemoryItemType {
  if (tab === "files") return "knowledge_file";
  if (tab === "experience") return "analysis_experience";
  return "intent";
}

function memoryItemTypeLabel(itemType: MemoryItemType) {
  return ({ intent: "意图", knowledge_file: "知识文件", analysis_experience: "分析经验", user_behavior_habit: "行为习惯" } as const)[itemType];
}

function memoryTypeOptionLabel(value: string) {
  return memoryTypeOptions.includes(value as MemoryItemType) ? memoryItemTypeLabel(value as MemoryItemType) : value;
}

function memoryItemTitle(itemType: MemoryItemType, item: ManagedMemoryAsset) {
  if (itemType === "intent") { const value = item as IntentAsset; return `${value.scenario} / ${value.purpose}`; }
  if (itemType === "knowledge_file") return (item as KnowledgeFileAsset).title;
  if (itemType === "analysis_experience") { const value = item as AnalysisExperienceAsset; return value.title || value.name; }
  return (item as BehaviorHabitAsset).title;
}

function memoryItemSummary(itemType: MemoryItemType, item: ManagedMemoryAsset) {
  if (itemType === "intent") return (item as IntentAsset).description;
  if (itemType === "knowledge_file") { const value = item as KnowledgeFileAsset; return value.content || `${value.items || 0} 条文本材料 · ${value.tags || "未设置标签"}`; }
  if (itemType === "analysis_experience") { const value = item as AnalysisExperienceAsset; return value.description || value.analysisSteps || value.steps; }
  return (item as BehaviorHabitAsset).description;
}

function memoryItemMeta(itemType: MemoryItemType, item: ManagedMemoryAsset) {
  if (itemType === "intent") { const value = item as IntentAsset; return `关键词：${value.keywords || "未设置"} · 适用：${value.pageScope || "未设置"}`; }
  if (itemType === "knowledge_file") { const value = item as KnowledgeFileAsset; return `维护人：${value.owner || "未设置"} · 更新：${value.updated || "未记录"}`; }
  if (itemType === "analysis_experience") { const value = item as AnalysisExperienceAsset; return `场景：${value.scenario || value.relatedIntent || "未设置"} · 频次/权重：${value.frequency || 1}/${formatWeight(value.weight)}`; }
  const value = item as BehaviorHabitAsset; return `${value.habitType} · 关联机构：${value.relatedOrgs || "未设置"} · 频次/权重：${value.frequency || 1}/${formatWeight(value.weight)}`;
}

function memoryItemStatus(itemType: MemoryItemType, item: ManagedMemoryAsset) {
  if (itemType === "knowledge_file") return (item as KnowledgeFileAsset).coverage || knowledgeMemoryStatus(item);
  return knowledgeMemoryStatus(item);
}

function emptyMemoryDraft(itemType: MemoryItemType): Record<string, unknown> {
  const now = new Date().toISOString();
  if (itemType === "intent") return { id: "", scenario: "", purpose: "", description: "", keywords: "", relatedTopic: "", relatedMetrics: "", relatedExperience: "", pageScope: "智能分析, 经营周报", enabled: true, examples: "" };
  if (itemType === "knowledge_file") return { id: "", title: "", content: "", coverage: "待复核", items: 1, updated: now, owner: "人工维护", tags: "" };
  if (itemType === "analysis_experience") return { id: "", title: "", name: "", description: "", analysisSteps: "", steps: "", scenario: "", relatedMetrics: "", sourceVersionId: "manual", sourceVersionName: "人工维护", evidence: "人工维护", status: "当前有效", frequency: 1, weight: 1, enabled: true, updatedAt: now };
  return { id: "", title: "", habitType: "分析习惯", description: "", behaviorDetail: "", sourceVersionId: "manual", sourceVersionName: "人工维护", evidence: "人工维护", relatedMetrics: "", relatedOrgs: "", firstSeenAt: now, lastSeenAt: now, frequency: 1, weight: 1, status: "当前有效", confidence: 1, updatedAt: now };
}

function validateMemoryDraft(itemType: MemoryItemType, draft: Record<string, unknown>, mode: MemoryEditorMode) {
  const required = (...fields: string[]) => fields.every((field) => String(draft[field] ?? "").trim());
  if (itemType === "intent" && !required("scenario", "purpose", "description", "keywords")) return "请填写场景、目的、记忆内容和关键词。";
  if (itemType === "knowledge_file" && !required("title")) return "请填写知识标题。";
  if (itemType === "knowledge_file" && mode === "create" && !required("content")) return "请填写需要沉淀的记忆内容。";
  if (itemType === "analysis_experience" && !(required("title") || required("name"))) return "请填写经验名称。";
  if (itemType === "analysis_experience" && !(required("steps") || required("analysisSteps"))) return "请填写分析路径。";
  if (itemType === "user_behavior_habit" && !required("title", "description", "sourceVersionId", "evidence")) return "请填写习惯名称、记忆内容、来源版本 ID 和来源证据。";
  return "";
}

function normalizeMemoryDraft(itemType: MemoryItemType, draft: Record<string, unknown>) {
  const now = new Date().toISOString();
  const item = { ...draft };
  if (itemType === "analysis_experience") {
    item.title = String(item.title || item.name || "").trim();
    item.name = item.title;
    item.steps = String(item.steps || item.analysisSteps || "").trim();
    item.analysisSteps = item.steps;
    item.updatedAt = now;
  } else if (itemType === "knowledge_file") {
    item.updated = now;
    item.items = Math.max(1, Number(item.items || 1));
  } else if (itemType === "user_behavior_habit") {
    item.lastSeenAt = now;
    item.updatedAt = now;
    item.frequency = Math.max(1, Number(item.frequency || 1));
    item.weight = Number(item.weight || 1);
  }
  return item;
}

function knowledgeMemoryStatus(item: object): "当前有效" | "历史归档" {
  const candidate = item as { status?: string; lifecycleStatus?: string };
  if (candidate.status === "历史归档" || ["archived", "expired"].includes(String(candidate.lifecycleStatus || ""))) {
    return "历史归档";
  }
  return "当前有效";
}

function sortMemoryItems<T extends object>(
  items: T[],
  sort: "time" | "weight",
) {
  return [...items].sort((a, b) => {
    const left = a as { lastSeenAt?: string; updatedAt?: string; updated?: string; weight?: number };
    const right = b as { lastSeenAt?: string; updatedAt?: string; updated?: string; weight?: number };
    if (sort === "weight") return Number(right.weight || 0) - Number(left.weight || 0);
    return String(right.lastSeenAt || right.updatedAt || right.updated || "").localeCompare(String(left.lastSeenAt || left.updatedAt || left.updated || ""));
  });
}

function formatWeight(value: unknown) {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric) || numeric <= 0) return "0.000";
  return numeric.toFixed(3);
}

function MemoryToolbar({
  sort,
  status,
  onSortChange,
  onStatusChange,
  action,
}: {
  sort: "time" | "weight";
  status: "all" | "当前有效" | "历史归档";
  onSortChange: (value: "time" | "weight") => void;
  onStatusChange: (value: "all" | "当前有效" | "历史归档") => void;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-[#fafbfc] p-2">
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label="记忆排序" value={sort} onChange={(event) => onSortChange(event.target.value as "time" | "weight")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#636366] outline-none">
          <option value="time">按时间倒排</option>
          <option value="weight">按权重排序</option>
        </select>
        <select aria-label="记忆状态" value={status} onChange={(event) => onStatusChange(event.target.value as "all" | "当前有效" | "历史归档")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#636366] outline-none">
          <option value="all">全部状态</option>
          <option value="当前有效">当前有效</option>
          <option value="历史归档">历史归档</option>
        </select>
      </div>
      {action && (
        <button type="button" onClick={action.onClick} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-[#d9d9de] bg-white px-3 text-[11px] font-medium text-[#3a3a3c] hover:bg-[#f2f2f7]" aria-label={action.label}>
          <Plus className="h-3.5 w-3.5" />
          {action.label}
        </button>
      )}
    </div>
  );
}

function SegmentedTabs({
  tabs,
  activeKey,
  onChange,
}: {
  tabs: { key: string; label: string }[];
  activeKey: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="flex shrink-0 flex-nowrap gap-px whitespace-nowrap rounded-lg bg-[#f2f2f7] p-0.5" data-segmented-tabs="true">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-[12px] transition-all ${
            activeKey === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#636366]"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

function AssetMiniField({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-white px-3 py-2">
      <div className="text-[10px] text-[#aeaeb2]">{label}</div>
      <div className="mt-1 truncate text-[11px] text-[#3a3a3c]" title={value}>{value || "未配置"}</div>
    </div>
  );
}

function AssetNotice({ notice }: { notice: string }) {
  if (!notice) return null;
  return (
    <div className="rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[12px] text-[#636366]">
      {notice}
    </div>
  );
}

function EmptyAssetState({ text }: { text: string }) {
  return <div className="rounded-lg bg-[#fafbfc] px-4 py-8 text-center text-[12px] text-[#aeaeb2]">{text}</div>;
}

function assetMatches(item: unknown, keyword: string) {
  if (!keyword) return true;
  return JSON.stringify(item).toLowerCase().includes(keyword);
}

function QualityMonitor({ searchTerm, tenantId, userId }: { searchTerm: string; tenantId: string; userId: string }) {
  const [health, setHealth] = useState<SystemHealthResponse | null>(null);
  const [qualityResults, setQualityResults] = useState<DataQualityResult[]>([]);
  const [qualityJobs, setQualityJobs] = useState<AcquisitionJob[]>([]);
  const [healthLoading, setHealthLoading] = useState(false);
  const [healthError, setHealthError] = useState("");
  const [qualityError, setQualityError] = useState("");
  const qualityMetrics = useMemo(() => buildQualityMetricCards(qualityResults), [qualityResults]);
  const issues = useMemo(
    () =>
      qualityResults
        .filter((item) => item.status !== "passed")
        .map(toQualityIssue)
        .filter((item) => `${item.table} ${item.issue}`.toLowerCase().includes(searchTerm.toLowerCase())),
    [qualityResults, searchTerm],
  );

  const loadHealth = async () => {
    setHealthLoading(true);
    setHealthError("");
    setQualityError("");
    const [healthResult, acquisitionResult] = await Promise.allSettled([
      getSystemHealth(),
      fetchDataAcquisition({ tenantId, userId }),
    ]);
    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value);
    } else {
      setHealth(null);
      setHealthError(apiErrorMessage(healthResult.reason, "运行健康加载失败，请稍后重试。"));
    }
    if (acquisitionResult.status === "fulfilled") {
      setQualityResults(acquisitionResult.value.quality_results || []);
      setQualityJobs(acquisitionResult.value.jobs || []);
    } else {
      setQualityResults([]);
      setQualityJobs([]);
      setQualityError(apiErrorMessage(acquisitionResult.reason, "质量结果加载失败，请稍后重试。"));
    }
    setHealthLoading(false);
  };

  useEffect(() => {
    void loadHealth();
  }, [tenantId, userId]);

  const runtime = health?.runtime;
  const healthOk = health?.ready === true && health.status !== "degraded";
  const healthStatusLabel = health?.ready
    ? health.status === "degraded" ? "降级" : "正常"
    : "不可用";
  const failedHealthChecks = Object.entries(health?.checks || {})
    .filter(([, check]) => check.ready === false)
    .map(([name, check]) => `${name}${check.error ? `(${check.error})` : ""}`);
  const healthCards = [
    {
      label: "服务状态",
      value: health ? healthStatusLabel : healthLoading ? "同步中" : "未连接",
      hint: failedHealthChecks.length ? `未就绪：${failedHealthChecks.join("、")}` : health?.service || "smart-data-agent-api",
    },
    {
      label: "语义层模式",
      value: health ? healthSemanticModeLabel(health.semantic_client_mode) : healthLoading ? "同步中" : "—",
      hint:
        health?.semantic_fallback_mode === "explicit_local"
          ? "显式本地 fallback"
          : health?.semantic_fallback_mode === "disabled"
            ? "远程失败不降级"
            : "本地语义适配",
    },
    {
      label: "数据源模式",
      value: health ? healthDataSourceModeLabel(health.data_source_mode) : healthLoading ? "同步中" : "—",
      hint: health?.route_count ? `统一接口 ${health.route_count} 个` : "统一接口目录",
    },
    {
      label: "最近样本",
      value: runtime ? `${runtime.sample_size} 次` : healthLoading ? "同步中" : "—",
      hint: runtime?.last_seen_at ? `最近 ${formatHealthTime(runtime.last_seen_at)}` : "暂无运行记录",
    },
    {
      label: "错误 / 降级",
      value: runtime ? `${runtime.error_count} / ${runtime.fallback_count}` : healthLoading ? "同步中" : "—",
      hint: "错误请求 / fallback 请求",
    },
    {
      label: "平均耗时",
      value: runtime ? `${Math.round(runtime.avg_latency_ms)} ms` : healthLoading ? "同步中" : "—",
      hint: runtime?.last_latency_ms != null ? `最近 ${runtime.last_latency_ms} ms` : "暂无最近耗时",
    },
  ];

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2">
            <Activity className="w-4 h-4 text-[#aeaeb2]" />
            <div>
              <h3 className="text-[13px] text-[#1d1d1f]">运行健康</h3>
              <p className="mt-0.5 text-[11px] text-[#aeaeb2]">
                来源：后端 /api/health · 分析请求、语义层降级和耗时摘要
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void loadHealth()}
            disabled={healthLoading}
            className="inline-flex h-8 w-fit items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[11px] text-[#636366] transition-colors hover:bg-[#f2f2f7] disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${healthLoading ? "animate-spin" : ""}`} />
            刷新
          </button>
        </div>
        <div data-health-summary-grid="true" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          {healthCards.map((item) => (
            <div key={item.label} className="rounded-lg bg-[#fafbfc] px-4 py-3">
              <div className="text-[11px] text-[#8a8a8e]">{item.label}</div>
              <div className={`mt-1 text-[16px] tracking-tight ${item.label === "服务状态" && !healthOk && health ? "text-[#d93025]" : "text-[#1d1d1f]"}`}>
                {item.value}
              </div>
              <div className="mt-1 truncate text-[10px] text-[#aeaeb2]" title={item.hint}>
                {item.hint}
              </div>
            </div>
          ))}
        </div>
        {healthError && (
          <div className="mt-3 rounded-lg border border-[#ffe3aa] bg-[#fff7e6] px-3 py-2 text-[12px] text-[#8a5a00]">
            运行健康暂不可用；不会用内置数字补位。{healthError}
          </div>
        )}
      </div>

      {qualityError && (
        <div role="alert" className="rounded-lg border border-[#ffe3aa] bg-[#fff7e6] px-3 py-2 text-[12px] text-[#8a5a00]">
          质量结果暂不可用；不会用内置数字补位。{qualityError}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        {qualityMetrics.map((qm) => (
          <div key={qm.metric} className="rounded-xl border border-[#f0f0f2] bg-white p-5">
            <div className="mb-2 text-[12px] text-[#aeaeb2]">{qm.metric}</div>
            <div className="text-[24px] text-[#1d1d1f] tracking-tight">{qm.score === null ? "—" : `${qm.score.toFixed(1)}%`}</div>
            <span className={`text-[11px] ${qm.status === "good" ? "text-[#34a853]" : "text-[#f59e0b]"}`}>
              {qm.trend}
            </span>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4 text-[#aeaeb2]" />
          <h3 className="text-[13px] text-[#1d1d1f]">质量异常</h3>
        </div>
        <div className="space-y-2">
          {issues.map((item) => (
            <div key={item.table} className="flex items-center gap-3 rounded-lg bg-[#fafbfc] p-3.5">
              <span
                className={`h-2 w-2 rounded-full ${
                  item.level === "high" ? "bg-[#ea4335]" : item.level === "medium" ? "bg-[#f59e0b]" : "bg-[#c7c7cc]"
                }`}
              />
              <div className="flex-1">
                <div className="font-mono text-[12px] text-[#1d1d1f]">{item.table}</div>
                <div className="mt-0.5 text-[11px] text-[#8a8a8e]">{item.issue}</div>
              </div>
              <span className="text-[10px] text-[#c7c7cc]">{item.time}</span>
            </div>
          ))}
          {!issues.length && (
            <div className="rounded-lg bg-[#fafbfc] p-8 text-center text-[12px] text-[#aeaeb2]">
              没有匹配的质量异常
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex items-center gap-2">
          <Shield className="w-4 h-4 text-[#aeaeb2]" />
          <h3 className="text-[13px] text-[#1d1d1f]">监控覆盖</h3>
        </div>
        <div className="grid gap-3 md:grid-cols-3">
          {qualityJobs.map((job) => (
            <div key={job.acquisition_job_id} className="rounded-lg bg-[#fafbfc] px-4 py-3">
              <div className="flex items-center gap-2 text-[12px] text-[#636366]">
                <Database className="w-3.5 h-3.5 text-[#aeaeb2]" />
                {job.target_dataset_id}
              </div>
              <div className="mt-1 text-[13px] text-[#1d1d1f]">{job.status === "active" ? "质量规则已接入" : `任务状态：${job.status}`}</div>
            </div>
          ))}
          {!qualityJobs.length && (
            <div className="rounded-lg bg-[#fafbfc] px-4 py-6 text-center text-[12px] text-[#aeaeb2] md:col-span-3">
              暂无已配置的数据获取任务，不能声称任何数据表已被质量监控覆盖
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function buildQualityMetricCards(results: DataQualityResult[]) {
  const definitions = [
    { key: "completeness", metric: "数据完整性" },
    { key: "accuracy", metric: "数据准确性" },
    { key: "freshness", metric: "数据时效性" },
    { key: "consistency", metric: "口径一致性" },
  ];
  return definitions.map(({ key, metric }) => {
    const group = results.filter((result) => qualityCategory(result.rule_code) === key);
    if (!group.length) return { metric, score: null, trend: "暂无真实质量评估", status: "warning" };
    const score = (group.reduce((total, item) => total + Number(item.score || 0), 0) / group.length) * 100;
    const prior = group.length > 1
      ? (group.slice(1).reduce((total, item) => total + Number(item.score || 0), 0) / (group.length - 1)) * 100
      : null;
    const delta = prior === null ? null : score - prior;
    return {
      metric,
      score,
      trend: delta === null ? "暂无可比评估" : `${delta >= 0 ? "+" : ""}${delta.toFixed(1)}pp 较上一评估`,
      status: score >= 95 ? "good" : "warning",
    };
  });
}

function healthSemanticModeLabel(mode: string) {
  if (mode === "http") return "远程";
  if (mode === "local") return "本地";
  return mode || "未配置";
}

function healthDataSourceModeLabel(mode?: string) {
  if (mode === "json_mock_warehouse") return "JSON Mock";
  if (mode === "csv_folder") return "CSV 文件夹";
  if (mode === "production_data_source_not_configured") return "未配置";
  if (mode === "local") return "本地";
  return mode || "未配置";
}

function qualityCategory(ruleCode: string) {
  const normalized = ruleCode.toLowerCase();
  if (/(fresh|stale|watermark|timeliness)/.test(normalized)) return "freshness";
  if (/(null|required|row_count|complete)/.test(normalized)) return "completeness";
  if (/(unique|duplicate|range|format|accuracy)/.test(normalized)) return "accuracy";
  return "consistency";
}

function toQualityIssue(item: DataQualityResult): { table: string; issue: string; level: "high" | "medium" | "low"; time: string } {
  const observed = compactQualityValue(item.observed_value);
  const threshold = compactQualityValue(item.threshold_value);
  return {
    table: item.target_dataset_id || item.acquisition_run_id,
    issue: `${item.rule_code}：${item.status}${observed ? `；观测 ${observed}` : ""}${threshold ? `；阈值 ${threshold}` : ""}`,
    level: item.blocking || item.status === "failed" || item.status === "error" ? "high" : "medium",
    time: formatHealthTime(item.evaluated_at),
  };
}

function compactQualityValue(value: Record<string, unknown>) {
  const text = JSON.stringify(value || {});
  return text === "{}" ? "" : text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

function formatHealthTime(value: string) {
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
