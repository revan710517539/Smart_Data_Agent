import { useEffect, useRef, useState } from "react";
import { ChevronDown, Eye, EyeOff, Pencil, Plus, Trash2, X } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import { askConfirm } from "./ui/ConfirmDialog";
import { pageVisibleAnalysisSkills } from "../services/analysisSkillCatalog";
import {
  deleteDataAssetItem,
  fetchDataAssets,
  saveDataAssetItem,
  type AnalysisShortcutAsset,
  type AnalysisExperienceAsset,
  type AnalysisSkillAsset,
  type BehaviorHabitAsset,
  type IntentAsset,
  type TopicTableAsset,
} from "../services/dataAssetApi";

const emptyShortcut: AnalysisShortcutAsset = {
  id: "",
  title: "",
  query: "",
  skillIds: [],
  tableIds: [],
  memoryIds: [],
  visible: true,
  sortOrder: 999,
  ownerUserId: "",
};

export function AnalysisConfigManager() {
  const { tenantId, userId } = usePlatformContext();
  const [shortcuts, setShortcuts] = useState<AnalysisShortcutAsset[]>([]);
  const [skills, setSkills] = useState<AnalysisSkillAsset[]>([]);
  const [topicTables, setTopicTables] = useState<TopicTableAsset[]>([]);
  const [memories, setMemories] = useState<AnalysisMemoryOption[]>([]);
  const [draft, setDraft] = useState<AnalysisShortcutAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const loadVersionRef = useRef(0);

  const load = async ({ reset = false }: { reset?: boolean } = {}) => {
    const loadVersion = ++loadVersionRef.current;
    if (reset) {
      setLoading(true);
      setShortcuts([]);
      setSkills([]);
      setTopicTables([]);
      setMemories([]);
    }
    try {
      const [bundle, knowledgeBundle] = await Promise.all([
        fetchDataAssets({ tenantId, userId }),
        fetchDataAssets({ tenantId, userId, scope: "knowledge" }),
      ]);
      const allShortcuts = bundle.analysis_shortcuts || [];
      if (loadVersion !== loadVersionRef.current) return;
      const ownedShortcuts = allShortcuts.filter((item) => item.ownerUserId === userId);
      setShortcuts(
        (ownedShortcuts.length ? ownedShortcuts : allShortcuts.filter((item) => !item.ownerUserId))
          .sort((a, b) => a.sortOrder - b.sortOrder),
      );
      setSkills(pageVisibleAnalysisSkills(knowledgeBundle.analysis_skills || []));
      setTopicTables(
        [...(bundle.topic_tables || [])].sort((a, b) =>
          a.name.localeCompare(b.name, "zh-CN") || a.code.localeCompare(b.code),
        ),
      );
      setMemories([
        ...(knowledgeBundle.intents || []).filter(isActiveMemory).map(intentToMemoryOption),
        ...(knowledgeBundle.analysis_experiences || []).filter(isActiveMemory).map(experienceToMemoryOption),
        ...(knowledgeBundle.behavior_habits || []).filter(isActiveMemory).map(habitToMemoryOption),
      ]);
    } catch (error) {
      if (loadVersion === loadVersionRef.current) setNotice(apiErrorMessage(error, "分析配置加载失败"));
    } finally {
      if (loadVersion === loadVersionRef.current) setLoading(false);
    }
  };

  useEffect(() => {
    void load({ reset: true });
    return () => {
      loadVersionRef.current += 1;
    };
  }, [tenantId, userId]);

  const save = async (value: AnalysisShortcutAsset): Promise<string | null> => {
    if (!value.title.trim() || !value.query.trim()) {
      return "请填写快捷键名称和分析问题。";
    }
    try {
      const availableSkillIds = new Set(skills.map((skill) => skill.id));
      await saveDataAssetItem({
        tenantId,
        userId,
        itemType: "analysis_shortcut",
        item: {
          ...value,
          ownerUserId: value.ownerUserId || userId,
          skillIds: value.skillIds.filter((skillId) => availableSkillIds.has(skillId)),
        },
      });
      setDraft(null);
      setNotice("分析快捷键已保存。");
      await load();
      return null;
    } catch (error) {
      const message = apiErrorMessage(error, "分析配置保存失败");
      setNotice(message);
      return message;
    }
  };

  const remove = async (item: AnalysisShortcutAsset) => {
    if (!(await askConfirm({ title: "删除分析配置", description: `确定删除「${item.title}」？`, hint: "此操作不可撤销。" }))) return;
    try {
      await deleteDataAssetItem({ tenantId, userId, itemType: "analysis_shortcut", itemId: item.id });
      setNotice("分析快捷键已删除。");
      await load();
    } catch (error) {
      setNotice(apiErrorMessage(error, "分析配置删除失败"));
    }
  };

  return (
    <div className="min-h-full bg-[#f8f8fa] p-7">
      <div className="w-full">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">分析配置</h2>
            <p className="mt-1 text-[13px] text-[#8a8a8e]">维护智能分析输入框下方的快捷键；只有勾选展示的配置才会出现在查询页。</p>
          </div>
          <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">
            <button
              type="button"
              onClick={() => setDraft({ ...emptyShortcut, ownerUserId: userId })}
              disabled={loading}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white disabled:cursor-wait disabled:opacity-50"
            >
              <Plus className="h-3.5 w-3.5" />新增分析配置
            </button>
          </div>
        </div>
        {notice ? <div className="mt-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366]">{notice}</div> : null}
        <div className="mt-6 overflow-hidden rounded-2xl border border-[#e5e5ea] bg-white">
          <div className="grid grid-cols-[minmax(200px,1fr)_minmax(320px,1.8fr)_minmax(220px,1fr)_100px_120px] border-b border-[#f0f0f2] bg-[#fafbfc] px-5 py-3 text-[11px] text-[#8a8a8e]">
            <span>快捷键名称</span><span>分析问题</span><span>绑定Skill</span><span>展示</span><span className="text-right">操作</span>
          </div>
          {loading ? <AnalysisConfigSkeleton /> : null}
          {!loading && shortcuts.map((item) => (
            <div key={item.id} className="grid grid-cols-[minmax(200px,1fr)_minmax(320px,1.8fr)_minmax(220px,1fr)_100px_120px] items-center gap-4 border-b border-[#f5f5f7] px-5 py-4 last:border-b-0">
              <div className="text-[13px] text-[#1d1d1f]">{item.title}</div>
              <div className="line-clamp-2 text-[12px] leading-5 text-[#636366]">{item.query}</div>
              <div className="flex flex-wrap gap-1">
                {item.skillIds
                  .map((id) => skills.find((skill) => skill.id === id))
                  .filter((skill): skill is AnalysisSkillAsset => Boolean(skill))
                  .map((skill) => <span key={skill.id} className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[10px] text-[#636366]">{skill.name}</span>)}
              </div>
              <button
                type="button"
                onClick={() => void save({ ...item, visible: !item.visible })}
                className={`inline-flex w-fit items-center gap-1 rounded-full px-2.5 py-1 text-[10px] ${item.visible ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"}`}
              >
                {item.visible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}{item.visible ? "已展示" : "已隐藏"}
              </button>
              <div className="flex justify-end gap-1">
                <button type="button" onClick={() => setDraft({ ...item })} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]" aria-label={`编辑${item.title}`}><Pencil className="h-3.5 w-3.5" /></button>
                <button type="button" onClick={() => void remove(item)} className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d93025]" aria-label={`删除${item.title}`}><Trash2 className="h-3.5 w-3.5" /></button>
              </div>
            </div>
          ))}
          {!loading && !shortcuts.length ? <div className="px-5 py-14 text-center text-[12px] text-[#aeaeb2]">暂无分析快捷键。</div> : null}
        </div>
      </div>
      {draft ? (
        <ShortcutEditor
          draft={draft}
          skills={skills}
          topicTables={topicTables}
          memories={memories}
          onClose={() => setDraft(null)}
          onSave={save}
        />
      ) : null}
    </div>
  );
}

function AnalysisConfigSkeleton() {
  return <div aria-label="正在读取分析配置" className="animate-pulse">
    {Array.from({ length: 4 }, (_, index) => (
      <div key={index} className="grid grid-cols-[minmax(200px,1fr)_minmax(320px,1.8fr)_minmax(220px,1fr)_100px_120px] items-center gap-4 border-b border-[#f5f5f7] px-5 py-4 last:border-b-0">
        <span className="h-3 w-28 rounded bg-[#ececf0]" />
        <span className="h-3 w-4/5 rounded bg-[#f0f0f2]" />
        <span className="h-6 w-24 rounded-md bg-[#f0f0f2]" />
        <span className="h-6 w-14 rounded-full bg-[#f0f0f2]" />
        <span className="ml-auto h-7 w-16 rounded-md bg-[#f0f0f2]" />
      </div>
    ))}
  </div>;
}

function ShortcutEditor({
  draft: initial,
  skills,
  topicTables,
  memories,
  onClose,
  onSave,
}: {
  draft: AnalysisShortcutAsset;
  skills: AnalysisSkillAsset[];
  topicTables: TopicTableAsset[];
  memories: AnalysisMemoryOption[];
  onClose: () => void;
  onSave: (value: AnalysisShortcutAsset) => Promise<string | null>;
}) {
  const [draft, setDraft] = useState(initial);
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const selectedTopicTables = draft.tableIds
    .map((id) => topicTables.find((table) => table.id === id))
    .filter((table): table is TopicTableAsset => Boolean(table));
  const selectedMemories = (draft.memoryIds || [])
    .map((id) => memories.find((memory) => memory.id === id))
    .filter((memory): memory is AnalysisMemoryOption => Boolean(memory));
  const toggleSkill = (id: string) => setDraft({
    ...draft,
    skillIds: draft.skillIds.includes(id) ? draft.skillIds.filter((item) => item !== id) : [...draft.skillIds, id],
  });
  const toggleTable = (id: string) => setDraft({
    ...draft,
    tableIds: draft.tableIds.includes(id) ? draft.tableIds.filter((item) => item !== id) : [...draft.tableIds, id],
  });
  const toggleMemory = (id: string) => setDraft({
    ...draft,
    memoryIds: (draft.memoryIds || []).includes(id)
      ? (draft.memoryIds || []).filter((item) => item !== id)
      : [...(draft.memoryIds || []), id],
  });
  const save = async () => {
    if (saving) return;
    setSaveError("");
    setSaving(true);
    const error = await onSave(draft);
    if (error) setSaveError(error);
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/20 px-4" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${draft.id ? "编辑" : "新增"}分析配置`}
        className="flex max-h-[86vh] w-full max-w-[760px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-6 py-4">
          <div>
            <h3 className="text-[16px] text-[#1d1d1f]">{draft.id ? "编辑" : "新增"}分析配置</h3>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">快捷键只由这里维护，不会因执行一次分析自动新增。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-[#8a8a8e]" aria-label="关闭编辑分析配置"><X className="h-4 w-4" /></button>
        </div>
        <div className="grid min-h-0 gap-4 overflow-y-auto px-6 py-5">
          <label>
            <span className="mb-1.5 block text-[11px] text-[#636366]">快捷键名称</span>
            <input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} className="h-9 w-full rounded-lg border border-[#e5e5ea] px-3 text-[12px] outline-none focus:border-[#aeaeb2]" />
          </label>
          <label>
            <span className="mb-1.5 block text-[11px] text-[#636366]">点击后提交的分析问题</span>
            <textarea value={draft.query} onChange={(event) => setDraft({ ...draft, query: event.target.value })} className="min-h-24 w-full rounded-lg border border-[#e5e5ea] px-3 py-2 text-[12px] outline-none focus:border-[#aeaeb2]" />
          </label>
          <div>
            <span className="mb-1.5 block text-[11px] text-[#636366]">分析记忆</span>
            <details className="group relative">
              <summary aria-label="选择分析记忆" className="flex h-10 cursor-pointer list-none items-center justify-between gap-3 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#aeaeb2] [&::-webkit-details-marker]:hidden">
                <span className={`min-w-0 truncate ${selectedMemories.length ? "text-[#1d1d1f]" : "text-[#aeaeb2]"}`}>
                  {selectedMemories.length ? selectedMemories.map((memory) => memory.label).join("、") : "请选择意图、分析经验或行为习惯"}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-[#8a8a8e]">
                  {selectedMemories.length ? `已选 ${selectedMemories.length}` : null}
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                </span>
              </summary>
              <div className="absolute left-0 right-0 z-30 mt-1 max-h-64 overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white p-1.5 shadow-xl">
                {memories.length ? memories.map((memory) => (
                  <label key={memory.id} className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 hover:bg-[#f8f8fa]">
                    <input type="checkbox" checked={(draft.memoryIds || []).includes(memory.id)} onChange={() => toggleMemory(memory.id)} className="mt-0.5" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 text-[12px] text-[#1d1d1f]"><span className="truncate">{memory.label}</span><span className="shrink-0 rounded bg-[#eef8f1] px-1.5 py-0.5 text-[9px] text-[#258a3f]">{memory.kind}</span></span>
                      <span className="mt-0.5 block truncate text-[10px] text-[#aeaeb2]">{memory.description}</span>
                    </span>
                  </label>
                )) : <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">知识记忆中暂无可直接用于分析的记忆</div>}
              </div>
            </details>
            <p className="mt-1.5 text-[10px] text-[#aeaeb2]">这里只保存记忆 ID；知识记忆中的名称和内容更新后会自动同步到本配置。</p>
          </div>
          <div>
            <span className="mb-1.5 block text-[11px] text-[#636366]">分析所用数据源（主题表）</span>
            <details className="group relative">
              <summary
                aria-label="选择分析所用数据源"
                className="flex h-10 cursor-pointer list-none items-center justify-between gap-3 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#aeaeb2] [&::-webkit-details-marker]:hidden"
              >
                <span className={`min-w-0 truncate ${selectedTopicTables.length ? "text-[#1d1d1f]" : "text-[#aeaeb2]"}`}>
                  {selectedTopicTables.length ? selectedTopicTables.map((table) => table.name).join("、") : "请选择已注册的主题表"}
                </span>
                <span className="flex shrink-0 items-center gap-2 text-[#8a8a8e]">
                  {selectedTopicTables.length ? `已选 ${selectedTopicTables.length}` : null}
                  <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                </span>
              </summary>
              <div className="absolute left-0 right-0 z-20 mt-1 max-h-64 overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white p-1.5 shadow-xl">
                {topicTables.length ? topicTables.map((table) => (
                  <label key={table.id} className="flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 hover:bg-[#f8f8fa]">
                    <input type="checkbox" checked={draft.tableIds.includes(table.id)} onChange={() => toggleTable(table.id)} className="mt-0.5" />
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2 text-[12px] text-[#1d1d1f]">
                        <span className="truncate">{table.name}</span>
                        <span className="shrink-0 rounded bg-[#f2f2f7] px-1.5 py-0.5 text-[9px] text-[#8a8a8e]">{topicTableStatusLabel(table.lifecycleStatus)}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-[10px] text-[#aeaeb2]">{table.code}{table.description ? ` · ${table.description}` : ""}</span>
                    </span>
                  </label>
                )) : <div className="px-3 py-8 text-center text-[11px] text-[#aeaeb2]">主题表中暂无已注册数据表</div>}
              </div>
            </details>
            <p className="mt-1.5 text-[10px] text-[#aeaeb2]">可多选；点击此快捷键时，所选主题表会作为本次分析的数据上下文。</p>
          </div>
          <div>
            <span className="mb-2 block text-[11px] text-[#636366]">绑定 Skill 解决方案</span>
            <div className="grid grid-cols-2 gap-2">
              {skills.map((skill) => (
                <label key={skill.id} className="flex items-start gap-2 rounded-lg border border-[#f0f0f2] p-3 text-[11px] text-[#3a3a3c]">
                  <input type="checkbox" checked={draft.skillIds.includes(skill.id)} onChange={() => toggleSkill(skill.id)} />
                  <span><span className="block text-[12px]">{skill.name}</span><span className="mt-0.5 block text-[#aeaeb2]">{skill.category}</span></span>
                </label>
              ))}
            </div>
            {!skills.length ? <p className="text-[11px] text-[#aeaeb2]">Skill 插件中暂无可用解决方案。</p> : null}
          </div>
          <label className="flex items-center gap-2 text-[12px] text-[#3a3a3c]">
            <input type="checkbox" checked={draft.visible} onChange={(event) => setDraft({ ...draft, visible: event.target.checked })} />展示在智能分析输入框下方
          </label>
        </div>
        <div className="flex items-center justify-between gap-4 border-t border-[#f0f0f2] px-6 py-4">
          <p role="alert" className="min-w-0 text-[11px] text-[#d93025]">{saveError}</p>
          <div className="flex shrink-0 gap-2">
            <button type="button" onClick={onClose} disabled={saving} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366] disabled:cursor-not-allowed disabled:opacity-50">取消</button>
            <button type="button" onClick={() => void save()} disabled={saving} className="h-9 rounded-lg bg-[#1d1d1f] px-5 text-[12px] text-white disabled:cursor-not-allowed disabled:opacity-50">{saving ? "保存中…" : "保存"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}

type AnalysisMemoryOption = {
  id: string;
  label: string;
  kind: "意图" | "分析经验" | "行为习惯";
  description: string;
};

function intentToMemoryOption(item: IntentAsset): AnalysisMemoryOption {
  return { id: item.id, label: `${item.scenario} / ${item.purpose}`, kind: "意图", description: item.description };
}

function experienceToMemoryOption(item: AnalysisExperienceAsset): AnalysisMemoryOption {
  return { id: item.id, label: item.title || item.name, kind: "分析经验", description: item.description || item.steps || item.analysisSteps || "" };
}

function habitToMemoryOption(item: BehaviorHabitAsset): AnalysisMemoryOption {
  return { id: item.id, label: item.title, kind: "行为习惯", description: item.description };
}

function isActiveMemory(item: IntentAsset | AnalysisExperienceAsset | BehaviorHabitAsset) {
  return !item.lifecycleStatus || item.lifecycleStatus === "active";
}

function topicTableStatusLabel(status: TopicTableAsset["lifecycleStatus"]) {
  const labels: Record<NonNullable<TopicTableAsset["lifecycleStatus"]>, string> = {
    draft: "草稿",
    review: "待审核",
    active: "已生效",
    rejected: "已驳回",
    archived: "已归档",
  };
  return status ? labels[status] : "已注册";
}
