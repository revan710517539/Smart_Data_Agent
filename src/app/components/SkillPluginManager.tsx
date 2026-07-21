import { useEffect, useMemo, useState } from "react";
import { BookOpen, ChevronRight, Pencil, Plus, Trash2, Wrench, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  deleteDataAssetItem,
  fetchDataAssets,
  saveDataAssetItem,
  type AnalysisSkillAsset,
  type ExternalToolAsset,
} from "../services/dataAssetApi";
import { apiErrorMessage } from "../services/apiClient";

const emptySkill = (category: "场景" | "主题"): AnalysisSkillAsset => ({
  id: "",
  name: "",
  category,
  description: "",
  memoryRefs: [],
  toolRefs: [],
  analysisMethod: "",
  documentAbstraction: "",
  outputFormat: "",
  viewpointStrategy: "",
  recommendedSkillIds: [],
  enabled: true,
  sortOrder: 999,
});

type SkillReferenceOption = {
  id: string;
  label: string;
  meta: string;
  disabled?: boolean;
};

export function SkillPluginManager() {
  const { tenantId, userId } = usePlatformContext();
  const [activeCategory, setActiveCategory] = useState<"场景" | "主题">("场景");
  const [skills, setSkills] = useState<AnalysisSkillAsset[]>([]);
  const [memoryOptions, setMemoryOptions] = useState<SkillReferenceOption[]>([]);
  const [tools, setTools] = useState<ExternalToolAsset[]>([]);
  const [draft, setDraft] = useState<AnalysisSkillAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const bundle = await fetchDataAssets({ tenantId, userId });
      setSkills(bundle.analysis_skills || []);
      setTools(bundle.external_tools || []);
      setMemoryOptions([
        ...(bundle.intents || []).filter((item) => !item.lifecycleStatus || item.lifecycleStatus === "active").map((item) => ({ id: item.id, label: `${item.scenario} / ${item.purpose}`, meta: "分析意图" })),
        ...(bundle.analysis_experiences || []).filter((item) => !item.lifecycleStatus || item.lifecycleStatus === "active").map((item) => ({ id: item.id, label: item.title || item.name, meta: "分析经验" })),
        ...(bundle.behavior_habits || []).filter((item) => !item.lifecycleStatus || item.lifecycleStatus === "active").map((item) => ({ id: item.id, label: item.title, meta: "行为习惯" })),
      ]);
      setNotice("");
    } catch (error) {
      setNotice(apiErrorMessage(error, "Skill 解决方案加载失败"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, [tenantId, userId]);

  const visibleSkills = useMemo(
    () => skills.filter((skill) => skill.category === activeCategory).sort((a, b) => a.sortOrder - b.sortOrder),
    [activeCategory, skills],
  );

  const save = async () => {
    if (!draft?.name.trim() || !draft.description.trim()) {
      setNotice("请填写 Skill 名称和用途说明。");
      return;
    }
    try {
      await saveDataAssetItem({
        tenantId,
        userId,
        itemType: "analysis_skill",
        item: draft.category === "主题" ? { ...draft, outputFormat: "" } : draft,
      });
      setDraft(null);
      setNotice("Skill 解决方案已保存。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "Skill 保存失败"));
    }
  };

  const remove = async (skill: AnalysisSkillAsset) => {
    if (!window.confirm(`确认删除“${skill.name}”吗？`)) return;
    try {
      await deleteDataAssetItem({ tenantId, userId, itemType: "analysis_skill", itemId: skill.id });
      setNotice("Skill 已删除。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "Skill 删除失败"));
    }
  };

  return (
    <div className="min-h-full bg-[#f8f8fa] p-7">
      <div className="mx-auto max-w-[1260px]">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">Skill插件</h2>
            <p className="mt-1 text-[13px] text-[#8a8a8e]">将提炼后的意图、分析经验、行为习惯与工具、分析方法组合为可复用解决方案；知识文件不会被 Skill 直接引用。</p>
          </div>
          <button type="button" onClick={() => setDraft(emptySkill(activeCategory))} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 text-[12px] text-white hover:bg-[#2c2c2e]">
            <Plus className="h-3.5 w-3.5" />新增{activeCategory}
          </button>
        </div>

        <div className="mt-6 inline-flex rounded-xl bg-[#eeeef3] p-1">
          {(["场景", "主题"] as const).map((category) => (
            <button key={category} type="button" onClick={() => setActiveCategory(category)} className={`h-9 rounded-lg px-6 text-[13px] transition ${activeCategory === category ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e]"}`}>
              {category}
            </button>
          ))}
        </div>

        {notice ? <div className="mt-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366]">{notice}</div> : null}

        <div className="mt-5 overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white">
          <div className="grid grid-cols-[minmax(220px,1.2fr)_minmax(260px,1.5fr)_minmax(220px,1fr)_120px] border-b border-[#f0f0f2] bg-[#fafbfc] px-5 py-3 text-[11px] text-[#8a8a8e]">
            <span>Skill名称</span><span>解决方案定位</span><span>关联能力</span><span className="text-right">操作</span>
          </div>
          {loading ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">正在读取 Skill 解决方案…</div> : null}
          {!loading && !visibleSkills.length ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">暂无{activeCategory} Skill，可点击右上角新增。</div> : null}
          {visibleSkills.map((skill) => (
            <div key={skill.id} className="grid grid-cols-[minmax(220px,1.2fr)_minmax(260px,1.5fr)_minmax(220px,1fr)_120px] items-center gap-4 border-b border-[#f5f5f7] px-5 py-4 last:border-b-0">
              <div className="min-w-0">
                <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${skill.enabled ? "bg-[#34c759]" : "bg-[#c7c7cc]"}`} /><span className="truncate text-[13px] text-[#1d1d1f]">{skill.name}</span></div>
                <div className="mt-1 truncate text-[11px] text-[#aeaeb2]">{skill.id} · v{skill.assetVersion || 1}</div>
              </div>
              <div className="line-clamp-2 text-[12px] leading-5 text-[#636366]">{skill.description}</div>
              <div className="space-y-1 text-[11px] text-[#8a8a8e]">
                <div className="flex items-center gap-1.5"><BookOpen className="h-3 w-3" />{skill.memoryRefs.length} 项记忆</div>
                <div className="flex items-center gap-1.5"><Wrench className="h-3 w-3" />{skill.toolRefs.length} 个工具</div>
              </div>
              <div className="flex justify-end gap-1">
                <button type="button" onClick={() => setDraft({ ...skill })} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label={`编辑${skill.name}`}><Pencil className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => void remove(skill)} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d93025]" aria-label={`删除${skill.name}`}><Trash2 className="h-3.5 w-3.5" /></button>
                <ChevronRight className="mt-2 h-3.5 w-3.5 text-[#d1d1d6]" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {draft ? <SkillEditor draft={draft} memoryOptions={memoryOptions} tools={tools} skills={skills} onChange={setDraft} onClose={() => setDraft(null)} onSave={() => void save()} /> : null}
    </div>
  );
}

function SkillEditor({
  draft,
  memoryOptions,
  tools,
  skills,
  onChange,
  onClose,
  onSave,
}: {
  draft: AnalysisSkillAsset;
  memoryOptions: SkillReferenceOption[];
  tools: ExternalToolAsset[];
  skills: AnalysisSkillAsset[];
  onChange: (value: AnalysisSkillAsset) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  const toolOptions = tools.map((tool) => ({
    id: tool.id,
    label: tool.name,
    meta: `${tool.provider} · ${tool.enabled ? "已接入" : "未启用"}`,
    disabled: !tool.enabled,
  }));
  const themeOptions = skills
    .filter((skill) => skill.category === "主题" && skill.id !== draft.id)
    .map((skill) => ({ id: skill.id, label: skill.name, meta: skill.description }));
  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/20 px-4" onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={`${draft.id ? "编辑" : "新增"}${draft.category} Skill`} className="flex max-h-[86vh] w-full max-w-[760px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#f0f0f2] bg-white px-6 py-4"><div><h3 className="text-[16px] text-[#1d1d1f]">{draft.id ? "编辑" : "新增"}{draft.category} Skill</h3><p className="mt-1 text-[11px] text-[#8a8a8e]">维护一套可直接进入智能分析上下文的完整方案。</p></div><button type="button" onClick={onClose} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label={`关闭${draft.category}弹窗`}><X className="h-4 w-4" /></button></div>
        <div className="grid min-h-0 gap-4 overflow-y-auto px-6 py-5">
          <Field label="名称" value={draft.name} onChange={(value) => onChange({ ...draft, name: value })} />
          <Field label="用途说明" value={draft.description} multiline onChange={(value) => onChange({ ...draft, description: value })} />
          <ReferencePicker label="对应记忆" value={draft.memoryRefs} options={memoryOptions} emptyText="知识记忆中暂无已提炼的意图、分析经验或行为习惯" onChange={(memoryRefs) => onChange({ ...draft, memoryRefs })} />
          <ReferencePicker label="可调用工具" value={draft.toolRefs} options={toolOptions} emptyText="工具调用中暂无已维护工具" onChange={(toolRefs) => onChange({ ...draft, toolRefs })} />
          <Field label="分析思路" value={draft.analysisMethod} multiline onChange={(value) => onChange({ ...draft, analysisMethod: value })} />
          {draft.category === "主题" ? <p className="-mt-2 rounded-lg bg-[#fafbfc] px-3 py-2 text-[10px] leading-5 text-[#8a8a8e]">主题 Skill 不设置固定格式；表格、柱状图、趋势图等呈现方式应跟随分析思路、数据结构和结论重点动态适配。</p> : null}
          <Field label="文档抽象思路" value={draft.documentAbstraction} multiline onChange={(value) => onChange({ ...draft, documentAbstraction: value })} />
          {draft.category === "场景" ? <Field label="格式要求" value={draft.outputFormat} multiline onChange={(value) => onChange({ ...draft, outputFormat: value })} /> : null}
          <Field label="观点生成策略" value={draft.viewpointStrategy} multiline onChange={(value) => onChange({ ...draft, viewpointStrategy: value })} />
          {draft.category === "场景" ? <ReferencePicker label="建议调用主题" value={draft.recommendedSkillIds} options={themeOptions} emptyText="暂无可建议的主题 Skill" onChange={(recommendedSkillIds) => onChange({ ...draft, recommendedSkillIds })} /> : null}
          <label className="flex items-center gap-2 text-[12px] text-[#3a3a3c]"><input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} />在智能分析中启用</label>
        </div>
        <div className="flex justify-end gap-2 border-t border-[#f0f0f2] bg-white px-6 py-4"><button type="button" onClick={onClose} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366]">取消</button><button type="button" onClick={onSave} className="h-9 rounded-lg bg-[#1d1d1f] px-5 text-[12px] text-white">保存</button></div>
      </div>
    </div>
  );
}

function ReferencePicker({
  label,
  value,
  options,
  emptyText,
  onChange,
}: {
  label: string;
  value: string[];
  options: SkillReferenceOption[];
  emptyText: string;
  onChange: (value: string[]) => void;
}) {
  const knownIds = new Set(options.map((option) => option.id));
  const missing = value.filter((id) => !knownIds.has(id));
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((item) => item !== id) : [...value, id]);
  return <div><span className="mb-2 block text-[11px] text-[#636366]">{label}</span><div className="grid grid-cols-2 gap-2">{options.map((option) => <label key={option.id} className={`flex items-start gap-2 rounded-lg border border-[#f0f0f2] p-3 text-[11px] ${option.disabled && !value.includes(option.id) ? "cursor-not-allowed opacity-45" : "text-[#3a3a3c]"}`}><input type="checkbox" checked={value.includes(option.id)} disabled={option.disabled && !value.includes(option.id)} onChange={() => toggle(option.id)} /><span className="min-w-0"><span className="block truncate text-[12px]">{option.label}</span><span className="mt-0.5 block truncate text-[#aeaeb2]">{option.meta}</span></span></label>)}{!options.length ? <div className="col-span-2 rounded-lg border border-dashed border-[#e5e5ea] px-3 py-4 text-center text-[11px] text-[#aeaeb2]">{emptyText}</div> : null}{missing.map((id) => <label key={id} className="col-span-2 flex items-center gap-2 rounded-lg border border-[#ffe0b2] bg-[#fffaf1] px-3 py-2 text-[11px] text-[#9a6200]"><input type="checkbox" checked onChange={() => toggle(id)} /><span>历史引用 {id}（当前目录已不存在）</span></label>)}</div></div>;
}

function Field({ label, value, onChange, multiline = false }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean }) {
  return <label><span className="mb-1.5 block text-[11px] text-[#636366]">{label}</span>{multiline ? <textarea value={value} onChange={(event) => onChange(event.target.value)} className="min-h-20 w-full rounded-lg border border-[#e5e5ea] px-3 py-2 text-[12px] outline-none focus:border-[#c7c7cc]" /> : <input value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-[#e5e5ea] px-3 text-[12px] outline-none focus:border-[#c7c7cc]" />}</label>;
}
