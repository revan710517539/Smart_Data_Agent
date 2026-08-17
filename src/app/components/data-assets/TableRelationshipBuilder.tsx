import { useEffect, useMemo, useRef, useState, type DragEvent, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { Database, GitBranch, GripVertical, Link2, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { apiErrorMessage } from "../../services/apiClient";
import {
  deleteDataAssetItem,
  fetchTableRelationshipCatalog,
  saveDataAssetItem,
  type TableRelationshipAsset,
  type TableRelationshipCatalog,
  type TableRelationshipCatalogTable,
  type TableRelationshipEdge,
  type TableRelationshipNode,
} from "../../services/dataAssetApi";
import { DataPageSelector, useClientPagination } from "../ui/DataPageSelector";

type Endpoint = { nodeId: string; field: string };
type Props = {
  tenantId: string;
  userId: string;
  relationships: TableRelationshipAsset[];
  keyword: string;
  onNotice: (message: string) => void;
  onChanged: (saved?: TableRelationshipAsset) => void;
  createRequestId?: number;
};

const nodeWidth = 248;
const fieldHeight = 28;
const headerHeight = 54;

export function TableRelationshipWorkspace({
  tenantId,
  userId,
  relationships,
  keyword,
  onNotice,
  onChanged,
  createRequestId = 0,
}: Props) {
  const [editor, setEditor] = useState<TableRelationshipAsset | null | undefined>(undefined);
  useEffect(() => {
    if (createRequestId > 0) setEditor(null);
  }, [createRequestId]);
  const normalizedKeyword = keyword.trim().toLowerCase();
  const shown = relationships.filter((item) => !normalizedKeyword || [item.name, ...item.nodes.flatMap((node) => [node.institutionName, node.sourceTableName])].some((value) => value.toLowerCase().includes(normalizedKeyword)));
  const pagination = useClientPagination(shown);

  const remove = async (relationship: TableRelationshipAsset) => {
    if (!window.confirm(`确认删除表关系“${relationship.name}”？已引用该关系的页面数据将停止读取。`)) return;
    try {
      await deleteDataAssetItem({ tenantId, userId, itemType: "table_relationship", itemId: relationship.id });
      onNotice("表关系已删除；多机构数据候选已同步失效。");
      onChanged();
    } catch (error) {
      onNotice(`表关系删除失败：${apiErrorMessage(error, "未知错误")}`);
    }
  };

  return <div className="space-y-3">
    {pagination.paginated && <div className="flex justify-end"><DataPageSelector page={pagination.page} totalPages={pagination.totalPages} shownCount={pagination.items.length} totalCount={pagination.total} onChange={pagination.setPage} ariaLabel="表关系分页" /></div>}
    {pagination.items.map((item) => <div key={item.id} className="flex items-center gap-3 rounded-lg border border-[#e8eee9] bg-white px-4 py-3">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[#f2f8f4] text-[#168454]"><GitBranch className="h-4 w-4" /></div>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2"><div className="truncate text-[13px] font-medium text-[#1d1d1f]">{item.name}</div><span className={`shrink-0 rounded-full px-2 py-0.5 text-[9px] ${item.relationshipScope === "multi_institution" ? "bg-[#e7f5ed] text-[#137a4d]" : "bg-[#f2f2f7] text-[#68686d]"}`}>{item.relationshipScope === "multi_institution" ? "跨机构" : "单机构"}</span></div>
        <div className="mt-1 truncate text-[10px] text-[#8a8f8c]">{item.institutionCount} 个机构 · {item.tableCount} 张表 · {item.edges.length} 条主键关系 · {item.nodes.map((node) => `${node.institutionName}/${node.sourceTableName}`).join("、")}</div>
      </div>
      <button type="button" aria-label={`编辑${item.name}`} onClick={() => setEditor(item)} className="rounded-lg p-2 text-[#7d8580] hover:bg-[#f2f7f4] hover:text-[#147c50]"><Pencil className="h-4 w-4" /></button>
      <button type="button" aria-label={`删除${item.name}`} onClick={() => void remove(item)} className="rounded-lg p-2 text-[#a0a5a2] hover:bg-[#fff2f1] hover:text-[#d34a3a]"><Trash2 className="h-4 w-4" /></button>
    </div>)}
    {!shown.length && <div className="rounded-lg border border-dashed border-[#dfe7e2] bg-[#fafcfb] px-4 py-10 text-center text-[12px] text-[#8a938e]">暂无已配置的多表关系，点击上方“新增表关系”开始配置。</div>}
    {editor !== undefined && <TableRelationshipModal tenantId={tenantId} userId={userId} initial={editor} onClose={() => setEditor(undefined)} onSaved={(message, saved) => { setEditor(undefined); onNotice(message); onChanged(saved); }} />}
  </div>;
}

function TableRelationshipModal({ tenantId, userId, initial, onClose, onSaved }: { tenantId: string; userId: string; initial: TableRelationshipAsset | null; onClose: () => void; onSaved: (message: string, saved: TableRelationshipAsset) => void }) {
  const [catalog, setCatalog] = useState<TableRelationshipCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [name, setName] = useState(initial?.name || "");
  const [nodes, setNodes] = useState<TableRelationshipNode[]>(() => initial?.nodes.map((node) => ({ ...node, position: { ...node.position }, fields: node.fields.map((field) => ({ ...field })) })) || []);
  const [edges, setEdges] = useState<TableRelationshipEdge[]>(() => initial?.edges.map((edge) => ({ ...edge })) || []);
  const [search, setSearch] = useState("");
  const [pending, setPending] = useState<Endpoint | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [moving, setMoving] = useState<{ nodeId: string; startX: number; startY: number; originX: number; originY: number } | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [onClose, saving]);
  const canvasExtent = useMemo(() => {
    if (!nodes.length) return { width: "100%", height: "100%" };
    const width = Math.max(...nodes.map((node) => node.position.x + nodeWidth + 48));
    const height = Math.max(...nodes.map((node) => node.position.y + headerHeight + Math.min(310, node.fields.length * fieldHeight) + 48));
    return { width: `${width}px`, height: `${height}px` };
  }, [nodes]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadError("");
    fetchTableRelationshipCatalog({ tenantId, userId }).then((response) => {
      if (!cancelled) setCatalog(response);
    }).catch((requestError) => {
      if (!cancelled) setLoadError(apiErrorMessage(requestError, "关系目录读取失败。"));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tenantId, userId, catalogAttempt]);

  useEffect(() => {
    if (!moving) return;
    const move = (event: globalThis.PointerEvent) => {
      setNodes((current) => current.map((node) => node.id === moving.nodeId ? { ...node, position: { x: Math.max(0, Math.min(1320, moving.originX + event.clientX - moving.startX)), y: Math.max(0, Math.min(760, moving.originY + event.clientY - moving.startY)) } } : node));
    };
    const up = () => setMoving(null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up, { once: true });
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [moving]);

  const filteredInstitutions = useMemo(() => {
    const key = search.trim().toLowerCase();
    return (catalog?.institutions || []).map((institution) => {
      const institutionMatches = !key || institution.institutionName.toLowerCase().includes(key);
      return { ...institution, tables: institutionMatches ? institution.tables : institution.tables.filter((table) => [table.tableNameCn, table.tableNameEn].some((value) => value.toLowerCase().includes(key))) };
    }).filter((institution) => !key || institution.institutionName.toLowerCase().includes(key) || institution.tables.length);
  }, [catalog, search]);

  const addTable = (table: TableRelationshipCatalogTable, x?: number, y?: number) => {
    if (nodes.some((node) => node.tenantId === table.tenantId && node.sourceKey === table.sourceKey)) return;
    setNodes((current) => [...current, {
      id: `node_${Date.now().toString(36)}_${current.length}`,
      tenantId: table.tenantId,
      institutionName: table.institutionName,
      sourceKey: table.sourceKey,
      sourceTableId: table.id,
      sourceTableName: table.tableNameCn || table.tableNameEn,
      schemaFingerprint: table.schemaFingerprint,
      position: { x: x ?? 40 + (current.length % 3) * 290, y: y ?? 40 + Math.floor(current.length / 3) * 280 },
      fields: table.fields.map((field) => ({ ...field })),
    }]);
  };

  const dropTable = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    const tenantIdValue = event.dataTransfer.getData("application/x-sda-tenant");
    const sourceKey = event.dataTransfer.getData("application/x-sda-source");
    const table = catalog?.institutions.flatMap((item) => item.tables).find((item) => item.tenantId === tenantIdValue && item.sourceKey === sourceKey);
    if (!table || !canvasRef.current) return;
    const rect = canvasRef.current.getBoundingClientRect();
    addTable(table, event.clientX - rect.left + canvasRef.current.scrollLeft - 124, event.clientY - rect.top + canvasRef.current.scrollTop - 30);
  };

  const completeLink = (target: Endpoint) => {
    if (!pending) { setPending(target); return; }
    if (pending.nodeId === target.nodeId) { setPending(target); return; }
    if (edges.some((edge) => (edge.sourceNodeId === pending.nodeId && edge.sourceField === pending.field && edge.targetNodeId === target.nodeId && edge.targetField === target.field) || (edge.targetNodeId === pending.nodeId && edge.targetField === pending.field && edge.sourceNodeId === target.nodeId && edge.sourceField === target.field))) {
      setPending(null);
      return;
    }
    setEdges((current) => [...current, { id: `edge_${Date.now().toString(36)}`, sourceNodeId: pending.nodeId, sourceField: pending.field, targetNodeId: target.nodeId, targetField: target.field, joinType: "inner" }]);
    setPending(null);
  };

  const removeNode = (nodeId: string) => {
    setNodes((current) => current.filter((node) => node.id !== nodeId));
    setEdges((current) => current.filter((edge) => edge.sourceNodeId !== nodeId && edge.targetNodeId !== nodeId));
    if (pending?.nodeId === nodeId) setPending(null);
  };

  const save = async () => {
    setError("");
    if (!name.trim()) { setError("请输入表关系名称。"); return; }
    if (nodes.length < 2) { setError("请至少拖入两张数据表。"); return; }
    if (!edges.length) { setError("请至少建立一条主键关系。"); return; }
    setSaving(true);
    try {
      const response = await saveDataAssetItem({
        tenantId,
        userId,
        itemType: "table_relationship",
        item: { id: initial?.id || "", lockVersion: initial?.lockVersion, name: name.trim(), relationshipScope: new Set(nodes.map((node) => node.tenantId)).size > 1 ? "multi_institution" as const : "single_institution" as const, nodes, edges, institutionCount: 0, tableCount: 0, updatedAt: new Date().toISOString() },
      });
      const saved = response.item as TableRelationshipAsset;
      onSaved(`表关系“${saved.name}”已保存并标记为${saved.relationshipScope === "multi_institution" ? "跨机构" : "单机构"}：${saved.institutionCount} 个机构、${saved.tableCount} 张表${saved.relationshipScope === "multi_institution" ? "；现可在新增多机构数据中选择。" : "。"}`, saved);
    } catch (saveError) {
      setError(apiErrorMessage(saveError, "表关系保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return createPortal(<div className="fixed inset-0 z-[160] flex items-center justify-center bg-[rgba(18,33,27,0.32)] p-4 sm:p-6" data-table-relationship-modal-overlay="true" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-busy={saving} aria-labelledby="table-relationship-dialog-title" aria-describedby="table-relationship-dialog-description" data-table-relationship-dialog="true" className="flex h-[min(760px,86vh)] w-full max-w-[1180px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/15" style={{ contain: "layout paint" }} onMouseDown={(event) => event.stopPropagation()}>
      <div className="flex shrink-0 items-center justify-between border-b border-[#ecefed] px-5 py-4"><div><h3 id="table-relationship-dialog-title" className="text-[17px] font-semibold text-[#1d1d1f]">{initial ? "编辑表关系" : "新增表关系"}</h3><p id="table-relationship-dialog-description" className="mt-1 text-[11px] text-[#8b938e]">拖入授权数据集；点击一个字段连接点，再点击另一张表的字段连接点完成主键关联，也支持按住后拖到目标字段。</p></div><button type="button" onClick={onClose} disabled={saving} aria-label="关闭表关系弹窗" className="rounded-lg p-2 text-[#8a8f8c] hover:bg-[#f2f4f3] disabled:opacity-50"><X className="h-5 w-5" /></button></div>
      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)] overflow-hidden">
        <aside className="min-h-0 overflow-y-auto border-r border-[#ecefed] bg-[#fbfcfb] p-4">
          <div className="relative mb-3"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#a0a5a2]" /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索机构或数据集" className="h-10 w-full rounded-lg border border-[#dfe5e1] bg-white pl-9 pr-3 text-[12px] outline-none focus:border-[#7db797]" /></div>
          {loading && <div className="py-10 text-center text-[11px] text-[#949b97]">正在读取授权机构和数据集…</div>}
          {loadError && <div className="rounded-lg border border-[#f3d5d0] bg-[#fff8f7] p-3 text-[11px] text-[#b8493e]"><div>{loadError}</div><button type="button" onClick={() => setCatalogAttempt((value) => value + 1)} className="mt-2 rounded-md border border-[#e6bdb7] bg-white px-2.5 py-1 text-[10px] text-[#a83e34] hover:bg-[#fff4f2]">重新读取</button></div>}
          {!loading && !loadError && !filteredInstitutions.length && <div className="py-10 text-center text-[11px] text-[#949b97]">暂无可用数据集</div>}
          <div className="space-y-3">{filteredInstitutions.map((institution) => <section key={institution.tenantId}><div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-[#3d4741]"><Database className="h-3.5 w-3.5 text-[#20865a]" />{institution.institutionName}<span className="text-[#a0a7a3]">{institution.tables.length}</span></div><div className="space-y-1.5">{institution.tables.map((table) => <button type="button" draggable onDragStart={(event) => { event.dataTransfer.setData("application/x-sda-tenant", table.tenantId); event.dataTransfer.setData("application/x-sda-source", table.sourceKey); }} onDoubleClick={() => addTable(table)} key={`${table.tenantId}:${table.sourceKey}`} className="group flex w-full items-center gap-2 rounded-lg border border-[#e6ebe8] bg-white px-2.5 py-2 text-left hover:border-[#9dc8ae] hover:bg-[#f7fbf8]"><GripVertical className="h-4 w-4 shrink-0 text-[#b1b7b3]" /><div className="min-w-0 flex-1"><div className="truncate text-[11px] text-[#2d3430]">{table.tableNameCn || table.tableNameEn}</div><div className="mt-0.5 text-[9px] text-[#9aa19d]">{table.fields.length} 字段 · {table.fields.filter((field) => field.isPrimaryKey).length} 主键</div></div><Plus className="h-3.5 w-3.5 text-[#7c9185] opacity-0 group-hover:opacity-100" /></button>)}{!institution.tables.length && <div className="rounded-lg border border-dashed border-[#e6ebe8] px-2.5 py-2 text-[9px] text-[#a2a8a4]">当前机构暂无可用数据集</div>}</div></section>)}</div>
        </aside>
        <main className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-[#f6f8f7] p-4"><div className="mb-3 flex items-center gap-3"><label className="flex min-w-0 flex-1 items-center gap-2 text-[11px] text-[#646d68]">关系名称<input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：信贷经营多机构关联" maxLength={120} className="h-9 min-w-0 flex-1 rounded-lg border border-[#dfe5e1] bg-white px-3 text-[12px] outline-none focus:border-[#7db797]" /></label><div className="shrink-0 text-[10px] text-[#8d9690]">{nodes.length}/12 张表 · {edges.length}/24 条关系</div></div>
          <div ref={canvasRef} onDragOver={(event) => event.preventDefault()} onDrop={dropTable} className="relative min-h-0 flex-1 overflow-auto rounded-xl border border-dashed border-[#b9ccc1] bg-white" data-relationship-canvas="true">
            <div className="relative min-h-full min-w-full bg-[radial-gradient(#dfe7e2_1px,transparent_1px)] [background-size:20px_20px]" style={canvasExtent}>
              {!nodes.length && <div className="absolute left-1/2 top-1/2 flex w-[min(520px,calc(100%-48px))] -translate-x-1/2 -translate-y-1/2 flex-col items-center rounded-xl border border-dashed border-[#c9d8cf] bg-[#fbfdfc] px-6 py-12 text-center"><GitBranch className="h-8 w-8 text-[#89aa97]" /><div className="mt-3 text-[13px] text-[#546158]">将左侧同机构或跨机构的数据集拖到画布</div><div className="mt-1 text-[10px] text-[#929b95]">也可双击数据集快速添加；系统按节点机构自动标记关系范围，不会按同名表或字段自动关联。</div></div>}
              <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible">{edges.map((edge) => {
                const source = nodes.find((node) => node.id === edge.sourceNodeId); const target = nodes.find((node) => node.id === edge.targetNodeId); if (!source || !target) return null;
                const sourceIndex = Math.max(0, source.fields.findIndex((field) => field.fieldNameEn === edge.sourceField)); const targetIndex = Math.max(0, target.fields.findIndex((field) => field.fieldNameEn === edge.targetField));
                const sx = source.position.x + nodeWidth; const sy = source.position.y + headerHeight + sourceIndex * fieldHeight + fieldHeight / 2; const tx = target.position.x; const ty = target.position.y + headerHeight + targetIndex * fieldHeight + fieldHeight / 2; const middle = (sx + tx) / 2;
                return <path key={edge.id} d={`M ${sx} ${sy} C ${middle} ${sy}, ${middle} ${ty}, ${tx} ${ty}`} fill="none" stroke="#2b9b67" strokeWidth="2" />;
              })}</svg>
              {nodes.map((node) => <div key={node.id} style={{ left: node.position.x, top: node.position.y, width: nodeWidth }} className="absolute overflow-hidden rounded-xl border border-[#b7d4c3] bg-white shadow-[0_5px_20px_rgba(32,85,57,0.08)]">
                <div onPointerDown={(event: PointerEvent<HTMLDivElement>) => { if ((event.target as HTMLElement).closest("button")) return; setMoving({ nodeId: node.id, startX: event.clientX, startY: event.clientY, originX: node.position.x, originY: node.position.y }); }} className="flex h-[54px] cursor-move items-start gap-2 border-b border-[#e6eee9] bg-[#f4faf6] px-3 py-2"><Database className="mt-0.5 h-4 w-4 shrink-0 text-[#20865a]" /><div className="min-w-0 flex-1"><div className="truncate text-[10px] font-medium text-[#16754d]">{node.institutionName}</div><div className="truncate text-[11px] text-[#2f3833]">{node.sourceTableName}</div></div><button type="button" aria-label={`移除${node.sourceTableName}`} onClick={() => removeNode(node.id)} className="rounded p-1 text-[#9aa39d] hover:bg-white hover:text-[#cf4a3e]"><X className="h-3.5 w-3.5" /></button></div>
                <div className="max-h-[310px] overflow-y-auto">{node.fields.map((field) => {
                  const selected = pending?.nodeId === node.id && pending.field === field.fieldNameEn;
                  const endpoint = { nodeId: node.id, field: field.fieldNameEn };
                  return <div key={field.fieldNameEn} className="flex h-7 items-center gap-1.5 border-b border-[#f1f3f2] px-2 text-[9px] last:border-b-0"><button type="button" aria-label={`连接${node.sourceTableName}.${field.fieldNameCn || field.fieldNameEn}`} onPointerDown={() => { if (!pending) setPending(endpoint); }} onPointerUp={() => { if (pending) completeLink(endpoint); }} className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${selected ? "border-[#148554] bg-[#148554] text-white" : "border-[#9bb8a7] bg-white text-[#4f8f68]"}`}><Link2 className="h-2.5 w-2.5" /></button><span className="min-w-0 flex-1 truncate text-[#4d554f]" title={field.fieldNameEn}>{field.fieldNameCn || field.fieldNameEn}</span>{field.isPrimaryKey && <span className="rounded bg-[#eaf6ee] px-1 text-[8px] text-[#177e50]">主键</span>}<span className="text-[8px] text-[#a1a7a3]">{field.type}</span></div>;
                })}</div>
              </div>)}
            </div>
          </div>
          <div className="mt-2 flex min-h-5 items-center justify-between gap-3 text-[10px]" aria-live="polite"><span data-relationship-save-status="true" className={error && !saving ? "text-[#c7463a]" : "text-[#7f8983]"}>{saving ? "正在保存中……" : error || (pending ? "已选择起点，请点击另一张表的关联字段。" : "连接必须至少一端为主键，且两端字段类型一致；同机构多表会先按关系连接。")}</span>{edges.length > 0 && !saving && <button type="button" aria-label="撤销上一条关系" onClick={() => setEdges((current) => current.slice(0, -1))} className="shrink-0 whitespace-nowrap border-0 bg-transparent p-0 text-[11px] font-normal leading-5 text-[#4e7760] hover:text-[#2f6649] hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#8dc4a5] focus-visible:ring-offset-1">撤销上一条关系</button>}</div>
        </main>
      </div>
      <div className="relative z-10 flex shrink-0 items-center justify-end gap-2 border-t border-[#ecefed] bg-white px-5 py-3"><button type="button" onClick={onClose} disabled={saving} className="h-9 rounded-lg border border-[#dfe3e1] bg-white px-4 text-[12px] text-[#5f6762] hover:bg-[#f7f8f7] disabled:opacity-50">取消</button><button type="button" onClick={() => void save()} disabled={saving || loading} className="h-9 rounded-lg bg-[#0f8f58] px-5 text-[12px] text-white hover:bg-[#0b7d4c] disabled:cursor-not-allowed disabled:opacity-50">{saving ? "保存中…" : "保存"}</button></div>
    </section>
  </div>, document.body);
}
