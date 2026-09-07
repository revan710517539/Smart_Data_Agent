import { useEffect, useMemo, useRef, useState } from "react";
import { Check, GripVertical, SlidersHorizontal, Trash2, X } from "lucide-react";
import type { RawField } from "../../services/dataAssetApi";
import { createClientUuid } from "../../utils/clientUuid";
import { AppSelect } from "../ui/AppSelect";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "../ui/FormDialog";

export type ReportPublicFilterGroup = {
  id: string;
  name: string;
  datasetIds: string[];
  fields: string[];
  controlOrder: string[];
  controlPositions?: Record<string, number>;
  selections: Record<string, string>;
};

export type ReportPublicFilterControlRef = { groupId: string; field: string };

function controlKey(control: ReportPublicFilterControlRef) {
  return `${control.groupId}:${control.field}`;
}

export function orderedReportPublicFilterControls(groups: ReportPublicFilterGroup[]) {
  let fallbackPosition = 0;
  return groups.flatMap((group) => group.controlOrder.map((field) => {
    const position = group.controlPositions?.[field];
    return {
      group,
      field,
      position: typeof position === "number" && Number.isFinite(position) ? position : Number.MAX_SAFE_INTEGER + fallbackPosition++,
    };
  })).sort((left, right) => left.position - right.position);
}

export function normalizeReportPublicFilterPositions(groups: ReportPublicFilterGroup[]) {
  const ordered = orderedReportPublicFilterControls(groups);
  const positionByKey = new Map(ordered.map((control, index) => [controlKey({ groupId: control.group.id, field: control.field }), index]));
  return groups.map((group) => ({
    ...group,
    controlOrder: ordered.filter((control) => control.group.id === group.id).map((control) => control.field),
    controlPositions: Object.fromEntries(group.fields.map((field) => [field, positionByKey.get(controlKey({ groupId: group.id, field })) ?? ordered.length])),
  }));
}

export function moveReportPublicFilterControl(groups: ReportPublicFilterGroup[], source: ReportPublicFilterControlRef, target: ReportPublicFilterControlRef) {
  if (controlKey(source) === controlKey(target)) return groups;
  const ordered = orderedReportPublicFilterControls(groups).map(({ group, field }) => ({ groupId: group.id, field }));
  const sourceIndex = ordered.findIndex((control) => controlKey(control) === controlKey(source));
  const targetIndex = ordered.findIndex((control) => controlKey(control) === controlKey(target));
  if (sourceIndex < 0 || targetIndex < 0) return groups;
  const [moved] = ordered.splice(sourceIndex, 1);
  ordered.splice(targetIndex, 0, moved);
  const positionByKey = new Map(ordered.map((control, index) => [controlKey(control), index]));
  return groups.map((group) => ({
    ...group,
    controlOrder: ordered.filter((control) => control.groupId === group.id).map((control) => control.field),
    controlPositions: Object.fromEntries(group.fields.map((field) => [field, positionByKey.get(controlKey({ groupId: group.id, field })) ?? ordered.length])),
  }));
}

