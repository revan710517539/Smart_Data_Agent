import { useEffect, useState } from "react";
import { BookOpen, ChevronRight, Eye, EyeOff, Pencil, Plus, Trash2, Wrench } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  deleteDataAssetItem,
  fetchDataAssets,
  saveDataAssetItem,
  type AnalysisSkillAsset,
  type ExternalToolAsset,
} from "../services/dataAssetApi";
import { apiErrorMessage } from "../services/apiClient";
import { askConfirm } from "./ui/ConfirmDialog";
import { analysisSkillDisplayLocation, displayedAnalysisSkills } from "../services/analysisSkillCatalog";
import { operatingTenantNames } from "../data/operatingTenants";
import { DataPageSelector, useClientPagination } from "./ui/DataPageSelector";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "./ui/FormDialog";

const coreTopicSkills = [
  { id: "topic-descriptive", label: "描述性分析" },
  { id: "topic-attribution", label: "归因分析" },
  { id: "topic-predictive", label: "预测分析" },
] as const;

function canonicalCoreTopicId(name: string) {
  const normalized = name.trim();
  return coreTopicSkills.find(({ label }) => normalized === label || operatingTenantNames.some((institution) => normalized === `${institution}${label}`))?.id || "";
}

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
  displayLocation: "intelligent_analysis",
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
      // Skills use only governed knowledge/configuration assets.  They must not
      // disappear while the selected institution's CSV catalog is refreshing.
      const bundle = await fetchDataAssets({ tenantId, userId, scope: "knowledge" });
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

  const visibleSkills = displayedAnalysisSkills(skills).filter((skill) => skill.category === activeCategory);
  const skillPagination = useClientPagination(visibleSkills);

  const save = async () => {
    if (!draft?.name.trim() || !draft.description.trim()) {
      setNotice("请填写 Skill 名称和用途说明。");
      return;
    }
    const canonicalTopicId = draft.category === "主题" ? canonicalCoreTopicId(draft.name) : "";
    if (canonicalTopicId && draft.id !== canonicalTopicId) {
      const canonical = coreTopicSkills.find((item) => item.id === canonicalTopicId);
      setNotice(`${canonical?.label || "该分析方法"}已存在，请编辑通用 Skill；机构差异应沉淀到 Memory，不再新增机构 Skill。`);
      return;
    }
    try {
      await saveDataAssetItem({
        tenantId,
        userId,
        itemType: "analysis_skill",
        item: normalizeDraftReferences(draft, memoryOptions, tools),
      });
      setDraft(null);
      setNotice("Skill 解决方案已保存。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "Skill 保存失败"));
    }
  };

  const remove = async (skill: AnalysisSkillAsset) => {
    if (!(await askConfirm({ title: "删除 Skill", description: `确定删除「${skill.name}」？`, hint: "此操作不可撤销。" }))) return;
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
            <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">skill/插件</h2>
            <p className="mt-1 text-[13px] text-[#8a8a8e]">将提炼后的意图、分析经验、行为习惯与工具、分析方法组合为可复用解决方案；知识文件不会被 Skill 直接引用。</p>
          </div>
          <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">
            <button type="button" onClick={() => setDraft(emptySkill(activeCategory))} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e]">
              <Plus className="h-3.5 w-3.5" />新增{activeCategory}
            </button>
          </div>
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
          <div className="flex items-center justify-between border-b border-[#f0f0f2] bg-[#fafbfc] px-5 py-2">
            <div className="grid flex-1 grid-cols-[minmax(220px,1.2fr)_minmax(260px,1.5fr)_minmax(190px,1fr)_100px_120px] items-center gap-4 text-[11px] text-[#8a8a8e]"><span>Skill名称</span><span>解决方案定位</span><span>关联能力</span><span>展示</span><span className="text-right">操作</span></div>
            {skillPagination.paginated && <DataPageSelector page={skillPagination.page} totalPages={skillPagination.totalPages} shownCount={skillPagination.items.length} totalCount={skillPagination.total} onChange={skillPagination.setPage} ariaLabel="Skill分页" compact />}
          </div>
          {loading ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">正在读取 Skill 解决方案…</div> : null}
          {!loading && !visibleSkills.length ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">暂无{activeCategory} Skill，可点击右上角新增。</div> : null}
          {skillPagination.items.map((skill) => {
            const availableMemoryCount = skill.memoryRefs.length;
            const availableToolCount = skill.toolRefs.filter((id) => tools.some((tool) => tool.id === id && tool.enabled)).length;
            const isPageVisible = analysisSkillDisplayLocation(skill) === "intelligent_analysis";
            return <div key={skill.id} className="grid grid-cols-[minmax(220px,1.2fr)_minmax(260px,1.5fr)_minmax(190px,1fr)_100px_120px] items-center gap-4 border-b border-[#f5f5f7] px-5 py-4 last:border-b-0">
              <div className="min-w-0">
                <div className="flex items-center gap-2"><span className={`h-2 w-2 rounded-full ${skill.enabled ? "bg-[#34c759]" : "bg-[#c7c7cc]"}`} /><span className="truncate text-[13px] text-[#1d1d1f]">{skill.name}</span></div>
                <div className="mt-1 truncate text-[11px] text-[#aeaeb2]">{skill.id} · v{skill.assetVersion || 1}</div>
              </div>
              <div className="line-clamp-2 text-[12px] leading-5 text-[#636366]">{skill.description}</div>
              <div className="space-y-1 text-[11px] text-[#8a8a8e]">
                <div className="flex items-center gap-1.5"><BookOpen className="h-3 w-3" />{availableMemoryCount} 项记忆</div>
                <div className="flex items-center gap-1.5"><Wrench className="h-3 w-3" />{availableToolCount} 个工具</div>
              </div>
              <span className={`inline-flex w-fit items-center gap-1 rounded-full px-2.5 py-1 text-[10px] ${isPageVisible ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`} data-skill-display-status={skill.id}>
                {isPageVisible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}{isPageVisible ? "展示" : "不展示"}
              </span>
              <div className="flex justify-end gap-1">
                <button type="button" onClick={() => setDraft(normalizeDraftReferences(skill, memoryOptions, tools))} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]" aria-label={`编辑${skill.name}`}><Pencil className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => void remove(skill)} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d93025]" aria-label={`删除${skill.name}`}><Trash2 className="h-3.5 w-3.5" /></button>
                <ChevronRight className="mt-2 h-3.5 w-3.5 text-[#d1d1d6]" />
              </div>
            </div>
          })}
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
  const toolOptions = tools.filter((tool) => tool.enabled).map((tool) => ({
    id: tool.id,
    label: tool.name,
    meta: `${tool.provider} · 已接入`,
  }));
  const themeOptions = skills
    .filter((skill) => skill.category === "主题" && skill.id !== draft.id)
    .map((skill) => ({ id: skill.id, label: skill.name, meta: skill.description }));
  return (
    <FormDialog
      title={`${draft.id ? "编辑" : "新增"}${draft.category} Skill`}
      description="维护一套可直接进入智能分析上下文的完整方案。"
      ariaLabel={`${draft.id ? "编辑" : "新增"}${draft.category} Skill`}
      onClose={onClose}
      widthClassName="max-w-[760px]"
      zIndexClassName="z-[90]"
      bodyClassName="grid gap-4"
      footer={<><FormDialogCancelButton onClick={onClose}>取消</FormDialogCancelButton><FormDialogPrimaryButton onClick={onSave}>保存</FormDialogPrimaryButton></>}
    >
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
          <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
            <label className="flex items-center gap-2 text-[12px] text-[#3a3a3c]"><input type="checkbox" checked={draft.enabled} onChange={(event) => onChange({ ...draft, enabled: event.target.checked })} data-skill-runtime-enabled={draft.id || "new"} />启用 Skill 运行时能力</label>
            <label className="flex items-center gap-2 text-[12px] text-[#3a3a3c]"><input type="checkbox" checked={analysisSkillDisplayLocation(draft) === "intelligent_analysis"} onChange={(event) => onChange({ ...draft, displayLocation: event.target.checked ? "intelligent_analysis" : "hidden" })} data-skill-intelligent-analysis-visible={draft.id || "new"} />展示在智能分析页面</label>
          </div>
    </FormDialog>
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
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((item) => item !== id) : [...value, id]);
  return <div><span className="mb-2 block text-[11px] text-[#636366]">{label}</span><div className="grid grid-cols-2 gap-2">{options.map((option) => <label key={option.id} className="flex items-start gap-2 rounded-lg border border-[#f0f0f2] p-3 text-[11px] text-[#3a3a3c]"><input type="checkbox" checked={value.includes(option.id)} onChange={() => toggle(option.id)} /><span className="min-w-0"><span className="block truncate text-[12px]">{option.label}</span><span className="mt-0.5 block truncate text-[#aeaeb2]">{option.meta}</span></span></label>)}{!options.length ? <div className="col-span-2 rounded-lg border border-dashed border-[#e5e5ea] px-3 py-4 text-center text-[11px] text-[#aeaeb2]">{emptyText}</div> : null}</div></div>;
}

function normalizeDraftReferences(
  draft: AnalysisSkillAsset,
  memoryOptions: SkillReferenceOption[],
  tools: ExternalToolAsset[],
): AnalysisSkillAsset {
  const memoryIds = new Set(memoryOptions.map((option) => option.id));
  const enabledToolIds = new Set(tools.filter((tool) => tool.enabled).map((tool) => tool.id));
  return {
    ...draft,
    memoryRefs: draft.memoryRefs.filter((id) => memoryIds.has(id) || id.startsWith("learned-")),
    toolRefs: draft.toolRefs.filter((id) => enabledToolIds.has(id)),
    outputFormat: draft.category === "主题" ? "" : draft.outputFormat,
  };
}

function Field({ label, value, onChange, multiline = false }: { label: string; value: string; onChange: (value: string) => void; multiline?: boolean }) {
  return <label><span className="mb-1.5 block text-[11px] text-[#636366]">{label}</span>{multiline ? <textarea value={value} onChange={(event) => onChange(event.target.value)} className="min-h-20 w-full rounded-lg border border-[#e5e5ea] px-3 py-2 text-[12px] outline-none focus:border-[#c7c7cc]" /> : <input value={value} onChange={(event) => onChange(event.target.value)} className="h-9 w-full rounded-lg border border-[#e5e5ea] px-3 text-[12px] outline-none focus:border-[#c7c7cc]" />}</label>;
}
