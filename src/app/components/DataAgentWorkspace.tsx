import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocation } from "react-router";
import {
  BrainCircuit,
  Play,
  Clock,
  CheckCircle2,
  AlertCircle,
  ArrowUpRight,
  ChevronDown,
  Plus,
  Pencil,
  Trash2,
  Zap,
  FileText,
  Bell,
  TrendingUp,
  Search,
  Target,
  RefreshCw,
  Eye,
  X,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { createClientUuid } from "../utils/clientUuid";
import {
  createAutomationTask,
  fetchAutomationWorkspace,
  triggerAutomationTask,
  updateAutomationTask,
  type AutomationRun,
  type AutomationTask,
} from "../services/automationApi";
import {
  fetchDataAssets,
  type AnalysisSkillAsset,
  type KnowledgeFileAsset,
  type TopicTableAsset,
} from "../services/dataAssetApi";
import { fetchMetricDictionary } from "../services/metricDictionaryApi";
import { pageVisibleAnalysisSkills } from "../services/analysisSkillCatalog";
import type { MetricDictionaryItem } from "../data/metricDictionary";
import { fetchSystemConfig, type ModelIntegration } from "../services/systemConfigApi";
import { fetchPlatformCapabilities, type PlatformCapabilityResponse } from "../services/capabilitiesApi";
import { TodoWorkspace } from "./TodoWorkspace";
import { DataPageSelector, useClientPagination } from "./ui/DataPageSelector";

type AgentTaskStatus = "ready" | "running" | "completed" | "alert" | "paused" | "terminated";
type AutomationKind = "memory" | "automatic_analysis";
type MemoryOutputType = "analysis_experience" | "intent" | "analysis_habit" | "operation_habit" | "reporting_habit";

type AgentTask = {
  id: string;
  name: string;
  type: string;
  schedule: string;
  status: AgentTaskStatus;
  lastRun: string;
  result: string;
  description: string;
  ownerUserId?: string;
  createdBy?: string;
  createdAt?: string;
  updatedAt?: string;
  definitionStatus?: "active" | "paused" | "disabled";
  lockVersion?: number;
  taskCode?: string;
  handlerRef?: string;
  taskConfig?: Record<string, unknown>;
  systemManaged?: boolean;
  recentRuns: AutomationRun[];
};

type AgentTaskFormState = {
  name: string;
  type: string;
  schedule: string;
  status: "active" | "paused" | "disabled";
  lastRun: string;
  result: string;
  description: string;
  automationKind: AutomationKind;
  sourceIds: string[];
  outputTypes: MemoryOutputType[];
  prompt: string;
  selectedMetricIds: string[];
  skillId: string;
  modelIntegrationId: string;
  selectedModelName: string;
  anomalyComparison: "relative_change" | "absolute_change" | "above" | "below";
  anomalyThreshold: string;
  anomalyDirection: "both" | "up" | "down";
  anomalyMatchMode: "any" | "all";
  lookbackPeriods: string;
  recentRuns: AutomationRun[];
};

type AutomaticAnalysisMetricContext = {
  optionId: string;
  metricId: string;
  metricName: string;
  metricCode: string;
  datasetId: string;
  tableId: string;
  tableCode: string;
  sourceTable: string;
  description: string;
  definition: string;
  valueLogic: string;
  dimension: string;
  timeDimension: string;
};

const agentTaskStatusConfig: Record<AgentTaskStatus, { label: string; color: string; bg: string }> = {
  ready: { label: "待运行", color: "#636366", bg: "#636366" },
  running: { label: "运行中", color: "#34c759", bg: "#34c759" },
  completed: { label: "已完成", color: "#8e8e93", bg: "#8e8e93" },
  alert: { label: "预警中", color: "#ff3b30", bg: "#ff3b30" },
  paused: { label: "已暂停", color: "#ff9500", bg: "#ff9500" },
  terminated: { label: "已终止", color: "#8e8e93", bg: "#8e8e93" },
};

const memoryOutputLabels: Record<MemoryOutputType, string> = {
  analysis_experience: "分析经验",
  intent: "意图管理",
  analysis_habit: "分析习惯",
  operation_habit: "运营习惯",
  reporting_habit: "汇报习惯",
};

const DEFAULT_MEMORY_PROMPT = "从所选知识文件的当前版本中，提炼会改变后续判断、分析方法或运营动作的本质信息。删除背景复述、常识、套话、表层摘要和同义重复；没有足够证据时不要生成记忆。";
const DEFAULT_AUTOMATIC_ANALYSIS_PROMPT = "当监控指标命中异动规则时，结合指标所在数据表、指标描述、统计口径、所选 Skill 和实际查询证据进行归因分析，说明异动表现、可能原因、证据边界、影响与建议动作。";
const taskControlClass = "h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#1d1d1f] outline-none focus:border-[#c7c7cc] disabled:cursor-not-allowed disabled:bg-[#fafbfc] disabled:text-[#636366]";
const taskSelectClass = `${taskControlClass} appearance-none pr-8`;
const taskAreaClass = "min-h-20 w-full resize-y rounded-lg border border-[#e5e5ea] bg-white px-3 py-2 text-[12px] leading-5 text-[#1d1d1f] outline-none focus:border-[#c7c7cc] disabled:cursor-not-allowed disabled:bg-[#fafbfc]";

function TaskSelect({
  "aria-label": ariaLabel,
  value,
  disabled,
  onChange,
  children,
}: {
  "aria-label": string;
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  return (
    <div className="relative">
      <select
        aria-label={ariaLabel}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className={taskSelectClass}
      >
        {children}
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#8a8a8e]" />
    </div>
  );
}

type AgentSection = "tasks" | "todos" | "skills";

function getAgentSection(pathname: string): AgentSection {
  if (pathname.endsWith("/skills")) return "skills";
  if (pathname.endsWith("/todos")) return "todos";
  return "tasks";
}

export function DataAgentWorkspace() {
  const location = useLocation();
  const { tenantId, userId, userName, isSuperAdmin } = usePlatformContext();
  const activeTab = getAgentSection(location.pathname);
  const [todoComposerRequest, setTodoComposerRequest] = useState(0);
  const [todoToolbarLeftHost, setTodoToolbarLeftHost] = useState<HTMLDivElement | null>(null);
  const [todoToolbarRightHost, setTodoToolbarRightHost] = useState<HTMLDivElement | null>(null);
  const headerCopy: Record<AgentSection, { title: string; subtitle: string; action: string }> = {
    todos: {
      title: "待办任务",
      subtitle: "个人待办 · 团队日程 · 系统注入任务统一管理",
      action: "新建待办",
    },
    tasks: {
      title: "自动化任务",
      subtitle: "统一管理主题数据加工、知识记忆提取与指标自动分析任务",
      action: "新建任务",
    },
    skills: {
      title: "skill/插件",
      subtitle: "管理可应用于智能分析、市场洞察、经营分析和多机构分析的分析技能",
      action: "加载插件",
    },
  };
  const header = headerCopy[activeTab];
  const showHeaderAction = header.action !== "新建任务";

  const [workspaceTasks, setWorkspaceTasks] = useState<AgentTask[]>([]);
  const [capabilities, setCapabilities] = useState<PlatformCapabilityResponse | null>(null);
  const [workspaceNotice, setWorkspaceNotice] = useState("正在读取服务端任务与能力状态…");
  const [taskModalOpen, setTaskModalOpen] = useState(false);
  const [taskModalMode, setTaskModalMode] = useState<"create" | "detail" | "edit">("create");
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [taskForm, setTaskForm] = useState<AgentTaskFormState>(() => emptyTaskForm());
  const [pendingDeleteTask, setPendingDeleteTask] = useState<AgentTask | null>(null);
  const [deletingTask, setDeletingTask] = useState(false);
  const [knowledgeFiles, setKnowledgeFiles] = useState<KnowledgeFileAsset[]>([]);
  const [topicTables, setTopicTables] = useState<TopicTableAsset[]>([]);
  const [analysisSkills, setAnalysisSkills] = useState<AnalysisSkillAsset[]>([]);
  const [metricDictionary, setMetricDictionary] = useState<MetricDictionaryItem[]>([]);
  const [analysisModels, setAnalysisModels] = useState<ModelIntegration[]>([]);

  useEffect(() => {
    if (activeTab !== "tasks") return;
    let cancelled = false;
    setWorkspaceNotice("正在读取服务端任务与能力状态…");
    const loadTasks = async () => {
      try {
        const [automation, capabilityResponse] = await Promise.all([
          fetchAutomationWorkspace({ tenantId, userId }),
          fetchPlatformCapabilities({ tenantId, userId }),
        ]);
        if (cancelled) return;
        setWorkspaceTasks(mapAutomationTasks(automation.tasks, automation.runs));
        setCapabilities(capabilityResponse);
        setWorkspaceNotice(
          `已连接持久化任务运行时：${automation.tasks.length} 个定义，${automation.runs.length} 条执行记录`,
        );
      } catch (error) {
        if (!cancelled) {
          setWorkspaceTasks([]);
          setCapabilities(null);
          setWorkspaceNotice(error instanceof Error ? `任务工作台不可用：${error.message}` : "任务工作台不可用");
        }
      }
    };
    const loadAcquisitionContext = async () => {
      const [assets, settings, metrics] = await Promise.allSettled([
        fetchDataAssets({ tenantId, userId }),
        fetchSystemConfig({ tenantId, userId }),
        fetchMetricDictionary({ tenantId, userId }),
      ]);
      if (cancelled) return;
      setKnowledgeFiles(assets.status === "fulfilled" ? assets.value.knowledge_files || [] : []);
      setTopicTables(assets.status === "fulfilled" ? assets.value.topic_tables || [] : []);
      setAnalysisSkills(assets.status === "fulfilled" ? pageVisibleAnalysisSkills(assets.value.analysis_skills || []) : []);
      setAnalysisModels(settings.status === "fulfilled" ? settings.value.models || [] : []);
      setMetricDictionary(metrics.status === "fulfilled" ? metrics.value.metrics || [] : []);
    };
    void loadTasks();
    void loadAcquisitionContext();
    return () => {
      cancelled = true;
    };
  }, [activeTab, tenantId, userId]);

  const automationTasks = workspaceTasks;
  const automaticAnalysisMetrics = useMemo(
    () => buildAutomaticAnalysisMetricOptions(topicTables, metricDictionary),
    [metricDictionary, topicTables],
  );
  const taskSummary = useMemo(
    () => ({
      active: workspaceTasks.filter((task) => task.definitionStatus === "active").length,
      paused: workspaceTasks.filter((task) => task.definitionStatus === "paused").length,
      terminated: workspaceTasks.filter((task) => task.definitionStatus === "disabled").length,
      succeeded: workspaceTasks.filter((task) => task.recentRuns?.[0]?.status === "succeeded").length,
    }),
    [workspaceTasks],
  );

  const openTaskCreate = () => {
    setTaskModalMode("create");
    setEditingTaskId(null);
    setTaskForm(emptyTaskForm());
    setTaskModalOpen(true);
  };

  const openTaskDetail = (task: AgentTask) => {
    setTaskModalMode("detail");
    setEditingTaskId(task.id);
    setTaskForm(taskToForm(task));
    setTaskModalOpen(true);
  };

  const openTaskEdit = (task: AgentTask) => {
    setTaskModalMode("edit");
    setEditingTaskId(task.id);
    setTaskForm(taskToForm(task));
    setTaskModalOpen(true);
  };

  const closeTaskModal = () => {
    setTaskModalOpen(false);
    setEditingTaskId(null);
  };

  const saveTask = async () => {
    const name = taskForm.name.trim();
    if (!name) return;
    if (taskForm.automationKind === "memory" && (!taskForm.sourceIds.length || !taskForm.outputTypes.length || !taskForm.prompt.trim())) {
      setWorkspaceNotice("记忆提取任务必须选择知识文件、输出类别并填写 Prompt。");
      return;
    }
    if (taskForm.automationKind === "automatic_analysis" && (
      !taskForm.selectedMetricIds.length
      || !taskForm.skillId
      || !taskForm.modelIntegrationId
      || !taskForm.selectedModelName
      || !taskForm.prompt.trim()
      || !isValidNonNegativeNumber(taskForm.anomalyThreshold)
    )) {
      setWorkspaceNotice("自动分析任务必须选择指标、Skill、Data_Agent 模型，并填写 Prompt 与有效异动阈值。");
      return;
    }
    const existing = editingTaskId ? workspaceTasks.find((task) => task.id === editingTaskId) : undefined;
    try {
      const definition = taskFormToAutomationDefinition(taskForm, existing, automaticAnalysisMetrics, analysisSkills);
      if (existing) {
        await updateAutomationTask({
          tenantId,
          userId,
          taskId: existing.id,
          expectedLockVersion: Number(existing.lockVersion || 0),
          patch: definition,
        });
      } else {
        await createAutomationTask({ tenantId, userId, definition });
      }
      closeTaskModal();
      await refreshWorkspace();
      setWorkspaceNotice(existing ? "任务定义已由服务端校验并更新" : "任务定义已由服务端创建；运行状态仅由 Worker 推进");
    } catch (error) {
      setWorkspaceNotice(error instanceof Error ? `任务保存失败：${error.message}` : "任务保存失败");
    }
  };

  const refreshWorkspace = async () => {
    const automation = await fetchAutomationWorkspace({ tenantId, userId });
    setWorkspaceTasks(mapAutomationTasks(automation.tasks, automation.runs));
  };

  const runTaskAction = async (task: AgentTask, action: string) => {
    try {
      if (action === "mark_insight_read") {
        await updateAutomationTask({
          tenantId,
          userId,
          taskId: task.id,
          expectedLockVersion: Number(task.lockVersion || 0),
          patch: { status: "paused" },
        });
        setWorkspaceNotice("任务已暂停；历史洞察与运行证据仍保留");
      } else {
        const requestId = `manual-${createClientUuid()}`;
        const response = await triggerAutomationTask({ tenantId, userId, taskId: task.id, idempotencyKey: requestId });
        setWorkspaceNotice(`任务已进入持久队列：${response.run.automation_run_id} · ${response.run.status}`);
      }
      await refreshWorkspace();
    } catch (error) {
      setWorkspaceNotice(error instanceof Error ? `任务操作失败：${error.message}` : "任务操作失败");
    }
  };

  const handlePrimaryAction = () => {
    if (activeTab === "skills") {
      setWorkspaceNotice("页面安装已禁用：Skill 必须以签名版本包经管理员审核后部署，当前不会伪造“加载成功”状态");
      return;
    }
    if (activeTab === "todos") {
      setTodoComposerRequest((value) => value + 1);
      return;
    }
    openTaskCreate();
  };

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-7">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-lg bg-[#f2f2f7] flex items-center justify-center">
            <BrainCircuit className="w-[18px] h-[18px] text-[#636366]" />
          </div>
          <div>
            <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">{header.title}</h2>
            <p className="text-[13px] text-[#aeaeb2] mt-0.5">{header.subtitle}</p>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">{workspaceNotice}</p>
          </div>
        </div>
        {showHeaderAction && (
          <div className="flex flex-wrap items-center justify-end gap-3">
            {activeTab === "todos" && (
              <div ref={setTodoToolbarLeftHost} className="flex items-center" data-todo-toolbar-host="left" />
            )}
            <button
              onClick={handlePrimaryAction}
              className="flex h-10 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-4 text-[13px] text-white transition-colors hover:bg-[#2c2c2e]"
            >
              <Plus className="w-4 h-4" />
              {header.action}
            </button>
            {activeTab === "todos" && (
              <div ref={setTodoToolbarRightHost} className="flex items-center" data-todo-toolbar-host="right" />
            )}
          </div>
        )}
      </div>

      {activeTab !== "todos" && (
        <div className="grid grid-cols-4 gap-4 mb-6">
          {[
            { label: "运行中", value: String(taskSummary.active), icon: Play, color: "#34c759" },
            { label: "暂停", value: String(taskSummary.paused), icon: Clock, color: "#ff9500" },
            { label: "终止", value: String(taskSummary.terminated), icon: X, color: "#8e8e93" },
            { label: "最近成功", value: String(taskSummary.succeeded), icon: CheckCircle2, color: "#34c759" },
          ].map((s) => (
            <div key={s.label} className="bg-white p-4 rounded-xl border border-[#f0f0f2]">
              <div className="flex items-center justify-between mb-2">
                <s.icon className="w-4 h-4" style={{ color: s.color }} />
              </div>
              <div className="text-[22px] text-gray-900 tracking-tight">{s.value}</div>
              <div className="text-[12px] text-gray-400 mt-0.5">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {activeTab === "todos" && (
        <TodoWorkspace
          tenantId={tenantId}
          userId={userId}
          userName={userName}
          isSuperAdmin={isSuperAdmin}
          composerRequest={todoComposerRequest}
          toolbarLeftHost={todoToolbarLeftHost}
          toolbarRightHost={todoToolbarRightHost}
        />
      )}

      {activeTab === "tasks" && (
        <div className="space-y-5">
          <TaskSection
            title="自动化任务"
            description="定时调用数据获取、记忆提取或指标异动监控流程，运行结果和近三次状态在这里统一追踪。"
            emptyText="暂无自动化任务。"
            tasks={automationTasks}
            createLabel="新增自动化任务"
            onCreate={openTaskCreate}
            onDetail={openTaskDetail}
            onEdit={openTaskEdit}
            onDelete={(task) => setPendingDeleteTask(task)}
            onTaskAction={(task, action) => void runTaskAction(task, action)}
          />
        </div>
      )}

      {activeTab === "skills" && (
        <div className="space-y-4">
          <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 className="text-[14px] text-[#1d1d1f]">skill/插件管理</h3>
                <p className="mt-1 max-w-3xl text-[12px] leading-[1.7] text-[#8a8a8e]">
                  这些插件沉淀了主题分析方法、展示样式和提示词逻辑，可在智能分析、市场洞察、经营分析、多机构分析中被分析引擎调用。
                </p>
              </div>
              <span className="rounded-full bg-[#eef8f1] px-2.5 py-1 text-[11px] text-[#258a3f]">
                已实现 {capabilities?.skills.filter((skill) => skill.implemented && skill.healthy).length || 0} / 已声明 {capabilities?.skills.length || 0}
              </span>
            </div>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            {(capabilities?.skills || []).map((skill) => (
              <div key={skill.skill_id} className="rounded-xl border border-[#f0f0f2] bg-white p-5">
                <div className="mb-3 flex items-center justify-between">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#f2f2f7]">
                    <BrainCircuit className="h-[18px] w-[18px] text-[#636366]" />
                  </div>
                  <span className={`rounded-full px-2 py-0.5 text-[10px] ${
                    skill.implemented && skill.healthy ? "bg-[#eef8f1] text-[#258a3f]" : "bg-[#f2f2f7] text-[#8a8a8e]"
                  }`}>
                    {skill.implemented && skill.healthy ? "运行健康" : skill.status === "disabled" ? "已禁用" : "已声明未实现"}
                  </span>
                </div>
                <h4 className="text-[14px] text-[#1d1d1f]">{skill.skill_id}</h4>
                <p className="mt-2 text-[12px] leading-[1.7] text-[#8a8a8e]">
                  配置状态：{skill.configured ? "已声明" : "未声明"} · Handler：{skill.implemented ? "已注册" : "未注册"} · 健康：{skill.healthy ? "通过" : "不可执行"}
                </p>
                <div className="mt-4 rounded-lg bg-[#fafbfc] px-3 py-2 text-[11px] text-[#636366]">
                  版本：{skill.version}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {pendingDeleteTask && (
        <TaskDeleteConfirm
          task={pendingDeleteTask}
          deleting={deletingTask}
          onCancel={() => {
            if (!deletingTask) setPendingDeleteTask(null);
          }}
          onConfirm={() => {
            void (async () => {
              if (!pendingDeleteTask) return;
              setDeletingTask(true);
              try {
                await updateAutomationTask({
                  tenantId,
                  userId,
                  taskId: pendingDeleteTask.id,
                  expectedLockVersion: Number(pendingDeleteTask.lockVersion || 0),
                  patch: { status: "disabled" },
                });
                setPendingDeleteTask(null);
                await refreshWorkspace();
                setWorkspaceNotice(`已终止任务「${pendingDeleteTask.name}」`);
              } catch (error) {
                setWorkspaceNotice(error instanceof Error ? `任务删除失败：${error.message}` : "任务删除失败");
              } finally {
                setDeletingTask(false);
              }
            })();
          }}
        />
      )}

      {taskModalOpen && (
        <AgentTaskModal
          mode={taskModalMode}
          form={taskForm}
          onChange={setTaskForm}
          onClose={closeTaskModal}
          onSave={saveTask}
          knowledgeFiles={knowledgeFiles}
          metricOptions={automaticAnalysisMetrics}
          analysisSkills={analysisSkills}
          analysisModels={analysisModels}
        />
      )}
    </div>
  );
}

type TaskSectionProps = {
  title: string;
  description: string;
  emptyText: string;
  tasks: AgentTask[];
  createLabel: string;
  onCreate: () => void;
  onDetail: (task: AgentTask) => void;
  onEdit: (task: AgentTask) => void;
  onDelete: (task: AgentTask) => void;
  onTaskAction: (task: AgentTask, action: string) => void;
};

function TaskSection({
  title,
  description,
  emptyText,
  tasks,
  createLabel,
  onCreate,
  onDetail,
  onEdit,
  onDelete,
  onTaskAction,
}: TaskSectionProps) {
  const pagination = useClientPagination(tasks);
  return (
    <section className="rounded-xl border border-[#f0f0f2] bg-white p-5" data-task-section={title}>
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-[14px] text-[#1d1d1f]">{title}</h3>
          <p className="mt-1 text-[12px] leading-[1.7] text-[#8a8a8e]">{description}</p>
        </div>
        <div className="flex items-center gap-2">
          {pagination.paginated && <DataPageSelector page={pagination.page} totalPages={pagination.totalPages} shownCount={pagination.items.length} totalCount={pagination.total} onChange={pagination.setPage} ariaLabel={`${title}分页`} compact />}
          <span className="rounded-full bg-[#f2f2f7] px-2.5 py-1 text-[11px] text-[#636366]">
            {tasks.length} 条任务
          </span>
          <button
            type="button"
            onClick={onCreate}
            className="flex items-center gap-1 rounded-lg bg-[#1d1d1f] px-3 py-1.5 text-[12px] text-white transition-colors hover:bg-[#2c2c2e]"
          >
            <Plus className="h-3.5 w-3.5" />
            {createLabel}
          </button>
        </div>
      </div>

      {tasks.length === 0 ? (
        <div className="rounded-lg border border-dashed border-[#d1d1d6] bg-[#fafbfc] px-4 py-8 text-center text-[12px] text-[#8a8a8e]">
          {emptyText}
        </div>
      ) : (
        <div className="space-y-1.5">
          {pagination.items.map((task) => (
            <AgentTaskCard
              key={task.id}
              task={task}
              onDetail={() => onDetail(task)}
              onEdit={() => onEdit(task)}
              onDelete={() => onDelete(task)}
              onTaskAction={(action) => onTaskAction(task, action)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

type AgentTaskCardProps = {
  task: AgentTask;
  onDetail: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onTaskAction: (action: string) => void;
};

function AgentTaskCard({ task, onDetail, onEdit, onDelete, onTaskAction }: AgentTaskCardProps) {
  const sc = agentTaskStatusConfig[task.status];
  const StatusIcon = task.status === "running"
    ? RefreshCw
    : task.status === "alert"
      ? AlertCircle
      : task.status === "paused" || task.status === "ready"
        ? Clock
        : CheckCircle2;
  return (
    <article
      className="overflow-hidden rounded-lg bg-[#fafbfc]"
      data-agent-task-card={task.id}
      data-agent-task-category="automation"
    >
      <div className="flex items-center gap-3 p-3 transition-colors hover:bg-[#f2f2f7]">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white">
          <StatusIcon className={`h-3.5 w-3.5 ${task.status === "running" ? "animate-spin" : ""}`} style={{ color: sc.color }} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate text-[12px] text-[#1d1d1f]">{task.name}</span>
            <span className="shrink-0 rounded-full px-1.5 py-0.5 text-[10px]" style={{ color: sc.color, backgroundColor: `${sc.bg}14` }}>{sc.label}</span>
            <span className="hidden shrink-0 rounded bg-white px-1.5 py-0.5 text-[10px] text-[#8a8a8e] sm:inline">{task.type}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-[#c7c7cc]">
            <span className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{task.schedule}</span>
            <span>最近运行：{task.lastRun}</span>
            <button
              type="button"
              onClick={() => onTaskAction("run_task")}
              disabled={task.definitionStatus !== "active"}
              className="inline-flex items-center gap-0.5 text-[#8a8a8e] hover:text-[#1d1d1f] disabled:cursor-not-allowed disabled:text-[#d1d1d6]"
            >
              立即运行 <ArrowUpRight className="h-3 w-3" />
            </button>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            aria-label={`查看任务详情：${task.name}`}
            title="查看"
            onClick={onDetail}
            className="rounded-md p-1.5 text-[#636366] hover:bg-white"
          >
            <Eye className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label={task.systemManaged ? `系统任务不可编辑：${task.name}` : `编辑任务：${task.name}`}
            title={task.systemManaged ? "系统任务不可编辑" : "编辑"}
            onClick={onEdit}
            disabled={task.systemManaged}
            className="rounded-md p-1.5 text-[#636366] hover:bg-white disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            aria-label={task.systemManaged || task.definitionStatus === "disabled" ? `任务不可删除：${task.name}` : `删除任务：${task.name}`}
            title={task.systemManaged ? "系统任务不可删除" : task.definitionStatus === "disabled" ? "任务已终止" : "删除"}
            onClick={onDelete}
            disabled={task.systemManaged || task.definitionStatus === "disabled"}
            className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025] disabled:cursor-not-allowed disabled:opacity-30"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </article>
  );
}

function TaskDeleteConfirm({
  task,
  deleting,
  onCancel,
  onConfirm,
}: {
  task: AgentTask;
  deleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[180] flex items-center justify-center bg-black/20 px-4"
      role="presentation"
      data-agent-task-delete-overlay="true"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !deleting) onCancel();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-task-delete-title"
        data-agent-task-delete-dialog="true"
        className="w-full max-w-[420px] rounded-xl border border-[#e5e5ea] bg-white p-5 shadow-2xl shadow-black/20"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[#fff0f0] text-[#d93025]">
            <Trash2 className="h-4 w-4" />
          </div>
          <div>
            <h3 id="agent-task-delete-title" className="text-[14px] text-[#1d1d1f]">终止并删除这条自动化任务？</h3>
            <p className="mt-1.5 text-[12px] leading-[1.7] text-[#636366]">{task.name}</p>
            <p className="mt-1 text-[11px] leading-[1.6] text-[#aeaeb2]">确认后任务将停止调度，历史运行记录仍保留备查。</p>
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" onClick={onCancel} disabled={deleting} className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-40">取消</button>
          <button type="button" onClick={onConfirm} disabled={deleting} className="h-9 rounded-lg bg-[#d93025] px-4 text-[12px] text-white hover:bg-[#c5221f] disabled:opacity-40">{deleting ? "处理中…" : "确认删除"}</button>
        </div>
      </div>
    </div>
  );
}

function RecentRunStatus({ runs }: { runs: AutomationRun[] }) {
  const recent = (runs || []).slice(0, 3);
  return (
    <div className="flex flex-wrap items-center gap-2" aria-label="近三次运行情况">
      <span className="text-[11px] text-[#8a8a8e]">近三次运行情况</span>
      {[0, 1, 2].map((index) => {
        const run = recent[index];
        const succeeded = run?.status === "succeeded";
        const failed = run?.status === "failed" || run?.status === "cancelled";
        return (
          <span
            key={run?.automation_run_id || `empty-${index}`}
            title={run ? `${formatServerTime(run.updated_at)} · ${run.status}` : "暂无运行记录"}
            className={`flex h-6 min-w-6 items-center justify-center rounded-full border px-1.5 text-[9px] ${
              succeeded
                ? "border-[#cdebd5] bg-[#eef8f1] text-[#258a3f]"
                : failed
                  ? "border-[#f4c7c3] bg-[#fff0f0] text-[#d93025]"
                  : run
                    ? "border-[#d7e7ff] bg-[#f5f9ff] text-[#0a66c2]"
                    : "border-[#e5e5ea] bg-[#fafbfc] text-[#c7c7cc]"
            }`}
          >
            {run ? (succeeded ? "成功" : failed ? "失败" : "运行") : "—"}
          </span>
        );
      })}
    </div>
  );
}

type AgentTaskModalProps = {
  mode: "create" | "detail" | "edit";
  form: AgentTaskFormState;
  onChange: (value: AgentTaskFormState) => void;
  onClose: () => void;
  onSave: () => void;
  knowledgeFiles: KnowledgeFileAsset[];
  metricOptions: AutomaticAnalysisMetricContext[];
  analysisSkills: AnalysisSkillAsset[];
  analysisModels: ModelIntegration[];
};

function AgentTaskModal({
  mode,
  form,
  onChange,
  onClose,
  onSave,
  knowledgeFiles,
  metricOptions,
  analysisSkills,
  analysisModels,
}: AgentTaskModalProps) {
  const title = mode === "create" ? "新建自动化任务" : mode === "detail" ? "自动化任务详情" : "编辑自动化任务";
  const saveLabel = mode === "create" ? "创建任务" : "保存修改";
  const readOnly = mode === "detail";
  const updateForm = <K extends keyof AgentTaskFormState>(key: K, value: AgentTaskFormState[K]) => {
    onChange({ ...form, [key]: value });
  };
  const toggle = <T extends string>(values: T[], value: T) =>
    values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
  const files = knowledgeFiles || [];
  const skills = analysisSkills || [];
  const metrics = metricOptions || [];
  const sourceIds = form.sourceIds || [];
  const outputTypes = form.outputTypes || [];
  const selectedMetricIds = form.selectedMetricIds || [];
  const selectableSkills = skills
    .filter((skill) => skill.enabled !== false && (!skill.lifecycleStatus || skill.lifecycleStatus === "active"))
    .sort((left, right) => Number(left.sortOrder || 0) - Number(right.sortOrder || 0));
  const modelChoices = buildAutomaticAnalysisModelChoices(analysisModels || []);
  const taskReady = form.automationKind === "memory"
      ? Boolean(sourceIds.length && outputTypes.length && String(form.prompt || "").trim())
      : Boolean(
          selectedMetricIds.length
          && form.skillId
          && form.modelIntegrationId
          && form.selectedModelName
          && String(form.prompt || "").trim()
          && isValidNonNegativeNumber(form.anomalyThreshold),
        );

  return (
    <div className="fixed inset-0 z-[90] flex items-center justify-center bg-black/20 px-4" data-task-modal onMouseDown={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} className="flex max-h-[86vh] w-full max-w-[760px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20" onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-[#f0f0f2] bg-white px-6 py-4">
          <div>
            <h3 className="text-[16px] text-[#1d1d1f]">{title}</h3>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">配置记忆提取或指标异动分析流程；数据由配置的 CSV 文件夹提供。</p>
          </div>
          <button
            type="button"
            aria-label="关闭任务弹窗"
            onClick={onClose}
            className="rounded-md p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid min-h-0 gap-4 overflow-y-auto px-6 py-5 md:grid-cols-2">
          <label className="space-y-1.5 text-[11px] text-[#636366]">
            任务名称
            <input aria-label="任务名称" value={form.name} disabled={readOnly} onChange={(event) => updateForm("name", event.target.value)} placeholder="请输入任务名称" className={taskControlClass} />
          </label>
          <label className="space-y-1.5 text-[11px] text-[#636366]">
            任务状态
            <TaskSelect
              aria-label="任务状态"
              value={form.status}
              disabled={readOnly}
              onChange={(value) => updateForm("status", value as AgentTaskFormState["status"])}
            >
              <option value="active">运行中</option>
              <option value="paused">暂停</option>
              <option value="disabled">终止</option>
            </TaskSelect>
          </label>
          <label className="space-y-1.5 text-[11px] text-[#636366]">
            自动化类型
            <TaskSelect aria-label="自动化类型" value={form.automationKind} disabled={mode !== "create"} onChange={(value) => {
              const kind = value as AutomationKind;
              const firstModel = modelChoices[0];
              onChange({
                ...form,
                automationKind: kind,
                type: kind === "memory" ? "记忆提取任务" : "自动分析任务",
                skillId: kind === "automatic_analysis" && !form.skillId
                  ? selectableSkills.find((skill) => skill.id === "topic-descriptive")?.id || selectableSkills[0]?.id || ""
                  : form.skillId,
                modelIntegrationId: kind === "automatic_analysis" && !form.modelIntegrationId ? firstModel?.integrationId || "" : form.modelIntegrationId,
                selectedModelName: kind === "automatic_analysis" && !form.selectedModelName ? firstModel?.selectedModelName || "" : form.selectedModelName,
                prompt: kind === "automatic_analysis" && (!String(form.prompt || "").trim() || form.prompt === DEFAULT_MEMORY_PROMPT)
                  ? DEFAULT_AUTOMATIC_ANALYSIS_PROMPT
                  : form.prompt,
              });
            }}>
              <option value="memory">记忆提取任务</option>
              <option value="automatic_analysis">自动分析任务</option>
            </TaskSelect>
          </label>
          <label className="space-y-1.5 text-[11px] text-[#636366]">
            触发计划
            <input aria-label="触发计划" value={form.schedule} disabled={readOnly} onChange={(event) => updateForm("schedule", event.target.value)} placeholder="例如：每日 09:00 或 0 9 * * *" className={taskControlClass} />
          </label>
          {form.automationKind === "memory" ? (
            <>
              <div className="md:col-span-2">
                <div className="mb-2 flex items-center justify-between gap-3"><span className="text-[11px] text-[#636366]">知识文件输入</span><span className="text-[11px] text-[#aeaeb2]">仅处理选中文件尚未提炼的当前版本</span></div>
                <div className="grid max-h-56 gap-2 overflow-y-auto pr-1 md:grid-cols-2" data-memory-source-grid>
                  {files.map((file) => {
                    const selected = sourceIds.includes(file.id);
                    return <label key={file.id} data-memory-source-card={file.id} data-selected={selected ? "true" : "false"} className={`flex items-start gap-2 rounded-lg border p-3 text-[11px] ${selected ? "border-[#cdebd5] bg-[#eef8f1] text-[#258a3f]" : "border-[#f0f0f2] bg-white text-[#3a3a3c]"}`}><input type="checkbox" disabled={readOnly} checked={selected} onChange={() => updateForm("sourceIds", toggle(sourceIds, file.id))} className="mt-0.5 accent-[#258a3f]" /><span className="min-w-0"><span className="block truncate text-[12px]">{file.title}</span><span className="mt-0.5 block truncate text-[11px] text-[#8a8a8e]">{file.tags || file.owner || "知识文件"} · 版本 {file.assetVersion || file.updated || "当前"}</span></span></label>;
                  })}
                </div>
                {!files.length && <div className="rounded-lg border border-dashed border-[#e5e5ea] px-3 py-4 text-center text-[11px] text-[#aeaeb2]">知识文件 Tab 暂无可选内容</div>}
              </div>
              <div className="md:col-span-2">
                <span className="mb-2 block text-[11px] text-[#636366]">输出到知识记忆</span>
                <div className="grid gap-2 sm:grid-cols-2 md:grid-cols-3" data-memory-output-grid>
                  {(Object.keys(memoryOutputLabels) as MemoryOutputType[]).map((type) => {
                    const selected = outputTypes.includes(type);
                    return <label key={type} data-memory-output-card={type} data-selected={selected ? "true" : "false"} className={`flex items-center gap-2 rounded-lg border p-3 text-[11px] ${selected ? "border-[#cdebd5] bg-[#eef8f1] text-[#258a3f]" : "border-[#f0f0f2] text-[#3a3a3c]"}`}><input type="checkbox" disabled={readOnly} checked={selected} onChange={() => updateForm("outputTypes", toggle(outputTypes, type))} className="accent-[#258a3f]" />{memoryOutputLabels[type]}</label>;
                  })}
                </div>
              </div>
              <label className="space-y-1.5 text-[11px] text-[#636366] md:col-span-2" data-memory-prompt>
                知识提炼 Prompt
                <textarea aria-label="知识提炼 Prompt" value={form.prompt} disabled={readOnly} onChange={(event) => updateForm("prompt", event.target.value)} rows={5} className={taskAreaClass} />
                <span className="block text-[11px] text-[#aeaeb2]">统一使用模型接入管理中的“记忆模块”，一次执行只调用一次模型；没有本质新增信息时不生成记忆。</span>
              </label>
            </>
          ) : (
            <div className="space-y-4 md:col-span-2" data-automatic-analysis-config>
              <div>
                <div className="mb-2 flex items-center justify-between gap-3">
                  <span className="text-[11px] text-[#636366]">监控指标</span>
                  <span className="text-[11px] text-[#aeaeb2]">仅展示已绑定语义数据集与指标编码的可执行指标</span>
                </div>
                <div className="grid max-h-64 gap-2 overflow-y-auto pr-1 md:grid-cols-2" data-automatic-analysis-metrics>
                  {metrics.map((metric) => {
                    const selected = selectedMetricIds.includes(metric.optionId);
                    return (
                      <label key={metric.optionId} data-selected={selected ? "true" : "false"} className={`rounded-lg border p-3 text-[11px] ${selected ? "border-[#cdebd5] bg-[#eef8f1] text-[#258a3f]" : "border-[#f0f0f2] bg-white text-[#3a3a3c]"}`}>
                        <div className="flex items-start gap-2">
                          <input type="checkbox" disabled={readOnly} checked={selected} onChange={() => updateForm("selectedMetricIds", toggle(selectedMetricIds, metric.optionId))} className="mt-0.5 accent-[#258a3f]" />
                          <span className="min-w-0">
                            <span className="block truncate text-[12px] text-[#1d1d1f]">{metric.metricName}</span>
                            <span className="mt-0.5 block truncate text-[11px] text-[#aeaeb2]">{metric.sourceTable} · {metric.datasetId}</span>
                          </span>
                        </div>
                        <p className="mt-2 line-clamp-2 text-[11px] leading-4 text-[#636366]">描述：{metric.description || metric.definition}</p>
                        <p className="mt-1 truncate text-[11px] text-[#aeaeb2]">口径：{metric.valueLogic || metric.metricCode}</p>
                      </label>
                    );
                  })}
                </div>
                {!metrics.length && <div className="rounded-lg border border-dashed border-[#e5e5ea] px-3 py-4 text-center text-[11px] text-[#aeaeb2]">暂无已发布且可执行的主题表指标，请先在数据资产中补充数据集、指标编码和时间维度。</div>}
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <label className="space-y-1.5 text-[11px] text-[#636366]">
                  分析 Skill
                  <TaskSelect aria-label="分析 Skill" value={form.skillId} disabled={readOnly} onChange={(value) => updateForm("skillId", value)}>
                    <option value="">请选择分析 Skill</option>
                    {selectableSkills.map((skill) => <option key={skill.id} value={skill.id}>{skill.name} · {skill.category}</option>)}
                  </TaskSelect>
                </label>
                <label className="space-y-1.5 text-[11px] text-[#636366]">
                  Data_Agent 分析模型
                  <TaskSelect aria-label="Data_Agent 分析模型" value={modelChoiceValue(form.modelIntegrationId, form.selectedModelName)} disabled={readOnly} onChange={(value) => {
                    const choice = modelChoices.find((item) => item.value === value);
                    onChange({ ...form, modelIntegrationId: choice?.integrationId || "", selectedModelName: choice?.selectedModelName || "" });
                  }}>
                    <option value="">请选择已测试连通的模型</option>
                    {modelChoices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                  </TaskSelect>
                </label>
              </div>
              {!modelChoices.length && <div className="rounded-lg border border-[#f1d6b8] bg-[#fff7ed] px-3 py-2.5 text-[11px] text-[#b45309]">请先在“模型接入管理”中将模型绑定到“自动分析任务”应用模块，并完成连通性测试。运行时只会通过该模块调用所选模型。</div>}

              <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4" data-anomaly-rule>
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div><div className="text-[12px] text-[#1d1d1f]">异动硬触发规则</div><p className="mt-1 text-[11px] leading-4 text-[#8a8a8e]">调度先查询最近周期并判定规则；未命中时记录监控结果，不调用 Data_Agent。</p></div>
                  <span className="rounded-full bg-[#fff0ee] px-2 py-1 text-[11px] text-[#d93025]">硬触发</span>
                </div>
                <div className="grid gap-3 md:grid-cols-5">
                  <label className="space-y-1.5 text-[11px] text-[#636366] md:col-span-2">判断方式<TaskSelect aria-label="异动判断方式" value={form.anomalyComparison} disabled={readOnly} onChange={(value) => updateForm("anomalyComparison", value as AgentTaskFormState["anomalyComparison"])}><option value="relative_change">环比变化率达到</option><option value="absolute_change">绝对变化量达到</option><option value="above">当前值高于</option><option value="below">当前值低于</option></TaskSelect></label>
                  <label className="space-y-1.5 text-[11px] text-[#636366]">阈值{form.anomalyComparison === "relative_change" ? "（%）" : ""}<input aria-label="异动阈值" type="number" min="0" value={form.anomalyThreshold} disabled={readOnly} onChange={(event) => updateForm("anomalyThreshold", event.target.value)} className={taskControlClass} /></label>
                  <label className="space-y-1.5 text-[11px] text-[#636366]">变化方向<TaskSelect aria-label="异动方向" value={form.anomalyDirection} disabled={readOnly || ["above", "below"].includes(form.anomalyComparison)} onChange={(value) => updateForm("anomalyDirection", value as AgentTaskFormState["anomalyDirection"])}><option value="both">上涨或下降</option><option value="up">仅上涨</option><option value="down">仅下降</option></TaskSelect></label>
                  <label className="space-y-1.5 text-[11px] text-[#636366]">多指标触发<TaskSelect aria-label="多指标触发方式" value={form.anomalyMatchMode} disabled={readOnly} onChange={(value) => updateForm("anomalyMatchMode", value as AgentTaskFormState["anomalyMatchMode"])}><option value="any">任一命中</option><option value="all">全部命中</option></TaskSelect></label>
                </div>
              </div>

              <label className="block space-y-1.5 text-[11px] text-[#636366]" data-automatic-analysis-prompt>
                归因分析 Prompt
                <textarea aria-label="归因分析 Prompt" value={form.prompt} disabled={readOnly} onChange={(event) => updateForm("prompt", event.target.value)} rows={5} className={taskAreaClass} />
                <span className="block text-[11px] text-[#aeaeb2]">命中异动后，指标表、描述、口径、Skill、Prompt、规则和查询证据会一起送入所选模型。</span>
              </label>
            </div>
          )}
          <div className="rounded-lg bg-[#fafbfc] px-3 py-3 md:col-span-2"><RecentRunStatus runs={form.recentRuns} /></div>
          <label className="space-y-1.5 text-[11px] text-[#636366] md:col-span-2">
            任务描述
            <textarea
              aria-label="任务描述"
              value={form.description}
              disabled={readOnly}
              onChange={(event) => updateForm("description", event.target.value)}
              rows={3}
              className={taskAreaClass}
            />
          </label>
          {form.result && <label className="space-y-1.5 text-[11px] text-[#636366] md:col-span-2">
            任务结果
            <textarea
              aria-label="任务结果"
              value={form.result}
              readOnly
              rows={3}
              className={`${taskAreaClass} text-[#8a8a8e]`}
            />
          </label>}
        </div>

        <div className="flex justify-end gap-2 border-t border-[#f0f0f2] bg-white px-6 py-4">
          <button type="button" onClick={onClose} className="h-9 rounded-lg border border-[#e5e5ea] px-4 text-[12px] text-[#636366] hover:bg-[#f2f2f7]">
            {mode === "detail" ? "关闭" : "取消"}
          </button>
          {mode !== "detail" && (
            <button type="button" onClick={onSave} disabled={!String(form.name || "").trim() || !taskReady} className="h-9 rounded-lg bg-[#1d1d1f] px-5 text-[12px] text-white hover:bg-[#2c2c2e] disabled:cursor-not-allowed disabled:bg-[#c7c7cc]">
              {saveLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function emptyTaskForm(): AgentTaskFormState {
  return {
    name: "",
    type: "记忆提取任务",
    schedule: "每日 09:00",
    status: "active",
    lastRun: "未运行",
    result: "",
    description: "",
    automationKind: "memory",
    sourceIds: [],
    outputTypes: Object.keys(memoryOutputLabels) as MemoryOutputType[],
    prompt: DEFAULT_MEMORY_PROMPT,
    selectedMetricIds: [],
    skillId: "",
    modelIntegrationId: "",
    selectedModelName: "",
    anomalyComparison: "relative_change",
    anomalyThreshold: "10",
    anomalyDirection: "both",
    anomalyMatchMode: "any",
    lookbackPeriods: "2",
    recentRuns: [],
  };
}

function taskToForm(task: AgentTask): AgentTaskFormState {
  const isAutomaticAnalysis = task.handlerRef === "analysis.monitor" || task.taskConfig?.automation_kind === "automatic_analysis";
  const isMemory = task.handlerRef === "memory.extract" || task.taskConfig?.automation_kind === "memory";
  const selectedMetrics = Array.isArray(task.taskConfig?.selected_metrics)
    ? task.taskConfig.selected_metrics.filter((item): item is Record<string, unknown> => Boolean(item && typeof item === "object"))
    : [];
  const modelSelection = task.taskConfig?.model_application_selection && typeof task.taskConfig.model_application_selection === "object"
    ? task.taskConfig.model_application_selection as Record<string, unknown>
    : {};
  const anomalyRule = task.taskConfig?.anomaly_rule && typeof task.taskConfig.anomaly_rule === "object"
    ? task.taskConfig.anomaly_rule as Record<string, unknown>
    : {};
  const selectedSkill = task.taskConfig?.analysis_skill && typeof task.taskConfig.analysis_skill === "object"
    ? task.taskConfig.analysis_skill as Record<string, unknown>
    : {};
  return {
    name: task.name,
    type: task.type,
    schedule: task.schedule,
    status: task.definitionStatus || "active",
    lastRun: task.lastRun,
    result: task.result,
    description: task.description,
    automationKind: isAutomaticAnalysis ? "automatic_analysis" : "memory",
    sourceIds: stringList(task.taskConfig?.source_ids),
    outputTypes: memoryOutputList(task.taskConfig?.output_types),
    prompt: String(task.taskConfig?.prompt || ""),
    selectedMetricIds: selectedMetrics.map(automaticMetricOptionId).filter(Boolean),
    skillId: String(selectedSkill.id || task.taskConfig?.skill_id || ""),
    modelIntegrationId: String(modelSelection.integrationId || modelSelection.integration_id || ""),
    selectedModelName: String(modelSelection.selectedModelName || modelSelection.selected_model_name || ""),
    anomalyComparison: normalizeAnomalyComparison(anomalyRule.comparison),
    anomalyThreshold: String(anomalyRule.threshold ?? "10"),
    anomalyDirection: normalizeAnomalyDirection(anomalyRule.direction),
    anomalyMatchMode: anomalyRule.match_mode === "all" ? "all" : "any",
    lookbackPeriods: String(anomalyRule.lookback_periods ?? "2"),
    recentRuns: task.recentRuns || [],
  };
}

function taskFormToAutomationDefinition(
  form: AgentTaskFormState,
  existing: AgentTask | undefined,
  metricOptions: AutomaticAnalysisMetricContext[],
  analysisSkills: AnalysisSkillAsset[],
): Record<string, unknown> {
  const scheduleExpression = humanScheduleToCron(form.schedule);
  const triggerType = scheduleExpression ? "schedule" : "manual";
  const taskCode = existing?.taskCode || `ui_automation_${createClientUuid().replaceAll("-", "")}`;
  const isMemory = form.automationKind === "memory";
  const isAutomaticAnalysis = form.automationKind === "automatic_analysis";
  const selectedMetrics = (metricOptions || []).filter((metric) => (form.selectedMetricIds || []).includes(metric.optionId));
  const selectedSkill = analysisSkills.find((skill) => skill.id === form.skillId);
  return {
    task_code: taskCode,
    task_name: form.name.trim(),
    task_type: isAutomaticAnalysis ? "analysis" : "custom",
    trigger_type: triggerType,
    schedule_expression: scheduleExpression,
    handler_ref: isMemory ? "memory.extract" : "analysis.monitor",
    task_config: {
      ...(existing?.taskConfig || {}),
      category: "automation",
      question: form.description.trim() || form.name.trim(),
      display_type: form.type.trim(),
      display_schedule: form.schedule.trim(),
      schedule_timezone: "Asia/Shanghai",
      automation_kind: form.automationKind,
      connection_id: undefined,
      data_script_id: undefined,
      execution_mode: isMemory ? "llm" : undefined,
      source_kind: isMemory ? "knowledge_file" : undefined,
      unextracted_only: isMemory ? true : undefined,
      source_ids: isMemory ? form.sourceIds : undefined,
      output_types: isMemory ? form.outputTypes : undefined,
      prompt: isMemory || isAutomaticAnalysis ? form.prompt.trim() : undefined,
      model_application_module: isMemory ? "memory_extraction" : isAutomaticAnalysis ? "automatic_analysis" : undefined,
      selected_metrics: isAutomaticAnalysis ? selectedMetrics : undefined,
      analysis_skill: isAutomaticAnalysis && selectedSkill ? {
        id: selectedSkill.id,
        name: selectedSkill.name,
        category: selectedSkill.category,
      } : undefined,
      skill_id: isAutomaticAnalysis ? form.skillId : undefined,
      model_application_selection: isAutomaticAnalysis ? {
        integrationId: form.modelIntegrationId,
        selectedModelName: form.selectedModelName,
      } : undefined,
      anomaly_rule: isAutomaticAnalysis ? {
        comparison: form.anomalyComparison,
        threshold: Number(form.anomalyThreshold),
        direction: form.anomalyDirection,
        match_mode: form.anomalyMatchMode,
        lookback_periods: Math.max(2, Number(form.lookbackPeriods) || 2),
      } : undefined,
    },
    retry_policy: { max_attempts: 3, base_delay_seconds: 30 },
    timeout_seconds: 900,
    max_concurrency: 1,
    status: form.status,
  };
}

function mapAutomationTasks(tasks: AutomationTask[], runs: AutomationRun[]): AgentTask[] {
  const runsByTask = new Map<string, AutomationRun[]>();
  [...runs]
    .sort((left, right) => String(right.created_at).localeCompare(String(left.created_at)))
    .forEach((run) => {
      const taskRuns = runsByTask.get(run.automation_task_id) || [];
      if (taskRuns.length < 3) taskRuns.push(run);
      runsByTask.set(run.automation_task_id, taskRuns);
    });
  return tasks.filter((task) =>
    task.task_config.category !== "insight" && ["memory.extract", "analysis.monitor", "topic-data.refresh"].includes(task.handler_ref),
  ).map((task) => {
    const recentRuns = runsByTask.get(task.automation_task_id) || [];
    const latest = recentRuns[0];
    return {
      id: task.automation_task_id,
      name: task.task_name,
      type: String(task.task_config.display_type || task.task_type),
      schedule: String(task.task_config.display_schedule || task.schedule_expression || "手动触发"),
      status: automationDisplayStatus(task, latest),
      lastRun: latest ? formatServerTime(latest.updated_at) : "未运行",
      result: latest ? automationRunResult(latest) : "",
      description: task.handler_ref === "topic-data.refresh"
        ? "每天按主题表 SQL 加工 Origin_Data 中的最新 CSV，并覆盖更新 Topic_Data 当前结果。"
        : String(task.task_config.question || ""),
      ownerUserId: task.owner_user_id,
      createdBy: task.owner_user_id,
      createdAt: task.created_at,
      updatedAt: task.updated_at,
      definitionStatus: task.status,
      lockVersion: task.lock_version,
      taskCode: task.task_code,
      handlerRef: task.handler_ref,
      taskConfig: task.task_config,
      systemManaged: task.handler_ref === "topic-data.refresh",
      recentRuns,
    };
  });
}

function automationDisplayStatus(task: AutomationTask, run?: AutomationRun): AgentTaskStatus {
  if (task.status === "disabled") return "terminated";
  if (task.status === "paused") return "paused";
  if (!run) return "ready";
  if (run.status === "queued" || run.status === "running" || run.status === "retry_wait") return "running";
  if (run.status === "failed") return "alert";
  return "completed";
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

function memoryOutputList(value: unknown): MemoryOutputType[] {
  const configured = stringList(value);
  const selected = configured.filter((item): item is MemoryOutputType => item in memoryOutputLabels);
  if (configured.includes("user_behavior_habit")) selected.push("analysis_habit", "operation_habit", "reporting_habit");
  return selected.length ? [...new Set(selected)] : Object.keys(memoryOutputLabels) as MemoryOutputType[];
}

function buildAutomaticAnalysisMetricOptions(
  topicTables: TopicTableAsset[] = [],
  metricDictionary: MetricDictionaryItem[] = [],
): AutomaticAnalysisMetricContext[] {
  const dictionaryByCode = new Map(metricDictionary.filter((item) => item.metricCode).map((item) => [item.metricCode!, item]));
  const dictionaryByName = new Map(metricDictionary.map((item) => [item.metricName.trim(), item]));
  const options: AutomaticAnalysisMetricContext[] = [];
  const seen = new Set<string>();
  topicTables
    .filter((table) => (!table.lifecycleStatus || table.lifecycleStatus === "active") && table.datasetId && Array.isArray(table.fields))
    .forEach((table) => {
      const fields = Array.isArray(table.fields) ? table.fields : [];
      const configuredDimensions = [...new Set([...(table.defaultDimensions || []), ...(table.dimensionCodes || [])])];
      const detectedTimeDimension =
        fields.find((field) => field.isTime)?.fieldNameEn
        || configuredDimensions.find((dimension) => /(?:date|time|month|week|day|stat_)/i.test(dimension))
        || fields.find((field) => /(?:date|time|month|week|day|stat_)/i.test(field.fieldNameEn))?.fieldNameEn;
      if (!detectedTimeDimension) return;
      const defaultTimeDimension = String(detectedTimeDimension);
      fields.filter((field) => field.isMetric && (field.metricCode || field.fieldNameEn)).forEach((field) => {
        const metricCode = String(field.metricCode || field.fieldNameEn).trim();
        const optionId = `${table.id}:${metricCode}`;
        if (!metricCode || seen.has(optionId)) return;
        const dictionary = dictionaryByCode.get(metricCode) || dictionaryByName.get(field.fieldNameCn.trim());
        seen.add(optionId);
        options.push({
          optionId,
          metricId: dictionary?.metricId || optionId,
          metricName: field.fieldNameCn || dictionary?.metricName || metricCode,
          metricCode,
          datasetId: String(table.datasetId),
          tableId: table.id,
          tableCode: table.code,
          sourceTable: table.name,
          description: dictionary?.description || table.description || field.explanation,
          definition: dictionary?.definition || field.explanation,
          valueLogic: dictionary?.valueLogic || field.metricLogic || metricCode,
          dimension: dictionary?.dimension || (table.defaultDimensions || table.dimensionCodes || []).join("、"),
          timeDimension: defaultTimeDimension,
        });
      });
    });
  return options.sort((left, right) => {
    const coreOrder = ["loan_balance", "loan_amount", "new_balance"];
    const leftCore = coreOrder.indexOf(left.metricCode);
    const rightCore = coreOrder.indexOf(right.metricCode);
    if (leftCore >= 0 || rightCore >= 0) return (leftCore < 0 ? 99 : leftCore) - (rightCore < 0 ? 99 : rightCore);
    return left.sourceTable.localeCompare(right.sourceTable, "zh-CN") || left.metricName.localeCompare(right.metricName, "zh-CN");
  });
}

function buildAutomaticAnalysisModelChoices(models: ModelIntegration[]) {
  const choices: Array<{ value: string; integrationId: string; selectedModelName: string; label: string }> = [];
  const seen = new Set<string>();
  models
    .filter((model) => (model.applicationModule === "automatic_analysis" || model.applicationModule === "global_text_model")
      && model.status === "available"
      && ["connected", "mock"].includes(model.testStatus || ""))
    .forEach((model) => {
      const names = (model.enabledModels || [])
        .map((name) => String(name).trim())
        .filter(Boolean);
      names.forEach((selectedModelName) => {
        const value = modelChoiceValue(model.id, selectedModelName);
        if (seen.has(value)) return;
        seen.add(value);
        choices.push({
          value,
          integrationId: model.id,
          selectedModelName,
          label: `${model.name || "Data_Agent"} · ${selectedModelName}`,
        });
      });
    });
  return choices;
}

function modelChoiceValue(integrationId: string, selectedModelName: string) {
  return integrationId && selectedModelName ? `${integrationId}::${selectedModelName}` : "";
}

function automaticMetricOptionId(metric: Record<string, unknown>) {
  const explicit = String(metric.optionId || metric.option_id || "").trim();
  if (explicit) return explicit;
  const tableId = String(metric.tableId || metric.table_id || "").trim();
  const metricCode = String(metric.metricCode || metric.metric_code || "").trim();
  return tableId && metricCode ? `${tableId}:${metricCode}` : "";
}

function normalizeAnomalyComparison(value: unknown): AgentTaskFormState["anomalyComparison"] {
  return ["relative_change", "absolute_change", "above", "below"].includes(String(value))
    ? String(value) as AgentTaskFormState["anomalyComparison"]
    : "relative_change";
}

function normalizeAnomalyDirection(value: unknown): AgentTaskFormState["anomalyDirection"] {
  return ["both", "up", "down"].includes(String(value))
    ? String(value) as AgentTaskFormState["anomalyDirection"]
    : "both";
}

function isValidNonNegativeNumber(value: string) {
  return value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0;
}

function automationRunResult(run: AutomationRun) {
  if (run.status === "failed") return `执行失败：${run.error_code || "automation_failed"}`;
  if (run.status === "cancelled") return "执行已取消";
  if (run.status === "queued" || run.status === "running" || run.status === "retry_wait") {
    return `运行 ${run.automation_run_id}：${run.status}`;
  }
  const references = run.result_refs
    .map((item) => String(item.id || item.hash || ""))
    .filter(Boolean)
    .slice(0, 3);
  return references.length ? `执行完成，产物引用：${references.join("、")}` : "执行完成，未返回可展示产物引用";
}

function formatServerTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function humanScheduleToCron(value: string): string | null {
  const text = value.trim();
  if (!text || text === "实时" || text === "实时触发" || text === "手动触发") return null;
  if (/^(?:\S+\s+){4}\S+$/.test(text)) return text;
  const daily = text.match(/^(?:每日|每天)\s*(\d{1,2}):(\d{2})$/);
  if (daily) return `${Number(daily[2])} ${Number(daily[1])} * * *`;
  const everyHours = text.match(/^每\s*(\d{1,2})\s*小时$/);
  if (everyHours) return `0 */${Math.max(1, Math.min(Number(everyHours[1]), 23))} * * *`;
  const weekly = text.match(/^每周([一二三四五六日])\s*(\d{1,2}):(\d{2})$/);
  if (weekly) {
    const weekday = { 日: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6 }[weekly[1] as "一"];
    return `${Number(weekly[3])} ${Number(weekly[2])} * * ${weekday}`;
  }
  throw new Error("触发计划需填写 cron、每日 HH:mm、每N小时或每周X HH:mm");
}