export function PublicFilterFieldChip({ field, label, onRemove }: { field: string; label: string; onRemove: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setMenuOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [menuOpen]);
  return <span ref={rootRef} className="relative inline-flex" data-page-public-filter-field-chip={field}>
    <button type="button" onContextMenu={(event) => { event.preventDefault(); event.stopPropagation(); setMenuOpen(true); }} className="rounded-md border border-[#d5e3da] bg-white px-2.5 py-1.5 text-[10px] text-[#456050]" title="右键打开字段操作">{label}</button>
    {menuOpen ? <span className="absolute left-0 top-full z-20 mt-1 w-24 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg" data-page-public-filter-field-menu="true" onPointerDown={(event) => event.stopPropagation()}>
      <button type="button" onClick={() => { setMenuOpen(false); onRemove(); }} className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-[11px] text-[#c62828] hover:bg-[#fff1f1]" data-page-public-filter-remove-field={field}><Trash2 className="h-3 w-3" />删除字段</button>
    </span> : null}
  </span>;
}

export type ReportFilterDataset = {
  id: string;
  name: string;
  subtitle?: string;
  fields: RawField[];
  rows?: Array<Record<string, unknown>>;
};

export function ReportPublicFilterButton({ datasets, groups, onChange, className = "" }: {
  datasets: ReportFilterDataset[];
  groups: ReportPublicFilterGroup[];
  onChange: (groups: ReportPublicFilterGroup[]) => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [draftGroups, setDraftGroups] = useState<ReportPublicFilterGroup[]>([]);
  const [selectedDatasetIds, setSelectedDatasetIds] = useState<string[]>([]);
  const [removedFields, setRemovedFields] = useState<string[]>([]);
  const [name, setName] = useState("");
  const selectedDatasets = datasets.filter((dataset) => selectedDatasetIds.includes(dataset.id));
  const commonFields = useMemo(() => {
    if (!selectedDatasets.length) return [];
    const intersection = selectedDatasets.slice(1).reduce(
      (current, dataset) => current.filter((field) => dataset.fields.some((candidate) => candidate.fieldNameEn === field.fieldNameEn)),
      selectedDatasets[0].fields,
    );
    return intersection.filter((field) => !removedFields.includes(field.fieldNameEn));
  }, [removedFields, selectedDatasets]);

  const begin = () => {
    setDraftGroups(groups);
    setSelectedDatasetIds([]);
    setRemovedFields([]);
    setName("");
    setOpen(true);
  };
  const addDraftGroup = () => {
    if (!selectedDatasetIds.length || !commonFields.length) return;
    setDraftGroups((current) => normalizeReportPublicFilterPositions([...current, {
      id: createClientUuid(),
      name: name.trim() || `公共筛选 ${current.length + 1}`,
      datasetIds: selectedDatasetIds,
      fields: commonFields.map((field) => field.fieldNameEn),
      controlOrder: commonFields.map((field) => field.fieldNameEn),
      selections: {},
    }]));
    setSelectedDatasetIds([]);
    setRemovedFields([]);
    setName("");
  };

  return <>
    <button type="button" onClick={begin} className={`inline-flex h-8 items-center gap-1.5 rounded-lg border border-[#cfe0d6] bg-white px-3 text-[10px] text-[#3f7656] hover:bg-[#f3f8f5] ${className}`} data-page-public-filter-button="true"><SlidersHorizontal className="h-3.5 w-3.5" />公共筛选{groups.length ? ` ${groups.length}` : ""}</button>
    <FormDialog
      open={open}
      title="公共筛选"
      description="选择多个数据集后，仅保留它们共有的字段。右键字段可从当前分组移除。"
      widthClassName="max-w-[820px]"
      heightClassName="max-h-[86vh]"
      zIndexClassName="z-[180]"
      onClose={() => setOpen(false)}
      bodyClassName="space-y-4"
      dataAttributes={{ "data-page-public-filter-dialog": "true" }}
      footer={<>
        <FormDialogCancelButton onClick={() => setOpen(false)} />
        <button type="button" disabled={!selectedDatasetIds.length || !commonFields.length} onClick={addDraftGroup} className="inline-flex h-9 items-center rounded-lg border border-[#cfe0d6] bg-white px-4 text-[11px] text-[#34704d] disabled:opacity-40" data-page-public-filter-save-group="true">保存</button>
        <FormDialogPrimaryButton onClick={() => { onChange(draftGroups); setOpen(false); }} data-page-public-filter-confirm="true">确认</FormDialogPrimaryButton>
      </>}
    >
      <section className="rounded-xl border border-[#e1e8e4] bg-[#f8faf9] p-3" data-page-public-filter-common-fields="true">
        <div className="flex items-center justify-between gap-3"><span className="text-[11px] text-[#4f5d55]">公共字段</span><span className="text-[9px] text-[#98a19c]">右键移除</span></div>
        <div className="mt-2 flex min-h-9 flex-wrap gap-2">
          {commonFields.map((field) => <PublicFilterFieldChip key={field.fieldNameEn} field={field.fieldNameEn} label={field.fieldNameCn || field.fieldNameEn} onRemove={() => setRemovedFields((current) => [...current, field.fieldNameEn])} />)}
          {!selectedDatasetIds.length ? <span className="py-2 text-[10px] text-[#9aa39e]">请先在下方选择数据集</span> : !commonFields.length ? <span className="py-2 text-[10px] text-[#b42318]">所选数据集没有可用的公共字段</span> : null}
        </div>
      </section>
      <section>
        <label className="text-[10px] text-[#69756e]">分组名称</label>
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder={`公共筛选 ${draftGroups.length + 1}`} className="mt-1 h-9 w-full rounded-lg border border-[#dfe5e1] bg-white px-3 text-[11px] outline-none focus:border-[#7fb596]" />
      </section>
      <section data-page-public-filter-datasets="true">
        <div className="mb-2 text-[11px] text-[#4f5d55]">可用数据集</div>
        <div className="grid gap-2 sm:grid-cols-2">
          {datasets.map((dataset) => {
            const selected = selectedDatasetIds.includes(dataset.id);
            return <button key={dataset.id} type="button" onClick={() => { setSelectedDatasetIds((current) => selected ? current.filter((id) => id !== dataset.id) : [...current, dataset.id]); setRemovedFields([]); }} className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-left ${selected ? "border-[#75b492] bg-[#edf8f1]" : "border-[#e2e7e4] bg-white hover:bg-[#f8faf9]"}`}><span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${selected ? "border-[#178a53] bg-[#178a53] text-white" : "border-[#cfd7d2] text-transparent"}`}><Check className="h-3 w-3" /></span><span className="min-w-0"><span className="block truncate text-[11px] text-[#27342c]">{dataset.name}</span><span className="mt-0.5 block truncate text-[9px] text-[#8f9993]">{dataset.subtitle || dataset.id}</span></span></button>;
          })}
          {!datasets.length ? <span className="px-3 py-8 text-center text-[10px] text-[#9aa39e] sm:col-span-2">当前报表还没有可用于联合筛选的数据集</span> : null}
        </div>
      </section>
      {draftGroups.length ? <section className="space-y-2 border-t border-[#edf0ee] pt-3" data-page-public-filter-saved-groups="true">
        <div className="text-[11px] text-[#4f5d55]">已保存分组</div>
        {draftGroups.map((group) => <div key={group.id} className="flex items-center justify-between gap-3 rounded-lg border border-[#e2e7e4] bg-white px-3 py-2"><div className="min-w-0"><div className="truncate text-[11px] text-[#27342c]">{group.name}</div><div className="mt-0.5 truncate text-[9px] text-[#8f9993]">{group.datasetIds.length} 个数据集 · {group.fields.length} 个字段</div></div><button type="button" onClick={() => setDraftGroups((current) => current.filter((item) => item.id !== group.id))} className="flex h-7 w-7 items-center justify-center rounded-md text-[#8d9690] hover:bg-[#fff1f1] hover:text-[#c62828]" aria-label={`删除${group.name}`}><X className="h-3.5 w-3.5" /></button></div>)}
      </section> : null}
    </FormDialog>
  </>;
}

export function ReportPublicFilterControls({ datasets, groups, editable, onChange, className = "mb-3" }: {
  datasets: ReportFilterDataset[];
  groups: ReportPublicFilterGroup[];
  editable: boolean;
  onChange: (groups: ReportPublicFilterGroup[]) => void;
  className?: string;
}) {
  const [dragging, setDragging] = useState<ReportPublicFilterControlRef | null>(null);
  const draggingRef = useRef<ReportPublicFilterControlRef | null>(null);
  if (!groups.length) return null;
  const labels = Object.assign({}, ...datasets.map((dataset) => Object.fromEntries(dataset.fields.map((field) => [field.fieldNameEn, field.fieldNameCn || field.fieldNameEn]))));
  const values = (group: ReportPublicFilterGroup, field: string) => Array.from(new Set(group.datasetIds.flatMap((datasetId) => (datasets.find((dataset) => dataset.id === datasetId)?.rows || []).map((row) => String(row[field] ?? "—"))))).sort((a, b) => a.localeCompare(b, "zh-CN")).slice(0, 200);
  const move = (target: ReportPublicFilterControlRef) => {
    const source = draggingRef.current || dragging;
    if (!source) return;
    onChange(moveReportPublicFilterControl(groups, source, target));
    draggingRef.current = null;
    setDragging(null);
  };
  const controls = orderedReportPublicFilterControls(groups);
  return <div className={`${className} flex flex-wrap items-end gap-2 rounded-xl border border-[#e1e8e4] bg-[#f8faf9] p-3`} data-page-public-filter-controls="true">
    {controls.map(({ group, field }) => <label key={`${group.id}:${field}`} draggable={editable} onDragStart={() => { const source = { groupId: group.id, field }; draggingRef.current = source; setDragging(source); }} onDragEnd={() => { draggingRef.current = null; setDragging(null); }} onDragOver={(event) => { if (editable) event.preventDefault(); }} onDrop={() => move({ groupId: group.id, field })} className="min-w-[160px] cursor-default" data-page-public-filter-control={field}>
      <span className="mb-1 flex items-center gap-1 text-[9px] text-[#7a8680]">{editable ? <GripVertical className="h-3 w-3 cursor-grab" /> : null}{group.name} · {labels[field] || field}</span>
      <AppSelect value={group.selections[field] || ""} onChange={(event) => onChange(groups.map((item) => item.id === group.id ? { ...item, selections: { ...item.selections, [field]: event.target.value } } : item))} className="h-9 w-full rounded-lg border border-[#dbe3de] bg-white px-2.5 text-[11px] text-[#27342c] outline-none focus:border-[#7fb596]"><option value="">全部</option>{values(group, field).map((value) => <option key={value} value={value}>{value}</option>)}</AppSelect>
    </label>)}
  </div>;
}

export function applyReportPublicFilters<T extends { raw: Record<string, unknown> }>(rows: T[], datasetId: string, groups: ReportPublicFilterGroup[]) {
  const rules = groups.flatMap((group) => group.datasetIds.includes(datasetId)
    ? group.controlOrder.flatMap((field) => group.selections[field] ? [{ field, value: group.selections[field] }] : [])
    : []);
  return rules.length ? rows.filter((row) => rules.every((rule) => String(row.raw[rule.field] ?? "—") === rule.value)) : rows;
}
