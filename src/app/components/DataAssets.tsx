import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { useLocation } from "react-router";
import {
  AlertTriangle,
  Activity,
  BookOpen,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Database,
  FilePlus2,
  Layers3,
  Pencil,
  Plus,
  RefreshCw,
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
import { usePlatformContext } from "../platform/PlatformContext";
import { fetchAccessRolePolicies, type AccessRoleConfig } from "../services/accessControlApi";
import {
  deleteMetricDictionaryItem,
  fetchMetricDictionary,
  importMetricDictionaryWorkbook,
  saveMetricDictionaryItem,
} from "../services/metricDictionaryApi";
import { getSystemHealth, type SystemHealthResponse } from "../services/systemHealthApi";
import {
  fetchDataAcquisition,
  type AcquisitionJob,
  type DataQualityResult,
} from "../services/dataAcquisitionApi";
import { apiErrorMessage } from "../services/apiClient";
import { demoFallbackDisabledMessage, isDemoFallbackEnabled } from "../services/apiContext";
import {
  deleteDataAssetItem,
  fetchDataAssets,
  fetchTopicData,
  type AnalysisExperienceAsset,
  type BehaviorHabitAsset,
  type DataAssetBundle,
  type IntentAsset,
  type KnowledgeFileAsset,
  type RawTableAsset,
  type RawField,
  type TopicTableAsset,
  type TopicDataSnapshot,
  saveDataAssetItem,
  uploadRawDataFile,
} from "../services/dataAssetApi";

type DataAssetSection = "metrics" | "knowledge" | "data-management" | "quality";
type DataManagementTab = "raw" | "topic";
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
    title: "数据管理",
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
    ? `原始表仅读取当前机构 /app/data/${selectedInstitution}/ 中的 CSV；主题表和分析结果统一复用 Topic_Data 中的最新数据资产`
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
      setMetricNotice("指标已存在，请检查……");
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
      setMetricNotice(result.skipped_count
        ? `已新增 ${result.created_count} 条指标，跳过 ${result.skipped_count} 条重名指标；原指标未被覆盖。`
        : `已新增 ${result.created_count} 条指标，原指标未被覆盖。`);
      setMetricImportOpen(false);
      setMetricImportFile(null);
      setMetricImportNotice("");
    } catch (error) {
      setMetricImportNotice(`${demoFallbackDisabledMessage("批量导入指标")} ${apiErrorMessage(error, "未知错误")}`);
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
            {section === "metrics" && (
              <span className="rounded-full border border-[#e5e5ea] bg-white px-2 py-0.5 text-[11px] text-[#8a8a8e]">
                指标字典
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
          notice={metricEditorOpen ? "" : metricNotice}
          tenantId={tenantId}
          institutionName={selectedInstitution}
          dataSource={metricDataSource}
          onEdit={openMetricEditor}
          onDelete={deleteMetric}
          canEditMetric={(metric) => canEditMetric(metric, { isSuperAdmin, tenantId, userId })}
          canDeleteMetric={(metric) => canEditMetric(metric, { isSuperAdmin, tenantId, userId })}
        />
      )}

      {section === "knowledge" && <KnowledgeMemory searchTerm={searchTerm} tenantId={tenantId} userId={userId} />}

      {section === "data-management" && <DataManagement searchTerm={searchTerm} tenantId={tenantId} />}

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
      {notice && (
        <div className="rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[12px] text-[#258a3f]">
          {notice}
        </div>
      )}

      <div className="rounded-xl border border-[#f0f0f2] bg-white overflow-hidden">
        <div className="flex flex-col gap-2 border-b border-[#f0f0f2] px-4 py-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="text-[13px] text-[#1d1d1f]">指标全集</div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={page}
              onChange={(event) => onPageChange(Number(event.target.value))}
              className="h-7 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#636366] outline-none hover:bg-[#f8f8f8] focus:border-[#c7c7cc]"
              aria-label="指标分页"
            >
              {Array.from({ length: pageCount }, (_, index) => (
                <option key={index + 1} value={index + 1}>
                  第 {index + 1} 页 / 共 {pageCount} 页
                </option>
              ))}
            </select>
            <span className="text-[11px] text-[#8a8a8e]">
              {filteredMetrics.length} / {metrics.length} 条
            </span>
          </div>
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
            <p className="mt-0.5 text-[11px] text-[#8a8a8e]">上传标准 Excel 后新增指标；同名指标将跳过，绝不覆盖原指标。</p>
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
            <span>✓ 规则：重复名称跳过，已有指标不改动</span>
          </div>
          {notice && <div className="rounded-lg bg-[#fafbfc] px-3 py-2 text-[12px] leading-[1.6] text-[#636366]">{notice}</div>}
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
      count: {},
};

function useDataAssetBundle(tenantId: string, scope?: "knowledge") {
  const [bundle, setBundle] = useState<DataAssetBundle>(emptyAssetBundle);
  const [notice, setNotice] = useState("资产配置同步中...");

  useEffect(() => {
    let cancelled = false;
    let retryTimer: number | undefined;
    const syncAssets = async () => {
      setNotice("资产配置同步中...");
      try {
        const response = await fetchDataAssets({ tenantId, scope });
        if (response.status === "loading") {
          if (!cancelled) {
            setNotice(response.message || "当前机构 Data Crawler 原始数据正在准备中，请稍候...");
            retryTimer = window.setTimeout(() => void syncAssets(), 700);
          }
          return;
        }
        if (!cancelled) {
          setBundle(response);
          setNotice(`已连接后端资产配置 · 原始表 ${response.raw_tables.length} 张 · 主题表 ${response.topic_tables.length} 个`);
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
  }, [tenantId, scope]);

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

  const removeTable = (itemType: "raw_table" | "topic_table", itemId: string) => {
    setBundle((current) => itemType === "raw_table"
      ? { ...current, raw_tables: current.raw_tables.filter((item) => item.id !== itemId) }
      : { ...current, topic_tables: current.topic_tables.filter((item) => item.id !== itemId) });
  };

  return { bundle, notice, upsertRawTable, upsertTopicTable, removeTable, setNotice };
}

function DataManagement({ searchTerm, tenantId }: { searchTerm: string; tenantId: string }) {
  const [activeTab, setActiveTab] = useState<DataManagementTab>("raw");
  const [rawPage, setRawPage] = useState(1);
  const [topicPage, setTopicPage] = useState(1);
  const [createType, setCreateType] = useState<DataManagementTab | null>(null);
  const [pendingDelete, setPendingDelete] = useState<{ itemType: "raw_table" | "topic_table"; item: RawTableAsset | TopicTableAsset } | null>(null);
  const [deleting, setDeleting] = useState(false);
  const { bundle, notice, upsertTopicTable, removeTable, setNotice } = useDataAssetBundle(tenantId);
  const keyword = searchTerm.trim().toLowerCase();
  const rawTables = bundle.raw_tables.filter((item) => assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const topicTables = bundle.topic_tables.filter((item) => assetMatches(item, keyword)).sort(sortAssetNewestFirst);
  const rawPageCount = Math.max(1, Math.ceil(rawTables.length / dataTablePageSize));
  const topicPageCount = Math.max(1, Math.ceil(topicTables.length / dataTablePageSize));
  const pagedRawTables = rawTables.slice((Math.min(rawPage, rawPageCount) - 1) * dataTablePageSize, Math.min(rawPage, rawPageCount) * dataTablePageSize);
  const pagedTopicTables = topicTables.slice((Math.min(topicPage, topicPageCount) - 1) * dataTablePageSize, Math.min(topicPage, topicPageCount) * dataTablePageSize);
  const currentPage = activeTab === "raw" ? Math.min(rawPage, rawPageCount) : Math.min(topicPage, topicPageCount);
  const currentPageCount = activeTab === "raw" ? rawPageCount : topicPageCount;
  const currentTotal = activeTab === "raw" ? rawTables.length : topicTables.length;
  const setCurrentPage = activeTab === "raw" ? setRawPage : setTopicPage;

  useEffect(() => {
    setRawPage(1);
    setTopicPage(1);
  }, [activeTab, keyword, tenantId]);

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
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">数据管理</h3>
            <p className="mt-1 text-[11px] text-[#aeaeb2]">原始表自动读取 CSV 文件并展示前 10 行和字段解读；主题表保存可复用分析 SQL。</p>
          </div>
          <div className="flex items-center gap-2">
            {(rawTables.length > dataTablePageSize || topicTables.length > dataTablePageSize) && (
              <DataTablePagination
                compact
                page={currentPage}
                totalPages={currentPageCount}
                total={currentTotal}
                onChange={setCurrentPage}
              />
            )}
            {activeTab === "topic" && (
              <button
                type="button"
                aria-label="新增主题表"
                onClick={() => setCreateType("topic")}
                className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e]"
              >
                <Plus className="h-3.5 w-3.5" />
                新增主题表
              </button>
            )}
            <SegmentedTabs
              tabs={[
                { key: "raw", label: `原始表 ${rawTables.length}` },
                { key: "topic", label: `主题表 ${topicTables.length}` },
              ]}
              activeKey={activeTab}
              onChange={(key) => setActiveTab(key as DataManagementTab)}
            />
          </div>
        </div>

        {activeTab === "raw" ? (
          <div className="space-y-3">
            {pagedRawTables.map((table) => (
              <RawTableCard
                key={table.id}
                table={table}
              />
            ))}
            {!rawTables.length && <EmptyAssetState text="暂无匹配的原始表配置" />}
          </div>
        ) : (
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
        )}
      </div>
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
  return (
    <div className={`flex items-center gap-2 text-[11px] text-[#8a8a8e] ${compact ? "shrink-0" : "flex-wrap justify-between border-t border-[#f0f0f2] pt-3"}`}>
      <span className={compact ? "hidden xl:inline" : ""}>共 {total} 条，每页 {dataTablePageSize} 条</span>
      <div className="flex items-center gap-2">
        <button type="button" aria-label="上一页" disabled={page <= 1} onClick={() => onChange(page - 1)} className="rounded-md border border-[#e5e5ea] bg-white px-2.5 py-1 hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:opacity-40">上一页</button>
        <span>{page} / {totalPages}</span>
        <button type="button" aria-label="下一页" disabled={page >= totalPages} onClick={() => onChange(page + 1)} className="rounded-md border border-[#e5e5ea] bg-white px-2.5 py-1 hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:opacity-40">下一页</button>
      </div>
    </div>
  );
}

function sortAssetNewestFirst(
  left: Pick<RawTableAsset, "id" | "updatedAt"> | Pick<TopicTableAsset, "id" | "updatedAt">,
  right: Pick<RawTableAsset, "id" | "updatedAt"> | Pick<TopicTableAsset, "id" | "updatedAt">,
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
    fields: [emptyRawField()],
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
    fields: [emptyRawField()],
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
  const fields = headers.map((header, index) => {
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
  const fieldByHeader = (pattern: RegExp) => fields[headers.findIndex((header) => pattern.test(header))]?.fieldNameEn || "";
  return {
    tableNameEn: normalizeTableIdentifier(nameWithoutExtension),
    tableNameCn: nameWithoutExtension,
    primaryKey: fieldByHeader(/(^id$|_id$|编号|主键)/i),
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

  const updateField = (index: number, key: keyof RawField, value: string) => {
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
              <div className="min-w-[820px]">
                <div className="grid grid-cols-[1fr_1fr_0.75fr_1.35fr_1.2fr_36px] gap-2 bg-[#fafbfc] px-3 py-2 text-[10px] text-[#8a8a8e]">
                  <span>字段英文 *</span><span>字段中文</span><span>类型 *</span><span>语义解释</span><span>示例用法</span><span />
                </div>
                {fields.map((field, index) => (
                  <div key={index} className="grid grid-cols-[1fr_1fr_0.75fr_1.35fr_1.2fr_36px] gap-2 border-t border-[#f8f8f8] p-3">
                    <input aria-label={`字段${index + 1}英文名`} value={field.fieldNameEn} onChange={(event) => updateField(index, "fieldNameEn", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <input aria-label={`字段${index + 1}中文名`} value={field.fieldNameCn} onChange={(event) => updateField(index, "fieldNameCn", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                    <select aria-label={`字段${index + 1}类型`} value={field.type} onChange={(event) => updateField(index, "type", event.target.value)} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]">
                      {["string", "integer", "decimal", "date", "datetime", "boolean"].map((type) => <option key={type} value={type}>{type}</option>)}
                    </select>
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
              {protectedAsset ? "该主题表是系统内置资产，关联经营周报和智能分析，不能删除。" : "确认后将从数据管理列表和后端资产配置中删除，操作不可撤销。"}
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

function KnowledgeMemory({ searchTerm, tenantId, userId }: { searchTerm: string; tenantId: string; userId: string }) {
  const [activeTab, setActiveTab] = useState<KnowledgeMemoryTab>("all");
  const [memorySort, setMemorySort] = useState<"time" | "weight">("time");
  const [memoryStatus, setMemoryStatus] = useState<"all" | "当前有效" | "历史归档">("all");
  const { bundle, notice } = useDataAssetBundle(tenantId, "knowledge");
  const keyword = searchTerm.trim().toLowerCase();
  const [localExperiences, setLocalExperiences] = useState<AnalysisExperienceAsset[]>([]);

  useEffect(() => {
    setLocalExperiences(bundle.analysis_experiences);
  }, [bundle.analysis_experiences]);

  const matchesMemory = (item: object) =>
    assetMatches(item, keyword) && (memoryStatus === "all" || knowledgeMemoryStatus(item) === memoryStatus);
  const intents = sortMemoryItems(bundle.intents.filter(matchesMemory), memorySort);
  const files = sortMemoryItems(bundle.knowledge_files.filter(matchesMemory), memorySort);
  const experiences = sortMemoryItems(localExperiences.filter(matchesMemory), memorySort);
  const allKnowledgeCount = intents.length + files.length + experiences.length;

  const archiveExperience = async (experience: AnalysisExperienceAsset) => {
    const next = { ...experience, status: "历史归档", enabled: false, updatedAt: new Date().toISOString().slice(0, 10) };
    setLocalExperiences((current) => current.map((item) => (item.id === experience.id ? next : item)));
    try {
      await saveDataAssetItem({ tenantId, userId, itemType: "analysis_experience", item: next });
    } catch {
      setLocalExperiences(bundle.analysis_experiences);
    }
  };

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
        <MemoryToolbar sort={memorySort} status={memoryStatus} onSortChange={setMemorySort} onStatusChange={setMemoryStatus} />

        {notice === "资产配置同步中..." && <div className="mt-4 rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-4 py-5 text-[12px] text-[#8a8a8e]">正在加载知识记忆…</div>}

        {notice !== "资产配置同步中..." && activeTab === "all" && (
          <div className="mt-4 space-y-5" data-knowledge-memory-all>
            {!allKnowledgeCount && <EmptyAssetState text="暂无匹配的知识类记忆" />}
            {intents.length > 0 && (
              <KnowledgeMemoryGroup title="意图管理" count={intents.length}>
                <div className="space-y-3">{intents.map((intent) => <IntentCard key={intent.id} intent={intent} />)}</div>
              </KnowledgeMemoryGroup>
            )}
            {files.length > 0 && (
              <KnowledgeMemoryGroup title="知识文件" count={files.length}>
                <div className="space-y-2.5">{files.map((item) => <KnowledgeFileRow key={item.id} item={item} />)}</div>
              </KnowledgeMemoryGroup>
            )}
            {experiences.length > 0 && (
              <KnowledgeMemoryGroup title="分析经验" count={experiences.length}>
                <div className="space-y-3">{experiences.map((experience) => <ExperienceCard key={experience.id} experience={experience} onArchive={archiveExperience} />)}</div>
              </KnowledgeMemoryGroup>
            )}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "intent" && (
          <div className="mt-4 space-y-3">
            {intents.map((intent) => <IntentCard key={intent.id} intent={intent} />)}
            {!intents.length && <EmptyAssetState text="暂无匹配的意图配置" />}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "files" && (
          <div className="mt-4 space-y-2.5">
            {files.map((item) => <KnowledgeFileRow key={item.id} item={item} />)}
            {!files.length && <EmptyAssetState text="暂无匹配的知识文件" />}
          </div>
        )}
        {notice !== "资产配置同步中..." && activeTab === "experience" && (
          <div className="mt-4 space-y-3">
            {experiences.map((experience) => <ExperienceCard key={experience.id} experience={experience} onArchive={archiveExperience} />)}
            {!experiences.length && <EmptyAssetState text="暂无匹配的分析经验" />}
          </div>
        )}
      </div>
      <BehaviorHabits searchTerm={searchTerm} tenantId={tenantId} userId={userId} bundle={bundle} loading={notice === "资产配置同步中..."} />
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

function BehaviorHabits({ searchTerm, tenantId, userId, bundle, loading }: { searchTerm: string; tenantId: string; userId: string; bundle: DataAssetBundle; loading: boolean }) {
  const [activeType, setActiveType] = useState<"all" | "分析习惯" | "运营习惯" | "汇报习惯">("all");
  const [sort, setSort] = useState<"time" | "weight">("time");
  const [status, setStatus] = useState<"all" | "当前有效" | "历史归档">("all");
  const [habits, setHabits] = useState<BehaviorHabitAsset[]>([]);
  const keyword = searchTerm.trim().toLowerCase();

  useEffect(() => {
    setHabits(bundle.behavior_habits || []);
  }, [bundle.behavior_habits]);

  const shownHabits = sortMemoryItems(
    habits
      .filter((habit) => assetMatches(habit, keyword))
      .filter((habit) => activeType === "all" || habit.habitType === activeType)
      .filter((habit) => status === "all" || (habit.status || "当前有效") === status),
    sort,
  );

  const archiveHabit = async (habit: BehaviorHabitAsset) => {
    const next = { ...habit, status: "历史归档", updatedAt: new Date().toISOString().slice(0, 10) };
    setHabits((current) => current.map((item) => (item.id === habit.id ? next : item)));
    try {
      await saveDataAssetItem({ tenantId, userId, itemType: "user_behavior_habit", item: next });
    } catch {
      setHabits(bundle.behavior_habits || []);
    }
  };

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
        <MemoryToolbar sort={sort} status={status} onSortChange={setSort} onStatusChange={setStatus} />
        <div className="mt-3 space-y-3">
          {loading && <div className="rounded-lg border border-[#e5e5ea] bg-[#fafbfc] px-4 py-5 text-[12px] text-[#8a8a8e]">正在加载行为习惯…</div>}
          {shownHabits.map((habit) => (
            <BehaviorHabitCard key={habit.id} habit={habit} onArchive={archiveHabit} />
          ))}
          {!shownHabits.length && <EmptyAssetState text="暂无匹配的用户行为习惯，保存经营周报版本后会自动生成。" />}
        </div>
      </div>
    </div>
  );
}

function RawTableCard({
  table,
}: {
  table: RawTableAsset;
}) {
  const [expanded, setExpanded] = useState(false);
  const [activeDetailTab, setActiveDetailTab] = useState<"preview" | "metadata">("preview");
  const previewHeaders = Object.keys(table.previewRows?.[0] || {}).length
    ? Object.keys(table.previewRows?.[0] || {})
    : table.fields.map((field) => field.fieldNameCn || field.fieldNameEn);

  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className={`${expanded ? "mb-3" : ""} flex flex-wrap items-start justify-between gap-3`}>
        <div>
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-[#8a8a8e]" />
            <h4 className="text-[13px] text-[#1d1d1f]">{table.tableNameCn}</h4>
            <span className="font-mono text-[11px] text-[#8a8a8e]">{table.tableNameEn}</span>
            {table.fileName && <span className="max-w-[280px] truncate rounded-full border border-[#e5e5ea] bg-white px-2 py-0.5 text-[10px] text-[#636366]" title={table.fileName}>文件：{table.fileName}</span>}
          </div>
          <p className="mt-1 text-[11px] leading-[1.6] text-[#636366]">更新时间：{formatAssetTime(table.updatedAt)}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-7 rounded-md border border-[#e5e5ea] bg-white px-2 py-1 text-[11px] text-[#636366]">
            CSV 文件 · {table.rowCount ?? 0} 行
          </span>
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
          </div>
          {activeDetailTab === "preview" ? (
            <div className="max-h-[360px] overflow-auto">
              <table className="min-w-full text-left text-[11px]">
                <thead className="sticky top-0 bg-white text-[#8a8a8e]">
                  <tr>{previewHeaders.map((header) => <th key={header} className="whitespace-nowrap border-b border-[#f0f0f2] px-3 py-2 font-normal">{header}</th>)}</tr>
                </thead>
                <tbody>
                  {(table.previewRows || []).map((row, rowIndex) => <tr key={rowIndex} className="border-b border-[#f8f8f8] last:border-b-0">{previewHeaders.map((header) => <td key={header} className="max-w-[280px] truncate px-3 py-2 text-[#3a3a3c]" title={row[header] || ""}>{row[header] || ""}</td>)}</tr>)}
                </tbody>
              </table>
              {!table.previewRows?.length && <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">文件没有可展示的数据行</div>}
            </div>
          ) : (
            <AssetFieldTable fields={table.fields} editing={false} onChange={() => undefined} />
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
      className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-[#e5e5ea] bg-white text-[#636366] hover:bg-[#f2f2f7]"
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
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#636366] hover:bg-[#f2f2f7]"
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
        className="inline-flex h-7 items-center gap-1.5 rounded-md bg-[#1d1d1f] px-2 text-[11px] text-white hover:bg-[#2c2c2e] disabled:opacity-50"
      >
        <Save className="h-3.5 w-3.5" />
        保存
      </button>
      <button
        type="button"
        onClick={onCancel}
        disabled={saving}
        className="inline-flex h-7 items-center gap-1.5 rounded-md border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50"
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
  onChange: (index: number, key: "explanation" | "exampleUsage", value: string) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-[#f0f0f2] bg-white">
      <div className="grid grid-cols-[1fr_1fr_0.7fr_1.7fr_1.5fr] bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
        <span>字段英文</span>
        <span>字段中文</span>
        <span>类型</span>
        <span>语义解释</span>
        <span>示例用法</span>
      </div>
      {fields.map((field, index) => (
        <div key={`${field.fieldNameEn}_${index}`} className="grid grid-cols-[1fr_1fr_0.7fr_1.7fr_1.5fr] border-t border-[#f8f8f8] px-3 py-2 text-[11px]">
          <span className="font-mono text-[#3a3a3c]">{field.fieldNameEn}</span>
          <span className="text-[#1d1d1f]">{field.fieldNameCn}</span>
          <span className="text-[#8a8a8e]">{field.type}</span>
          {editing ? (
            <>
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
  if (Array.isArray(topic.fields)) return topic.fields;
  const fieldNames = String(topic.fields || "")
    .split(/[,\uFF0C、]/)
    .map((field) => field.trim())
    .filter(Boolean);
  const explanations = String(topic.fieldExplanations || "")
    .split(/[,\uFF0C、]/)
    .map((field) => field.trim());
  return fieldNames.map((fieldName, index) => ({
    fieldNameEn: fieldName,
    fieldNameCn: explanations[index] || fieldName,
    type: inferFieldType(fieldName),
    explanation: explanations[index] || "待补充字段语义解释。",
    exampleUsage: "智能分析、经营周报、主题表复用",
  }));
}

function inferFieldType(fieldName: string) {
  if (/date|time|日期|时间/i.test(fieldName)) return "date";
  if (/amount|balance|rate|count|num|金额|余额|率|数/i.test(fieldName)) return "decimal";
  return "string";
}

function IntentCard({ intent }: { intent: IntentAsset }) {
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${intent.enabled ? "bg-[#34a853]" : "bg-[#c7c7cc]"}`} />
        <h4 className="text-[13px] text-[#1d1d1f]">{intent.scenario} / {intent.purpose}</h4>
        <span className="rounded-full border border-[#e5e5ea] bg-white px-2 py-0.5 text-[10px] text-[#8a8a8e]">{intent.pageScope}</span>
      </div>
      <p className="text-[12px] leading-[1.7] text-[#636366]">{intent.description}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <AssetMiniField label="关键词" value={intent.keywords} />
        <AssetMiniField label="关联主题" value={intent.relatedTopic} />
        <AssetMiniField label="关联指标" value={intent.relatedMetrics} />
      </div>
      <div className="mt-3 rounded-lg bg-white px-3 py-2 text-[11px] text-[#636366]">示例问题：{intent.examples}</div>
    </div>
  );
}

function KnowledgeFileRow({ item }: { item: KnowledgeFileAsset }) {
  return (
    <div className="flex cursor-pointer items-center gap-4 rounded-lg bg-[#fafbfc] p-4 transition-colors hover:bg-[#f2f2f7]">
      <div className={`h-2 w-2 rounded-full ${item.coverage === "已启用" ? "bg-[#34a853]" : "bg-[#f59e0b]"}`} />
      <div className="flex-1">
        <div className="text-[13px] text-[#1d1d1f]">{item.title}</div>
        <div className="mt-0.5 text-[11px] text-[#c7c7cc]">
          {item.items} 条文本材料 · 更新 {item.updated} · {item.tags}
        </div>
      </div>
      <div className="text-right">
        <div className="text-[13px] text-[#1d1d1f]">{item.coverage}</div>
        <div className="text-[10px] text-[#c7c7cc]">{item.owner}</div>
      </div>
      <ChevronRight className="w-4 h-4 text-[#d1d1d6]" />
    </div>
  );
}

function ExperienceCard({ experience, onArchive }: { experience: AnalysisExperienceAsset; onArchive: (experience: AnalysisExperienceAsset) => void }) {
  const title = experience.title || experience.name;
  const steps = experience.analysisSteps || experience.steps;
  const metrics = experience.relatedMetrics || experience.metrics;
  const status = experience.status || "当前有效";
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Sparkles className="h-4 w-4 text-[#8a8a8e]" />
          <h4 className="text-[13px] text-[#1d1d1f]">{title}</h4>
          <span className={`rounded-full px-2 py-0.5 text-[10px] ${status === "当前有效" ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`}>
            {status}
          </span>
        </div>
        {status !== "历史归档" && (
          <button onClick={() => onArchive(experience)} className="text-[11px] text-[#8a8a8e] hover:text-[#1d1d1f]">
            标记归档
          </button>
        )}
      </div>
      <p className="text-[12px] leading-[1.7] text-[#636366]">{experience.description || steps}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <AssetMiniField label="适用场景" value={experience.scenario || experience.relatedIntent} />
        <AssetMiniField label="关联指标" value={metrics} />
        <AssetMiniField label="来源版本" value={experience.sourceVersionName || experience.sourceVersionId || "历史经验"} />
        <AssetMiniField label="频次 / 权重" value={`${experience.frequency || 1} 次 / ${formatWeight(experience.weight)}`} />
      </div>
      <div className="mt-3 rounded-lg bg-white p-3 text-[11px] leading-[1.6] text-[#636366]">
        分析路径：{steps || "未记录"}
        <br />
        来源证据：{experience.evidence || experience.commonConclusions || "未记录"}
      </div>
    </div>
  );
}

function BehaviorHabitCard({ habit, onArchive }: { habit: BehaviorHabitAsset; onArchive: (habit: BehaviorHabitAsset) => void }) {
  const status = habit.status || "当前有效";
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <Activity className="h-4 w-4 text-[#8a8a8e]" />
          <h4 className="text-[13px] text-[#1d1d1f]">{habit.title}</h4>
          <span className="rounded-full border border-[#e5e5ea] bg-white px-2 py-0.5 text-[10px] text-[#636366]">
            {habit.habitType}
          </span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] ${status === "当前有效" ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`}>
            {status}
          </span>
        </div>
        {status !== "历史归档" && (
          <button onClick={() => onArchive(habit)} className="text-[11px] text-[#8a8a8e] hover:text-[#1d1d1f]">
            标记归档
          </button>
        )}
      </div>
      <p className="text-[12px] leading-[1.7] text-[#636366]">{habit.description}</p>
      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <AssetMiniField label="关联指标" value={habit.relatedMetrics} />
        <AssetMiniField label="关联机构" value={habit.relatedOrgs} />
        <AssetMiniField label="来源版本" value={habit.sourceVersionName || habit.sourceVersionId} />
        <AssetMiniField label="频次 / 权重" value={`${habit.frequency || 1} 次 / ${formatWeight(habit.weight)}`} />
      </div>
      <div className="mt-3 rounded-lg bg-white p-3 text-[11px] leading-[1.6] text-[#636366]">
        具体表现：{habit.behaviorDetail || "未记录"}
        <br />
        来源证据：{habit.evidence || "未记录"}
      </div>
    </div>
  );
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
}: {
  sort: "time" | "weight";
  status: "all" | "当前有效" | "历史归档";
  onSortChange: (value: "time" | "weight") => void;
  onStatusChange: (value: "all" | "当前有效" | "历史归档") => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-[#fafbfc] p-2">
      <select value={sort} onChange={(event) => onSortChange(event.target.value as "time" | "weight")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#636366] outline-none">
        <option value="time">按时间倒排</option>
        <option value="weight">按权重排序</option>
      </select>
      <select value={status} onChange={(event) => onStatusChange(event.target.value as "all" | "当前有效" | "历史归档")} className="h-8 rounded-md border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#636366] outline-none">
        <option value="all">全部状态</option>
        <option value="当前有效">当前有效</option>
        <option value="历史归档">历史归档</option>
      </select>
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
    <div className="flex gap-px rounded-lg bg-[#f2f2f7] p-0.5">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`rounded-md px-3 py-1.5 text-[12px] transition-all ${
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
    try {
      const [healthResponse, acquisition] = await Promise.all([
        getSystemHealth(),
        fetchDataAcquisition({ tenantId, userId }),
      ]);
      setHealth(healthResponse);
      setQualityResults(acquisition.quality_results || []);
      setQualityJobs(acquisition.jobs || []);
    } catch (error) {
      setQualityResults([]);
      setQualityJobs([]);
      setHealthError(error instanceof Error ? error.message : "运行健康暂不可用");
    } finally {
      setHealthLoading(false);
    }
  };

  useEffect(() => {
    void loadHealth();
  }, [tenantId, userId]);

  const runtime = health?.runtime;
  const healthOk = health?.ready === true && runtime?.last_status !== "error";
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
      value: health?.semantic_client_mode === "http" ? "远程" : health?.semantic_client_mode || "本地",
      hint:
        health?.semantic_fallback_mode === "explicit_local"
          ? "显式本地 fallback"
          : health?.semantic_fallback_mode === "disabled"
            ? "远程失败不降级"
            : "本地语义适配",
    },
    {
      label: "数据源模式",
      value: health?.data_source_mode === "json_mock_warehouse" ? "JSON Mock" : health?.data_source_mode || "本地",
      hint: health?.route_count ? `统一接口 ${health.route_count} 个` : "统一接口目录",
    },
    {
      label: "最近样本",
      value: runtime ? `${runtime.sample_size} 次` : "0 次",
      hint: runtime?.last_seen_at ? `最近 ${formatHealthTime(runtime.last_seen_at)}` : "暂无运行记录",
    },
    {
      label: "错误 / 降级",
      value: runtime ? `${runtime.error_count} / ${runtime.fallback_count}` : "0 / 0",
      hint: "错误请求 / fallback 请求",
    },
    {
      label: "平均耗时",
      value: runtime ? `${runtime.avg_latency_ms} ms` : "0 ms",
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
        <div className="grid gap-3 lg:grid-cols-5">
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
            运行健康或质量结果暂不可用；不会用内置数字补位。{healthError}
          </div>
        )}
      </div>

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
