import { useEffect, useState } from "react";
import { Link2, Pencil, Plus, Trash2, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { deleteDataAssetItem, fetchDataAssets, saveDataAssetItem, type ExternalToolAsset } from "../services/dataAssetApi";

const emptyTool: ExternalToolAsset = {
  id: "", name: "", provider: "", toolType: "api", description: "", endpoint: "",
  capabilities: [], enabled: false, status: "未配置",
};

export function ExternalToolManager() {
  const { tenantId, userId } = usePlatformContext();
  const [tools, setTools] = useState<ExternalToolAsset[]>([]);
  const [draft, setDraft] = useState<ExternalToolAsset | null>(null);
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const bundle = await fetchDataAssets({ tenantId, userId });
      setTools(bundle.external_tools || []);
    } catch (error) {
      setNotice(apiErrorMessage(error, "工具目录加载失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [tenantId, userId]);

  const save = async (tool: ExternalToolAsset) => {
    if (!tool.name.trim() || !tool.provider.trim() || !tool.toolType.trim() || !tool.description.trim()) {
      setNotice("请完整填写工具名称、系统来源、工具类型和用途说明。");
      return;
    }
    if (tool.enabled && tool.provider.trim().toLowerCase() !== "internal agent" && !tool.endpoint.trim()) {
      setNotice("外部系统启用前必须配置接入地址；未配置的工具可以先保存为停用状态。");
      return;
    }
    try {
      await saveDataAssetItem({ tenantId, userId, itemType: "external_tool", item: tool });
      setDraft(null);
      setNotice("外部工具配置已保存。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "工具保存失败"));
    }
  };

  const remove = async (tool: ExternalToolAsset) => {
    if (!window.confirm(`确认删除“${tool.name}”吗？`)) return;
    try {
      await deleteDataAssetItem({ tenantId, userId, itemType: "external_tool", itemId: tool.id });
      setNotice("外部工具已删除。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "工具删除失败"));
    }
  };

  const toggleTool = (tool: ExternalToolAsset) => {
    const enabling = !tool.enabled;
    if (enabling && tool.provider.trim().toLowerCase() !== "internal agent" && !tool.endpoint.trim()) {
      setNotice(`“${tool.name}”尚未配置接入地址，请先编辑后再启用。`);
      return;
    }
    void save({ ...tool, enabled: enabling, status: enabling ? "已接入" : "已停用" });
  };

  return (
    <div className="min-h-full bg-[#f8f8fa] p-7">
      <div className="mx-auto max-w-[1260px]">
        <div className="flex items-start justify-between gap-4"><div><h2 className="text-[18px] tracking-tight text-[#1d1d1f]">工具调用</h2><p className="mt-1 text-[13px] text-[#8a8a8e]">统一管理智能分析可调用的外部系统、企业工具和专业智能体。</p></div><div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true"><button type="button" onClick={() => setDraft({ ...emptyTool })} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white"><Plus className="h-3.5 w-3.5" />新增工具</button></div></div>
        {notice ? <div className="mt-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366]">{notice}</div> : null}
        <div className="mt-6 overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white">
          <div className="grid grid-cols-[minmax(220px,1.1fr)_minmax(220px,1fr)_minmax(260px,1.4fr)_130px_110px] border-b border-[#f0f0f2] bg-[#fafbfc] px-5 py-3 text-[11px] text-[#8a8a8e]"><span>工具名称</span><span>来源与类型</span><span>能力</span><span>状态</span><span className="text-right">操作</span></div>
          {loading ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">正在读取工具目录…</div> : null}
          {tools.map((tool) => <div key={tool.id} className="grid grid-cols-[minmax(220px,1.1fr)_minmax(220px,1fr)_minmax(260px,1.4fr)_130px_110px] items-center gap-4 border-b border-[#f5f5f7] px-5 py-4 last:border-b-0"><div className="min-w-0"><div className="flex items-center gap-2"><Link2 className="h-3.5 w-3.5 text-[#8a8a8e]" /><span className="truncate text-[13px] text-[#1d1d1f]">{tool.name}</span></div><div className="mt-1 truncate text-[11px] text-[#aeaeb2]">{tool.description}</div></div><div className="min-w-0"><div className="text-[12px] text-[#3a3a3c]">{tool.provider}</div><div className="mt-1 text-[11px] text-[#aeaeb2]">{tool.toolType}</div><div className="mt-1 truncate text-[10px] text-[#c7c7cc]">{tool.endpoint || (tool.provider === "Internal Agent" ? "平台内部能力" : "接入地址待配置")}</div></div><div className="flex flex-wrap gap-1">{tool.capabilities.map((capability) => <span key={capability} className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[10px] text-[#636366]">{capability}</span>)}</div><div className={`inline-flex w-fit rounded-full px-2.5 py-1 text-[10px] ${tool.enabled ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`}>{tool.enabled ? tool.status || "已启用" : "未启用"}</div><div className="flex justify-end gap-1"><button type="button" onClick={() => toggleTool(tool)} className="rounded-md px-2 py-1.5 text-[11px] text-[#636366] hover:bg-[#f2f2f7]">{tool.enabled ? "停用" : "启用"}</button><button type="button" onClick={() => setDraft({ ...tool })} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label={`编辑${tool.name}`}><Pencil className="h-3.5 w-3.5" /></button><button type="button" onClick={() => void remove(tool)} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d93025]" aria-label={`删除${tool.name}`}><Trash2 className="h-3.5 w-3.5" /></button></div></div>)}
        </div>
      </div>
      {draft ? <ToolEditor draft={draft} onClose={() => setDraft(null)} onSave={(value) => void save(value)} /> : null}
    </div>
  );
}

function ToolEditor({ draft: initial, onClose, onSave }: { draft: ExternalToolAsset; onClose: () => void; onSave: (value: ExternalToolAsset) => void }) {
  const [draft, setDraft] = useState(initial);
  const field = (key: "name" | "provider" | "toolType" | "description" | "endpoint", label: string, multiline = false) => <label><span className="mb-1.5 block text-[11px] text-[#636366]">{label}</span>{multiline ? <textarea value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} className="min-h-20 w-full rounded-lg border border-[#e5e5ea] px-3 py-2 text-[12px] outline-none" /> : <input value={draft[key]} onChange={(event) => setDraft({ ...draft, [key]: event.target.value })} className="h-9 w-full rounded-lg border border-[#e5e5ea] px-3 text-[12px] outline-none" />}</label>;
  return <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/20 px-4" onMouseDown={onClose}><div role="dialog" aria-modal="true" aria-label={`${draft.id ? "编辑" : "新增"}工具`} className="flex max-h-[86vh] w-full max-w-[620px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20" onMouseDown={(event) => event.stopPropagation()}><div className="flex items-center justify-between border-b border-[#f0f0f2] px-6 py-4"><div><h3 className="text-[16px] text-[#1d1d1f]">{draft.id ? "编辑" : "新增"}工具</h3><p className="mt-1 text-[11px] text-[#8a8a8e]">接入信息不会直接执行，启用后由 Skill 解决方案按权限引用。</p></div><button type="button" onClick={onClose} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label="关闭工具弹窗"><X className="h-4 w-4" /></button></div><div className="grid min-h-0 gap-4 overflow-y-auto px-6 py-5">{field("name", "工具名称")}{field("provider", "系统来源")}{field("toolType", "工具类型")}{field("description", "用途说明", true)}{field("endpoint", draft.provider.trim().toLowerCase() === "internal agent" ? "内部能力标识（可选）" : "接入地址（启用前必填）")}<label><span className="mb-1.5 block text-[11px] text-[#636366]">能力标签（逗号分隔）</span><input value={draft.capabilities.join("，")} onChange={(event) => setDraft({ ...draft, capabilities: event.target.value.split(/[,，]/).map((item) => item.trim()).filter(Boolean) })} className="h-9 w-full rounded-lg border border-[#e5e5ea] px-3 text-[12px] outline-none" /></label><label className="flex items-center gap-2 text-[12px] text-[#3a3a3c]"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked, status: event.target.checked ? "已接入" : "未配置" })} />启用工具</label></div><div className="flex justify-end gap-2 border-t border-[#f0f0f2] px-6 py-4"><button type="button" onClick={onClose} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366]">取消</button><button type="button" onClick={() => onSave(draft)} className="h-9 rounded-lg bg-[#1d1d1f] px-5 text-[12px] text-white">保存</button></div></div></div>;
}
