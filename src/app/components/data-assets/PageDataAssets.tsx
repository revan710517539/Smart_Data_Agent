import { memo, useEffect, useMemo, useState, type ReactNode } from "react";
import { LayoutDashboard, Pencil, Plus, Trash2, X } from "lucide-react";
import type {
  MultiInstitutionPageDataCandidate,
  PageDataAsset,
  PageDataInstitutionScope,
  PageDataPageCode,
  RawField,
  RawTableAsset,
} from "../../services/dataAssetApi";
import { normalizeFieldSemantics } from "../../data/fieldSemantics";
import { visualizationOptions, type VisualizationType } from "../self-analysis/domain";
import { singleInstitutionAssignedPage } from "../page-data/assignment";

const pageOptions: Array<{ code: PageDataPageCode; label: string }> = [
  { code: "weekly_report", label: "经营周报" },
  { code: "institution_supervision", label: "机构督导" },
];

export function PageDataAssetList({
  assets,
  keyword,
  scope,
  canManage = true,
  onDelete,
  onEdit,
  onPageChange,
}: {
  assets: PageDataAsset[];
  keyword: string;
  scope: PageDataInstitutionScope;
  canManage?: boolean;
  onDelete: (asset: PageDataAsset) => Promise<void>;
  onEdit: (asset: PageDataAsset) => void;
  onPageChange: (asset: PageDataAsset, page: Extract<PageDataPageCode, "weekly_report" | "institution_supervision">) => Promise<void>;
}) {
  const normalizedKeyword = keyword.trim().toLowerCase();
  const visibleAssets = assets.filter((asset) => !normalizedKeyword || [
    asset.name,
    asset.sourceTableName,
    ...asset.metricFields,
    ...asset.dimensionFields,
  ].join(" ").toLowerCase().includes(normalizedKeyword));
  return <>
    <div className="space-y-3" data-page-data-list="true">
      {visibleAssets.map((asset) => (
        <article key={asset.id} className="flex min-h-[78px] items-center gap-4 rounded-xl border border-[#edf1ee] bg-[#fafcfb] px-4 py-3" data-page-data-item={asset.id}>
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-white text-[#6d7d74]"><LayoutDashboard className="h-4 w-4" /></div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h4 className="truncate text-[13px] text-[#1d1d1f]">{asset.name}</h4>
              <span className="rounded-full border border-[#dce9e0] bg-white px-2 py-0.5 text-[10px] text-[#5f7467]">{asset.sourceTableName}</span>
              <span className="rounded-full bg-[#eef7f1] px-2 py-0.5 text-[10px] text-[#178a53]">{visualizationLabel(asset.visualizationType)}</span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-[#8a8a8e]">
              <span>页面：{scope === "multi_institution" ? "多机构分析" : pageLabel(singleInstitutionAssignedPage(asset))}</span>
              <span>指标：{fieldLabels(asset.metricFields, asset.sourceFields).join("、")}</span>
              <span>维度：{fieldLabels(asset.dimensionFields, asset.sourceFields).join("、")}</span>
            </div>
          </div>
          {scope === "single_institution" ? <label className="shrink-0">
            <span className="sr-only">{asset.name}放置页面</span>
            <select
              aria-label={`${asset.name}放置页面`}
              value={singleInstitutionAssignedPage(asset)}
              disabled={!canManage}
              onChange={(event) => void onPageChange(asset, event.target.value as Extract<PageDataPageCode, "weekly_report" | "institution_supervision">).catch(() => undefined)}
              className="h-8 min-w-[112px] rounded-lg border border-[#dfe5e1] bg-white px-2.5 text-[11px] text-[#536159] outline-none focus:border-[#8fbfa4] disabled:opacity-50"
            >
              {pageOptions.map((page) => <option key={page.code} value={page.code}>{page.label}</option>)}
            </select>
          </label> : <span className="shrink-0 rounded-lg border border-[#dfe5e1] bg-white px-2.5 py-2 text-[11px] text-[#536159]">多机构分析</span>}
          {canManage && <button type="button" aria-label={`编辑页面数据${asset.name}`} title="编辑页面数据" onClick={() => onEdit(asset)} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[#8a918d] hover:bg-white hover:text-[#178a53]"><Pencil className="h-3.5 w-3.5" /></button>}
          {canManage && <button type="button" aria-label={`删除页面数据${asset.name}`} title="删除页面数据" onClick={() => void onDelete(asset).catch(() => undefined)} className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-[#a1a1a6] hover:bg-[#fff1f1] hover:text-[#d93025]"><Trash2 className="h-3.5 w-3.5" /></button>}
        </article>
      ))}
      {!visibleAssets.length && <div className="rounded-xl border border-dashed border-[#dfe7e2] px-4 py-10 text-center text-[11px] text-[#9baba1]">暂无匹配的页面数据配置</div>}
    </div>
  </>;
}

export function PageDataCreateButton({ scope, onClick }: { scope: PageDataInstitutionScope; onClick: () => void }) {
  const label = scope === "multi_institution" ? "新增多机构数据" : "新增单机构数据";
  return <button type="button" onClick={onClick} className="inline-flex h-8 items-center gap-1.5 whitespace-nowrap rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e]" data-page-data-add={scope}><Plus className="h-3.5 w-3.5" />{label}</button>;
}

export const PageDataCreateModal = memo(function PageDataCreateModal({
  scope,
  rawTables,
  multiInstitutionCandidates = [],
  candidatesLoading = false,
  candidatesError = "",
  initialAsset,
  onClose,
  onSave,
}: {
  scope: PageDataInstitutionScope;
  rawTables: RawTableAsset[];
  multiInstitutionCandidates?: MultiInstitutionPageDataCandidate[];
  candidatesLoading?: boolean;
  candidatesError?: string;
  initialAsset?: PageDataAsset | null;
  onClose: () => void;
  onSave: (asset: PageDataAsset) => Promise<void>;
}) {
  const editing = Boolean(initialAsset?.id);
  const [sourceKey, setSourceKey] = useState(initialAsset?.relationshipGroupId || initialAsset?.sourceKey || "");
  const sourceTablesByKey = useMemo(() => new Map(rawTables.map((table) => [table.sourceKey, table])), [rawTables]);
  const candidatesById = useMemo(() => new Map(multiInstitutionCandidates.map((candidate) => [candidate.id, candidate])), [multiInstitutionCandidates]);
  const selectedCandidate = candidatesById.get(sourceKey);
  const selectedTable = scope === "single_institution" ? sourceTablesByKey.get(sourceKey) : undefined;
  const selectedFields = selectedTable?.fields || selectedCandidate?.fields || initialAsset?.sourceFields.filter((field) => field.fieldNameEn !== "__institution_name") || [];
  const fieldGroups = useMemo(() => classifyFields(selectedFields), [selectedFields]);
  const [name, setName] = useState(initialAsset?.name || "");
  const [targetPage, setTargetPage] = useState<Extract<PageDataPageCode, "weekly_report" | "institution_supervision">>(singleInstitutionAssignedPage(initialAsset));
  const [metrics, setMetrics] = useState<string[]>(initialAsset?.metricFields || []);
  const [dimensions, setDimensions] = useState<string[]>((initialAsset?.dimensionFields || []).filter((field) => field !== "__institution_name"));
  const [visualizationType, setVisualizationType] = useState<VisualizationType>((initialAsset?.visualizationType as VisualizationType) || "column");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, saving]);

  const selectTable = (nextSourceKey: string) => {
    const table = scope === "single_institution" ? sourceTablesByKey.get(nextSourceKey) : candidatesById.get(nextSourceKey);
    const fields = table && "fields" in table ? table.fields : [];
    const groups = classifyFields(fields || []);
    setSourceKey(nextSourceKey);
    setName(table ? `${"name" in table ? table.name : table.tableNameCn || table.tableNameEn} · ${scope === "multi_institution" ? "多机构数据" : "单机构数据"}` : "");
    setMetrics(groups.metrics.slice(0, 3).map((field) => field.fieldNameEn));
    setDimensions(groups.dimensions.slice(0, 2).map((field) => field.fieldNameEn));
    setError("");
  };

  const submit = async () => {
    if (scope === "single_institution" && (!selectedTable?.sourceKey || !selectedTable.schemaFingerprint)) return setError("请选择当前机构的一张有效原始表。");
    if (scope === "multi_institution" && (!selectedCandidate?.id || !selectedCandidate.schemaFingerprint)) return setError("请选择一组已经在表关系中配置且结构一致的多机构数据表。");
    if (!name.trim()) return setError("请填写页面数据名称。");
    if (!metrics.length || (scope === "single_institution" && !dimensions.length)) return setError("请至少选择一个指标和一个维度。");
    setSaving(true);
    setError("");
    try {
      await onSave({
        ...(initialAsset || {}),
        id: initialAsset?.id || "",
        name: name.trim(),
        institutionScope: scope,
        relationshipGroupId: scope === "multi_institution" ? selectedCandidate!.id : undefined,
        institutionSources: scope === "multi_institution" ? selectedCandidate!.sources : undefined,
        sourceKey: scope === "multi_institution" ? selectedCandidate!.id : selectedTable!.sourceKey,
        sourceTableId: scope === "multi_institution" ? selectedCandidate!.id : selectedTable!.id,
        sourceTableName: scope === "multi_institution" ? selectedCandidate!.name : selectedTable!.tableNameCn || selectedTable!.tableNameEn,
        schemaFingerprint: scope === "multi_institution" ? selectedCandidate!.schemaFingerprint : selectedTable!.schemaFingerprint,
        sourceFields: scope === "multi_institution" ? selectedCandidate!.fields : selectedTable!.fields,
        targetPages: scope === "multi_institution" ? ["dashboard"] : [targetPage],
        metricFields: metrics,
        dimensionFields: scope === "multi_institution" ? ["__institution_name", ...dimensions] : dimensions,
        visualizationType,
        updatedAt: new Date().toISOString(),
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "页面数据保存失败。");
    } finally {
      setSaving(false);
    }
  };

  const scopeLabel = scope === "multi_institution" ? "多机构数据" : "单机构数据";

  return <div
    className="fixed inset-0 z-[150] flex items-center justify-center bg-[rgba(18,33,27,0.22)] p-4 sm:p-6"
    data-page-data-modal-overlay="true"
    onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}
  >
    <section
      role="dialog"
      aria-modal="true"
      aria-labelledby="page-data-create-title"
      aria-describedby="page-data-create-description"
      aria-busy={saving}
      data-page-data-modal="true"
      className="flex max-h-[88vh] w-full max-w-[760px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15"
      style={{ contain: "layout paint" }}
      onMouseDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4"><div><h3 id="page-data-create-title" className="text-[15px] text-[#1d1d1f]">{editing ? "编辑" : "新增"}{scopeLabel}</h3><p id="page-data-create-description" className="mt-1 text-[11px] text-[#9a9aa0]">{scope === "multi_institution" ? "仅使用当前账号有权访问、已在表关系中显式关联且结构一致的数据表。" : "引用当前机构原始表，配置经营周报或机构督导及默认可视化。"}</p></div><button type="button" aria-label={`关闭${scopeLabel}弹窗`} disabled={saving} onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg text-[#8a8a8e] hover:bg-[#f2f2f7] disabled:opacity-50"><X className="h-4 w-4" /></button></div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
        <div className="grid gap-4 md:grid-cols-2 md:items-start" data-page-data-primary-fields="true">
          <label className="block min-w-0 text-[11px] text-[#636366]">{scopeLabel}名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：分行放款趋势" className="mt-1.5 h-10 w-full rounded-lg border border-[#dedee3] bg-white px-3 text-[12px] text-[#1d1d1f] outline-none focus:border-[#8fbfa4]" /></label>
          <label className="block min-w-0 text-[11px] text-[#636366]">{scope === "multi_institution" ? "已关联数据集" : "原始表"}<span className="ml-1 text-[#d93025]">*</span><select value={sourceKey} onChange={(event) => selectTable(event.target.value)} disabled={candidatesLoading} className="mt-1.5 h-10 w-full rounded-lg border border-[#dedee3] bg-white px-3 text-[12px] text-[#1d1d1f] outline-none focus:border-[#8fbfa4] disabled:bg-[#f7f7f8]"><option value="">{candidatesLoading ? "正在读取已关联数据集…" : scope === "multi_institution" ? "请选择已关联数据集" : "请选择原始表"}</option>{scope === "multi_institution" ? multiInstitutionCandidates.map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>) : rawTables.map((table) => <option key={table.id} value={table.sourceKey}>{table.tableNameCn || table.tableNameEn} · {table.rowCount || 0} 行</option>)}</select></label>
        </div>
        {scope === "single_institution" ? <ChoiceSection title="放置页面" hint="单机构数据只放置到一个页面">{pageOptions.map((page) => <CheckChoice key={page.code} checked={targetPage === page.code} label={page.label} onChange={() => setTargetPage(page.code as Extract<PageDataPageCode, "weekly_report" | "institution_supervision">)} />)}</ChoiceSection> : <ChoiceSection title="包含机构" hint="来自表关系配置且当前账号有权访问">{selectedCandidate?.sources.map((source) => <span key={`${source.tenantId}:${source.sourceKey}`} className="rounded-lg border border-[#dce9e0] bg-[#f5faf7] px-2.5 py-2 text-[11px] text-[#536159]">{source.institutionName} · {source.sourceTableName}</span>)}{!selectedCandidate && !candidatesLoading && <EmptyChoice text="选择数据集后显示包含机构" />}</ChoiceSection>}
        <ChoiceSection title="默认指标" hint="来自所选原始表中的数值字段">{fieldGroups.metrics.map((field) => <CheckChoice key={field.fieldNameEn} checked={metrics.includes(field.fieldNameEn)} label={field.fieldNameCn || field.fieldNameEn} onChange={() => setMetrics((current) => toggle(current, field.fieldNameEn))} />)}{selectedTable && !fieldGroups.metrics.length && <EmptyChoice text="该表没有可识别的数值指标" />}</ChoiceSection>
        <ChoiceSection title="默认维度" hint={scope === "multi_institution" ? "机构维度固定保留，可直接作为图表坐标轴" : "来自所选原始表中的分类或时间字段"}>{scope === "multi_institution" && selectedCandidate && <CheckChoice checked label="机构" onChange={() => undefined} />}{fieldGroups.dimensions.map((field) => <CheckChoice key={field.fieldNameEn} checked={dimensions.includes(field.fieldNameEn)} label={field.fieldNameCn || field.fieldNameEn} onChange={() => setDimensions((current) => toggle(current, field.fieldNameEn))} />)}{selectedTable && !fieldGroups.dimensions.length && <EmptyChoice text="该表没有可识别的维度字段" />}</ChoiceSection>
        <ChoiceSection title="默认样式" hint="使用系统内嵌可视化样式">{visualizationOptions.map((option) => <button key={option.type} type="button" onClick={() => setVisualizationType(option.type)} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-[11px] ${visualizationType === option.type ? "border-[#a7d5b8] bg-[#edf8f1] text-[#178a53]" : "border-[#e5e5ea] bg-white text-[#636366] hover:bg-[#f7faf8]"}`}><option.icon className="h-3.5 w-3.5" />{option.label}</button>)}</ChoiceSection>
        {scope === "multi_institution" && !candidatesLoading && !multiInstitutionCandidates.length && <div className="rounded-lg border border-dashed border-[#dfe7e2] bg-[#fafcfb] px-3 py-3 text-[11px] leading-5 text-[#7b8780]">{candidatesError || "暂无可用多机构数据。请先在“表关系”中显式配置不同机构的对应原始表；系统不会根据同名表或同名字段自动匹配。"}</div>}
        {error && <div className="rounded-lg border border-[#ffd7d7] bg-[#fff5f5] px-3 py-2 text-[11px] text-[#c62828]">{error}</div>}
      </div>
      <div className="flex items-center justify-end gap-2 border-t border-[#f0f0f2] px-5 py-4"><button type="button" onClick={onClose} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366] hover:bg-[#f7f7f8]">取消</button><button type="button" disabled={saving || candidatesLoading} onClick={() => void submit()} className="h-9 rounded-lg bg-[#178a53] px-4 text-[12px] text-white hover:bg-[#127647] disabled:opacity-50">{saving ? "保存中" : editing ? "保存" : `添加${scopeLabel}`}</button></div>
    </section>
  </div>;
});

function ChoiceSection({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return <fieldset><legend className="text-[11px] text-[#636366]">{title}<span className="ml-2 text-[10px] text-[#b0b0b5]">{hint}</span></legend><div className="mt-2 flex flex-wrap gap-2">{children}</div></fieldset>;
}

function CheckChoice({ checked, label, onChange }: { checked: boolean; label: string; onChange: () => void }) {
  return <label className={`flex cursor-pointer items-center gap-2 rounded-lg border px-2.5 py-2 text-[11px] ${checked ? "border-[#b9dec6] bg-[#eff8f2] text-[#178a53]" : "border-[#e5e5ea] bg-white text-[#636366]"}`}><input type="checkbox" checked={checked} onChange={onChange} className="h-3.5 w-3.5 accent-[#178a53]" />{label}</label>;
}

function EmptyChoice({ text }: { text: string }) { return <span className="rounded-lg border border-dashed border-[#e5e5ea] px-3 py-2 text-[10px] text-[#a1a1a6]">{text}</span>; }

function classifyFields(fields: RawField[]) {
  const normalized = normalizeFieldSemantics(fields);
  const numericTypes = new Set(["integer", "int", "long", "decimal", "rate", "number", "float", "double", "numeric"]);
  const metrics = normalized.filter((field) => field.semanticRole === "metric" || ((field.isMetric || numericTypes.has(field.type.toLowerCase())) && !field.isTime));
  let dimensions = normalized.filter((field) => field.semanticRole !== "metric");
  if (!dimensions.length && fields.length > 1) dimensions = [fields[0]];
  return { metrics: metrics.filter((field) => !dimensions.includes(field)), dimensions };
}

function toggle<T extends string>(values: T[], value: T) { return values.includes(value) ? values.filter((item) => item !== value) : [...values, value]; }

function pageLabel(pageCode: PageDataPageCode) { return pageOptions.find((page) => page.code === pageCode)?.label || pageCode; }
function fieldLabels(fields: string[], sourceFields: RawField[]) { const labels = Object.fromEntries(sourceFields.map((field) => [field.fieldNameEn, field.fieldNameCn || field.fieldNameEn])); return fields.map((field) => labels[field] || field); }
function visualizationLabel(type: string) { return visualizationOptions.find((option) => option.type === type)?.label || type; }
