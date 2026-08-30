import { useEffect, useMemo, useRef, useState, type DragEvent, type MouseEvent } from "react";
import { createPortal } from "react-dom";
import {
  CalendarDays,
  Check,
  ChevronDown,
  ChevronUp,
  ChevronsDown,
  ChevronsUp,
  ChevronRight,
  Circle,
  Columns3,
  ListChecks,
  PencilLine,
  Plus,
  Tag,
  Trash2,
  Users,
} from "lucide-react";
import { fetchApplicationModule, runApplicationAction } from "../services/applicationApi";
import { DataPageSelector, useClientPagination } from "./ui/DataPageSelector";
import { askConfirm } from "./ui/ConfirmDialog";
import { AppSelect } from "./ui/AppSelect";
import { DatePicker } from "./ui/DatePicker";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "./ui/FormDialog";

type TodoStatus = "todo" | "in_progress" | "done" | "closed";
type TodoPriority = "low" | "medium" | "high" | "urgent";
type TodoSource = "manual" | "system" | "weekly_report" | "agent";
type TodoView = "list" | "kanban" | "calendar";

type AgentTodo = {
  id: string;
  title: string;
  description: string;
  status: TodoStatus;
  priority: TodoPriority;
  dueDate: string;
  assignee: string;
  listName: string;
  labels: string[];
  source: TodoSource;
  ownerUserId: string;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  sourceVersionId?: string;
  sourceText?: string;
  background?: string;
  suggestion?: string;
  relatedOrg?: string;
  relatedMetric?: string;
  confidence?: number;
  registrationRequestId?: string;
};

type TodoFormState = {
  title: string;
  description: string;
  status: TodoStatus;
  priority: TodoPriority;
  dueDate: string;
  assignee: string;
  listName: string;
  labels: string;
};

type TodoWorkspaceProps = {
  tenantId: string;
  userId: string;
  userName: string;
  isSuperAdmin?: boolean;
  composerRequest: number;
  toolbarLeftHost: HTMLDivElement | null;
  toolbarRightHost: HTMLDivElement | null;
};

type CalendarLaneReveal = {
  date: string;
  index: number;
} | null;

type CalendarLaneDeleteState = {
  date: string;
  index: number;
  assignments: Record<string, string>;
} | null;

const statusConfig: Record<TodoStatus, { label: string; color: string; bg: string }> = {
  todo: { label: "待处理", color: "#636366", bg: "#f2f2f7" },
  in_progress: { label: "进行中", color: "#0b63ce", bg: "#eaf2ff" },
  done: { label: "已完成", color: "#258a3f", bg: "#eef8f1" },
  closed: { label: "已关闭", color: "#8a8a8e", bg: "#f2f2f7" },
};

const priorityConfig: Record<TodoPriority, { label: string; color: string; bg: string; rank: number }> = {
  urgent: { label: "紧急", color: "#d92d20", bg: "#fff1f0", rank: 4 },
  high: { label: "高", color: "#b54708", bg: "#fff7e6", rank: 3 },
  medium: { label: "中", color: "#0b63ce", bg: "#eaf2ff", rank: 2 },
  low: { label: "低", color: "#667085", bg: "#f2f2f7", rank: 1 },
};

const sourceConfig: Record<TodoSource, { label: string; color: string }> = {
  manual: { label: "自建", color: "#636366" },
  system: { label: "系统注入", color: "#af52de" },
  weekly_report: { label: "经营周报", color: "#0b63ce" },
  agent: { label: "智能体", color: "#258a3f" },
};

const kanbanColumns: { status: TodoStatus; title: string }[] = [
  { status: "todo", title: "待处理" },
  { status: "in_progress", title: "进行中" },
  { status: "done", title: "已完成" },
  { status: "closed", title: "已关闭" },
];

export function TodoWorkspace({
  tenantId,
  userId,
  userName,
  isSuperAdmin = false,
  composerRequest,
  toolbarLeftHost,
  toolbarRightHost,
}: TodoWorkspaceProps) {
  const [todos, setTodos] = useState<AgentTodo[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncError, setSyncError] = useState("");
  const [statusFilter, setStatusFilter] = useState<TodoStatus | "all">("all");
  const [activeView, setActiveView] = useState<TodoView>("list");
  const [composerOpen, setComposerOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<TodoFormState>(() => emptyTodoForm(userName));
  const [collapsedTodoIds, setCollapsedTodoIds] = useState<Set<string>>(() => new Set());
  const [kanbanExpanded, setKanbanExpanded] = useState(true);
  const [calendarExpanded, setCalendarExpanded] = useState(false);
  const [draggingTodoId, setDraggingTodoId] = useState<string | null>(null);
  const [calendarDays, setCalendarDays] = useState(() => Array.from({ length: 7 }, (_, index) => addDaysIso(index)));
  const [editingDateIndex, setEditingDateIndex] = useState<number | null>(null);
  const [revealingCalendarLane, setRevealingCalendarLane] = useState<CalendarLaneReveal>(null);
  const [calendarLaneRevealReady, setCalendarLaneRevealReady] = useState(true);
  const [deletingCalendarLane, setDeletingCalendarLane] = useState<CalendarLaneDeleteState>(null);
  const calendarRevealTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (calendarRevealTimerRef.current) {
        window.clearTimeout(calendarRevealTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const loadTodos = async () => {
      setLoading(true);
      setSyncError("");
      try {
        const response = await fetchApplicationModule<{ todos?: unknown[] }>({
          tenantId,
          userId,
          moduleKey: "agent_workspace",
        });
        if (cancelled) return;
        const parsed = normalizeTodos(response.state.todos, userId, userName);
        setTodos(parsed);
      } catch (error) {
        if (!cancelled) {
          setTodos([]);
          setSyncError(error instanceof Error ? error.message : "待办任务加载失败");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void loadTodos();
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId, userName]);

  useEffect(() => {
    if (composerRequest <= 0) return;
    setEditingId(null);
    setForm(emptyTodoForm(userName));
    setComposerOpen(true);
  }, [composerRequest, userName]);

  const filteredTodos = useMemo(() => {
    return [...todos]
      .filter((todo) => statusFilter === "all" || todo.status === statusFilter)
      .sort(sortTodos);
  }, [statusFilter, todos]);

  const openCreate = (defaults: Partial<TodoFormState> = {}) => {
    setEditingId(null);
    setForm({ ...emptyTodoForm(userName), ...defaults });
    setComposerOpen(true);
  };

  const openEdit = (todo: AgentTodo) => {
    setEditingId(todo.id);
    setForm({
      title: todo.title,
      description: todo.description,
      status: todo.status,
      priority: todo.priority,
      dueDate: todo.dueDate,
      assignee: todo.assignee,
      listName: todo.listName,
      labels: todo.labels.join("，"),
    });
    setComposerOpen(true);
  };

  const closeComposer = () => {
    setComposerOpen(false);
    setEditingId(null);
    setForm(emptyTodoForm(userName));
  };

  const saveTodo = async () => {
    const title = form.title.trim();
    if (!title) return;
    const existing = editingId ? todos.find((todo) => todo.id === editingId) : undefined;
    const now = new Date().toISOString();
    const nextTodo: AgentTodo = {
      id: existing?.id || makeTodoId(),
      title,
      description: form.description.trim(),
      status: form.status,
      priority: form.priority,
      dueDate: form.dueDate || todayIso(),
      assignee: form.assignee.trim() || userName,
      listName: form.listName.trim() || "个人待办",
      labels: splitLabels(form.labels),
      source: existing?.source || "manual",
      ownerUserId: existing?.ownerUserId || userId,
      createdBy: existing?.createdBy || userId,
      createdAt: existing?.createdAt || now,
      updatedAt: now,
      sourceVersionId: existing?.sourceVersionId,
      sourceText: existing?.sourceText,
      background: existing?.background,
      suggestion: existing?.suggestion,
      relatedOrg: existing?.relatedOrg,
      relatedMetric: existing?.relatedMetric,
      confidence: existing?.confidence,
    };
    const action = existing ? "update_todo" : "create_todo";
    const optimisticTodos = existing
      ? todos.map((todo) => (todo.id === nextTodo.id ? nextTodo : todo))
      : [nextTodo, ...todos];
    const previousTodos = todos;
    setTodos(optimisticTodos);
    setSyncError("");
    closeComposer();
    const synced = await persistTodoAction(tenantId, userId, userName, action, { todo: nextTodo, ownerUserId: userId });
    if (synced) {
      setTodos(synced);
    } else {
      setTodos(previousTodos);
      setSyncError("待办任务保存失败，未写入服务端");
    }
  };

  const deleteTodo = async (todoId: string) => {
    const todo = todos.find((item) => item.id === todoId);
    if (!(await askConfirm({ title: "删除待办", description: `确定删除「${todo?.title || "该待办"}」？`, hint: "此操作不可撤销。" }))) return;
    const previous = todos;
    setTodos((items) => items.filter((todo) => todo.id !== todoId));
    setSyncError("");
    const synced = await persistTodoAction(tenantId, userId, userName, "delete_todo", { todoId });
    if (synced) {
      setTodos(synced);
    } else {
      setTodos(previous);
      setSyncError("待办任务删除失败，已恢复原记录");
    }
  };

  const reviewRegistration = async (todo: AgentTodo, approved: boolean) => {
    const requestId = todo.registrationRequestId || todo.id.replace(/^todo_reg_/, "");
    if (!requestId) return;
    const previous = todos;
    setTodos((items) => items.filter((item) => item.id !== todo.id));
    setSyncError("");
    const synced = await persistTodoAction(
      tenantId,
      userId,
      userName,
      approved ? "approve_registration" : "reject_registration",
      { requestId, todoId: todo.id },
    );
    if (synced) setTodos(synced);
    else {
      setTodos(previous);
      setSyncError(approved ? "同意注册失败，已恢复原待办" : "拒绝注册失败，已恢复原待办");
    }
  };

  const changeStatus = async (todo: AgentTodo, status: TodoStatus) => {
    if (todo.status === status) return;
    const previous = todos;
    const nextTodo = { ...todo, status, updatedAt: new Date().toISOString() };
    setTodos((items) => items.map((item) => (item.id === todo.id ? nextTodo : item)));
    const synced = await persistTodoAction(tenantId, userId, userName, "change_todo_status", {
      todoId: todo.id,
      status,
    });
    if (synced) setTodos(synced);
    else {
      setTodos(previous);
      setSyncError("待办状态更新失败，已恢复原状态");
    }
  };

  const updateTodo = async (todo: AgentTodo) => {
    const previous = todos;
    const nextTodo = { ...todo, updatedAt: new Date().toISOString() };
    setTodos((items) => items.map((item) => (item.id === nextTodo.id ? nextTodo : item)));
    const synced = await persistTodoAction(tenantId, userId, userName, "update_todo", { todo: nextTodo, ownerUserId: userId });
    if (synced) setTodos(synced);
    else {
      setTodos(previous);
      setSyncError("待办任务更新失败，已恢复原记录");
    }
  };

  const moveTodoToDate = (todo: AgentTodo, dueDate: string) => {
    if (todo.dueDate === dueDate) return;
    void updateTodo({ ...todo, dueDate });
  };

  const toggleTodoCollapsed = (todoId: string) => {
    setCollapsedTodoIds((current) => {
      const next = new Set(current);
      if (next.has(todoId)) next.delete(todoId);
      else next.add(todoId);
      return next;
    });
  };

  const setAllCardsExpanded = (expanded: boolean) => {
    if (activeView === "calendar") setCalendarExpanded(expanded);
    else setKanbanExpanded(expanded);
    setCollapsedTodoIds(expanded ? new Set() : new Set(filteredTodos.map((todo) => todo.id)));
  };

  const activeCardsExpanded = activeView === "calendar" ? calendarExpanded : kanbanExpanded;

  const shiftTodosForDateMap = (dateMap: Record<string, string>) => {
    const affected = todos
      .filter((todo) => dateMap[todo.dueDate] && dateMap[todo.dueDate] !== todo.dueDate)
      .map((todo) => ({ ...todo, dueDate: dateMap[todo.dueDate], updatedAt: new Date().toISOString() }));
    if (!affected.length) return;
    setTodos((items) =>
      items.map((item) => {
        const updated = affected.find((todo) => todo.id === item.id);
        return updated || item;
      }),
    );
    affected.forEach((todo) => {
      void persistTodoAction(tenantId, userId, userName, "update_todo", { todo, ownerUserId: userId }).then((synced) => {
        if (synced) setTodos(synced);
      });
    });
  };

  const revealInsertedCalendarLane = (date: string, index: number) => {
    if (calendarRevealTimerRef.current) {
      window.clearTimeout(calendarRevealTimerRef.current);
      calendarRevealTimerRef.current = null;
    }
    setRevealingCalendarLane({ date, index });
    setCalendarLaneRevealReady(false);
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => setCalendarLaneRevealReady(true));
    });
    calendarRevealTimerRef.current = window.setTimeout(() => {
      setRevealingCalendarLane(null);
      setCalendarLaneRevealReady(true);
      calendarRevealTimerRef.current = null;
    }, 420);
  };

  const insertCalendarLaneAfter = (index: number) => {
    const current = calendarDays;
    if (index >= current.length - 1) {
      const insertedDate = addDays(current[current.length - 1], 1);
      setCalendarDays([...current, insertedDate]);
      revealInsertedCalendarLane(insertedDate, current.length);
      return;
    }
    const insertedDate = current[index + 1];
    const shifted = current.slice(index + 1).map((day) => addDays(day, 1));
    const next = [...current.slice(0, index + 1), insertedDate, ...shifted];
    const dateMap = current.slice(index + 1).reduce((map, day) => ({ ...map, [day]: addDays(day, 1) }), {} as Record<string, string>);
    setCalendarDays(next);
    revealInsertedCalendarLane(insertedDate, index + 1);
    shiftTodosForDateMap(dateMap);
  };

  const changeCalendarLaneDate = (index: number, nextDate: string) => {
    const currentDate = calendarDays[index];
    if (!currentDate || !nextDate || currentDate === nextDate) {
      setEditingDateIndex(null);
      return;
    }
    const delta = diffDays(currentDate, nextDate);
    const next = calendarDays.map((day, dayIndex) => (dayIndex >= index ? addDays(day, delta) : day));
    const dateMap = calendarDays
      .slice(index)
      .reduce((map, day) => ({ ...map, [day]: addDays(day, delta) }), {} as Record<string, string>);
    setCalendarDays(next);
    shiftTodosForDateMap(dateMap);
    setEditingDateIndex(null);
  };

  const requestDeleteCalendarLane = (index: number) => {
    const date = calendarDays[index];
    if (!date || calendarDays.length <= 1) return;
    const fallbackDate = calendarDays[index + 1] || calendarDays[index - 1] || addDays(date, 1);
    const assignments = todos
      .filter((todo) => todo.dueDate === date)
      .reduce((map, todo) => ({ ...map, [todo.id]: fallbackDate }), {} as Record<string, string>);
    setDeletingCalendarLane({ date, index, assignments });
  };

  const setDeleteLaneAssignment = (todoId: string, dueDate: string) => {
    setDeletingCalendarLane((current) =>
      current ? { ...current, assignments: { ...current.assignments, [todoId]: dueDate } } : current,
    );
  };

  const confirmDeleteCalendarLane = () => {
    if (!deletingCalendarLane) return;
    const deletedIndex = deletingCalendarLane.index;
    const dateMap = calendarDays
      .slice(deletedIndex + 1)
      .reduce((map, day) => ({ ...map, [day]: addDays(day, -1) }), {} as Record<string, string>);
    const resolveDeleteAssignment = (dueDate: string) => dateMap[dueDate] || dueDate;
    const now = new Date().toISOString();
    const updatedTodos = todos
      .map((todo) => {
        if (todo.dueDate === deletingCalendarLane.date) {
          const fallbackDate =
            calendarDays[deletedIndex + 1] ||
            calendarDays[deletedIndex - 1] ||
            addDays(todo.dueDate, 1);
          return {
            ...todo,
            dueDate: resolveDeleteAssignment(deletingCalendarLane.assignments[todo.id] || fallbackDate),
            updatedAt: now,
          };
        }
        if (dateMap[todo.dueDate]) {
          return {
            ...todo,
            dueDate: dateMap[todo.dueDate],
            updatedAt: now,
          };
        }
        return null;
      })
      .filter((todo): todo is AgentTodo => Boolean(todo));

    if (updatedTodos.length) {
      setTodos((items) =>
        items.map((item) => updatedTodos.find((todo) => todo.id === item.id) || item),
      );
      updatedTodos.forEach((todo) => {
        void persistTodoAction(tenantId, userId, userName, "update_todo", { todo, ownerUserId: userId }).then((synced) => {
          if (synced) setTodos(synced);
        });
      });
    }
    setCalendarDays((current) =>
      current
        .filter((_, dayIndex) => dayIndex !== deletedIndex)
        .map((day, dayIndex) => (dayIndex >= deletedIndex ? addDays(day, -1) : day)),
    );
    setDeletingCalendarLane(null);
  };

  return (
    <div className="space-y-5">
      {toolbarLeftHost &&
        createPortal(
          <div className="flex items-center gap-3" data-todo-toolbar="filters-and-views">
            <AppSelect
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as TodoStatus | "all")}
              aria-label="筛选待办状态"
              className="h-10 min-w-[116px] rounded-lg border border-[#d1d1d6] bg-white px-3 text-[13px] text-[#1d1d1f] outline-none transition-colors focus:border-[#8ab4ea]"
            >
              <option value="all">全部状态</option>
              <option value="todo">待处理</option>
              <option value="in_progress">进行中</option>
              <option value="done">已完成</option>
              <option value="closed">已关闭</option>
            </AppSelect>
            <div className="flex rounded-lg bg-[#f2f2f7] p-1" aria-label="待办展示方式">
              {[
                { key: "list", label: "列表", icon: ListChecks },
                { key: "kanban", label: "看板", icon: Columns3 },
                { key: "calendar", label: "日历", icon: CalendarDays },
              ].map((view) => (
                <button
                  key={view.key}
                  type="button"
                  onClick={() => setActiveView(view.key as TodoView)}
                  aria-pressed={activeView === view.key}
                  className={`flex h-8 items-center gap-1.5 rounded-md px-3 text-[12px] transition-colors ${
                    activeView === view.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#1d1d1f]"
                  }`}
                >
                  <view.icon className="h-3.5 w-3.5" />
                  {view.label}
                </button>
              ))}
            </div>
          </div>,
          toolbarLeftHost,
        )}
      {toolbarRightHost && activeView !== "list" &&
        createPortal(
          <button
            type="button"
            onClick={() => setAllCardsExpanded(!activeCardsExpanded)}
            data-todo-global-toggle
            className="flex h-10 w-10 items-center justify-center rounded-lg border border-[#e5e5ea] bg-white text-[#636366] transition-colors hover:bg-[#f2f2f7]"
            title={activeCardsExpanded ? "全部折叠" : "全部展开"}
            aria-label={activeCardsExpanded ? "全部折叠" : "全部展开"}
          >
            <QuadChevron expanded={activeCardsExpanded} />
          </button>,
          toolbarRightHost,
        )}
      {syncError && (
        <div className="rounded-lg border border-[#ffe3aa] bg-[#fff7e6] px-3 py-2 text-[12px] text-[#8a5a00]">
          {syncError}；系统不会用内置待办补位。
        </div>
      )}
      {composerOpen && (
        <FormDialog
          title={editingId ? "编辑待办" : "新建待办"}
          description="支持个人事项、团队安排和系统注入任务统一沉淀。"
          onClose={closeComposer}
          widthClassName="max-w-4xl"
          zIndexClassName="z-[120]"
          bodyClassName="grid gap-3"
          footer={<><FormDialogCancelButton onClick={closeComposer}>取消</FormDialogCancelButton><FormDialogPrimaryButton onClick={saveTodo}>{editingId ? "保存修改" : "新建待办"}</FormDialogPrimaryButton></>}
        >
              <input
                value={form.title}
                onChange={(event) => setForm((prev) => ({ ...prev, title: event.target.value }))}
                placeholder="待办标题"
                className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none focus:border-[#c7c7cc]"
              />
              <textarea
                value={form.description}
                onChange={(event) => setForm((prev) => ({ ...prev, description: event.target.value }))}
                placeholder="补充处理背景、验收标准或协作说明"
                className="min-h-[72px] resize-y rounded-lg border border-[#e5e5ea] px-3 py-2 text-[13px] leading-[1.6] outline-none focus:border-[#c7c7cc]"
              />
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                <AppSelect
                  value={form.priority}
                  onChange={(event) => setForm((prev) => ({ ...prev, priority: event.target.value as TodoPriority }))}
                  className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none"
                >
                  <option value="urgent">紧急</option>
                  <option value="high">高优先级</option>
                  <option value="medium">中优先级</option>
                  <option value="low">低优先级</option>
                </AppSelect>
                <AppSelect
                  value={form.status}
                  onChange={(event) => setForm((prev) => ({ ...prev, status: event.target.value as TodoStatus }))}
                  className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none"
                >
                  <option value="todo">待处理</option>
                  <option value="in_progress">进行中</option>
                  <option value="done">已完成</option>
                  <option value="closed">已关闭</option>
                </AppSelect>
                <DatePicker
                  value={form.dueDate}
                  onValueChange={(value) => setForm((prev) => ({ ...prev, dueDate: value }))}
                  ariaLabel="待办截止日期"
                  className="w-full text-[13px]"
                />
                <input
                  value={form.assignee}
                  onChange={(event) => setForm((prev) => ({ ...prev, assignee: event.target.value }))}
                  placeholder="负责人"
                  className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none"
                />
                <input
                  value={form.listName}
                  onChange={(event) => setForm((prev) => ({ ...prev, listName: event.target.value }))}
                  placeholder="项目/清单"
                  className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none"
                />
                <input
                  value={form.labels}
                  onChange={(event) => setForm((prev) => ({ ...prev, labels: event.target.value }))}
                  placeholder="标签，逗号分隔"
                  className="h-10 rounded-lg border border-[#e5e5ea] px-3 text-[13px] outline-none"
                />
              </div>
        </FormDialog>
      )}

      {loading ? (
        <div className="rounded-xl border border-[#f0f0f2] bg-white p-8 text-center text-[13px] text-[#8a8a8e]">
          正在加载待办任务...
        </div>
      ) : activeView === "list" ? (
        <TodoListView
          todos={filteredTodos}
          canReviewRegistration={isSuperAdmin}
          onEdit={openEdit}
          onDelete={deleteTodo}
          onChangeStatus={changeStatus}
          onReviewRegistration={reviewRegistration}
        />
      ) : activeView === "kanban" ? (
        <TodoKanbanView
          todos={filteredTodos}
          collapsedTodoIds={collapsedTodoIds}
          draggingTodoId={draggingTodoId}
          onCreate={(status) => openCreate({ status })}
          onEdit={openEdit}
          onDelete={deleteTodo}
          onChangeStatus={changeStatus}
          onReviewRegistration={reviewRegistration}
          canReviewRegistration={isSuperAdmin}
          onToggleCollapse={toggleTodoCollapsed}
          onDragStart={setDraggingTodoId}
          onDragEnd={() => setDraggingTodoId(null)}
        />
      ) : (
        <TodoCalendarView
          todos={filteredTodos}
          days={calendarDays}
          expanded={calendarExpanded}
          collapsedTodoIds={collapsedTodoIds}
          draggingTodoId={draggingTodoId}
          editingDateIndex={editingDateIndex}
          revealingLane={revealingCalendarLane}
          revealReady={calendarLaneRevealReady}
          deletingLane={deletingCalendarLane}
          onCreate={(dueDate) => openCreate({ dueDate })}
          onEdit={openEdit}
          onDelete={deleteTodo}
          onChangeStatus={changeStatus}
          onMoveDate={moveTodoToDate}
          onToggleCollapse={toggleTodoCollapsed}
          onDragStart={setDraggingTodoId}
          onDragEnd={() => setDraggingTodoId(null)}
          onEditDate={setEditingDateIndex}
          onChangeDate={changeCalendarLaneDate}
          onInsertAfter={insertCalendarLaneAfter}
          onRequestDeleteLane={requestDeleteCalendarLane}
          onCancelDeleteLane={() => setDeletingCalendarLane(null)}
          onSetDeleteLaneAssignment={setDeleteLaneAssignment}
          onConfirmDeleteLane={confirmDeleteCalendarLane}
        />
      )}
    </div>
  );
}

function TodoListView({
  todos,
  canReviewRegistration,
  onEdit,
  onDelete,
  onChangeStatus,
  onReviewRegistration,
}: {
  todos: AgentTodo[];
  canReviewRegistration: boolean;
  onEdit: (todo: AgentTodo) => void;
  onDelete: (todoId: string) => void;
  onChangeStatus: (todo: AgentTodo, status: TodoStatus) => void;
  onReviewRegistration: (todo: AgentTodo, approved: boolean) => void;
}) {
  const pagination = useClientPagination(todos);
  if (todos.length === 0) return <EmptyTodoState />;
  return (
    <div className="overflow-hidden rounded-xl border border-[#f0f0f2] bg-white">
      {pagination.paginated && <div className="flex justify-end border-b border-[#f0f0f2] bg-[#fafbfc] px-4 py-2"><DataPageSelector page={pagination.page} totalPages={pagination.totalPages} shownCount={pagination.items.length} totalCount={pagination.total} onChange={pagination.setPage} ariaLabel="待办列表分页" /></div>}
      {pagination.items.map((todo) => (
        <div key={todo.id} className="grid grid-cols-[36px_1fr_120px_120px_112px_86px] items-center gap-3 border-b border-[#f5f5f7] px-4 py-3 last:border-b-0">
          <button
            onClick={() => onChangeStatus(todo, todo.status === "done" ? "todo" : "done")}
            className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-[#f2f2f7]"
            title={todo.status === "done" ? "标记为待处理" : "标记完成"}
          >
            {todo.status === "done" ? <Check className="h-4 w-4 text-[#258a3f]" /> : <Circle className="h-4 w-4 text-[#c7c7cc]" />}
          </button>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <button
                onClick={() => onEdit(todo)}
                className={`truncate text-left text-[13px] hover:text-[#0b63ce] ${
                  todo.status === "done" ? "text-[#8a8a8e] line-through" : "text-[#1d1d1f]"
                }`}
              >
                {todo.title}
              </button>
              <PriorityBadge priority={todo.priority} />
              <SourceBadge source={todo.source} />
            </div>
            <div className="mt-1 flex min-w-0 items-center gap-2 text-[11px] text-[#8a8a8e]">
              <span className="truncate">{todo.description || "暂无补充说明"}</span>
            </div>
            {todo.source === "weekly_report" && (
              <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-[#8a8a8e]">
                {todo.sourceVersionId && <span>来源版本：{todo.sourceVersionId}</span>}
                {todo.relatedMetric && <span>关联指标：{todo.relatedMetric}</span>}
                {todo.relatedOrg && <span>关联机构：{todo.relatedOrg}</span>}
                {todo.confidence ? <span>置信度：{Math.round(todo.confidence * 100)}%</span> : null}
              </div>
            )}
            <TodoLabels labels={todo.labels} />
          </div>
          <div className="text-[12px] text-[#636366]">{todo.listName}</div>
          <div className="flex items-center gap-1 text-[12px] text-[#636366]">
            <Users className="h-3.5 w-3.5 text-[#aeaeb2]" />
            <span className="truncate">{todo.assignee}</span>
          </div>
          <DueDate todo={todo} />
          <div className="flex justify-end gap-1">
            {canReviewRegistration && isRegistrationTodo(todo) ? (
              <RegistrationReviewButtons todo={todo} onReview={onReviewRegistration} />
            ) : (
              <>
                <button onClick={() => onEdit(todo)} className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]">
                  <PencilLine className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => onDelete(todo.id)} className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d92d20]">
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function TodoKanbanView({
  todos,
  collapsedTodoIds,
  draggingTodoId,
  onCreate,
  onEdit,
  onDelete,
  onChangeStatus,
  onReviewRegistration,
  canReviewRegistration,
  onToggleCollapse,
  onDragStart,
  onDragEnd,
}: {
  todos: AgentTodo[];
  collapsedTodoIds: Set<string>;
  draggingTodoId: string | null;
  onCreate: (status: TodoStatus) => void;
  onEdit: (todo: AgentTodo) => void;
  onDelete: (todoId: string) => void;
  onChangeStatus: (todo: AgentTodo, status: TodoStatus) => void;
  onReviewRegistration: (todo: AgentTodo, approved: boolean) => void;
  canReviewRegistration: boolean;
  onToggleCollapse: (todoId: string) => void;
  onDragStart: (todoId: string) => void;
  onDragEnd: () => void;
}) {
  const todoById = useMemo(() => new Map(todos.map((todo) => [todo.id, todo])), [todos]);
  const dropOnStatus = (event: DragEvent<HTMLDivElement>, status: TodoStatus) => {
    event.preventDefault();
    const todoId = event.dataTransfer.getData("text/plain") || draggingTodoId;
    const todo = todoId ? todoById.get(todoId) : null;
    if (todo) onChangeStatus(todo, status);
    onDragEnd();
  };

  return (
    <div className="grid grid-cols-4 gap-4">
      {kanbanColumns.map((column) => {
        const columnTodos = todos.filter((todo) => todo.status === column.status);
        return (
          <div
            key={column.status}
            data-todo-status-lane={column.status}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => dropOnStatus(event, column.status)}
            className={`min-h-[360px] rounded-xl border border-[#f0f0f2] bg-[#fafbfc] p-3 transition-colors ${
              draggingTodoId ? "ring-1 ring-[#d1d1d6]" : ""
            }`}
          >
            <div className="mb-3 flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <div className="text-[13px] text-[#1d1d1f]">{column.title}</div>
                <span className="rounded-full bg-white px-2 py-0.5 text-[11px] text-[#8a8a8e]">{columnTodos.length}</span>
              </div>
              <button
                type="button"
                onClick={() => onCreate(column.status)}
                className="flex h-7 w-7 items-center justify-center rounded-lg bg-white text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                title={`新建${column.title}待办`}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="space-y-3">
              {columnTodos.map((todo) => (
                <TodoCard
                  key={todo.id}
                  todo={todo}
                  expanded={!collapsedTodoIds.has(todo.id)}
                  draggable
                  onEdit={onEdit}
                  onDelete={onDelete}
                  onChangeStatus={onChangeStatus}
                  onReviewRegistration={onReviewRegistration}
                  canReviewRegistration={canReviewRegistration}
                  onToggleCollapse={onToggleCollapse}
                  onDragStart={onDragStart}
                  onDragEnd={onDragEnd}
                />
              ))}
              {columnTodos.length === 0 && (
                <div className="rounded-lg border border-dashed border-[#d1d1d6] bg-white p-5 text-center text-[12px] text-[#aeaeb2]">
                  暂无任务
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TodoCalendarView({
  todos,
  days,
  expanded,
  collapsedTodoIds,
  draggingTodoId,
  editingDateIndex,
  revealingLane,
  revealReady,
  deletingLane,
  onCreate,
  onEdit,
  onDelete,
  onChangeStatus,
  onMoveDate,
  onToggleCollapse,
  onDragStart,
  onDragEnd,
  onEditDate,
  onChangeDate,
  onInsertAfter,
  onRequestDeleteLane,
  onCancelDeleteLane,
  onSetDeleteLaneAssignment,
  onConfirmDeleteLane,
}: {
  todos: AgentTodo[];
  days: string[];
  expanded: boolean;
  collapsedTodoIds: Set<string>;
  draggingTodoId: string | null;
  editingDateIndex: number | null;
  revealingLane: CalendarLaneReveal;
  revealReady: boolean;
  deletingLane: CalendarLaneDeleteState;
  onCreate: (dueDate: string) => void;
  onEdit: (todo: AgentTodo) => void;
  onDelete: (todoId: string) => void;
  onChangeStatus: (todo: AgentTodo, status: TodoStatus) => void;
  onMoveDate: (todo: AgentTodo, dueDate: string) => void;
  onToggleCollapse: (todoId: string) => void;
  onDragStart: (todoId: string) => void;
  onDragEnd: () => void;
  onEditDate: (index: number | null) => void;
  onChangeDate: (index: number, nextDate: string) => void;
  onInsertAfter: (index: number) => void;
  onRequestDeleteLane: (index: number) => void;
  onCancelDeleteLane: () => void;
  onSetDeleteLaneAssignment: (todoId: string, dueDate: string) => void;
  onConfirmDeleteLane: () => void;
}) {
  const todoById = useMemo(() => new Map(todos.map((todo) => [todo.id, todo])), [todos]);
  const deleteLaneTodos = deletingLane ? todos.filter((todo) => todo.dueDate === deletingLane.date) : [];
  const deleteLaneDateOptions = deletingLane
    ? days.filter((_, dayIndex) => dayIndex !== deletingLane.index)
    : [];
  const dropOnDay = (event: DragEvent<HTMLDivElement>, day: string) => {
    event.preventDefault();
    const todoId = event.dataTransfer.getData("text/plain") || draggingTodoId;
    const todo = todoId ? todoById.get(todoId) : null;
    if (todo) onMoveDate(todo, day);
    onDragEnd();
  };

  return (
    <div className="overflow-x-auto pb-2">
      <div className="flex items-stretch gap-0">
      {days.map((day, dayIndex) => {
        const dayTodos = todos.filter((todo) => todo.dueDate === day);
        const weekend = isWeekend(day);
        const editable = canEditCalendarDate(day);
        const targetWidth = expanded ? 280 : 156;
        const isRevealingLane = revealingLane?.date === day && revealingLane.index === dayIndex;
        const laneWidth = isRevealingLane && !revealReady ? 0 : targetWidth;
        const laneOpacity = isRevealingLane && !revealReady ? 0 : 1;
        return (
          <div key={`${day}_${dayIndex}`} className="flex items-stretch">
            <div
              data-calendar-date-lane={day}
              data-calendar-expanded={expanded ? "true" : "false"}
              data-calendar-revealing={isRevealingLane ? "true" : "false"}
              data-calendar-weekend={weekend ? "true" : "false"}
              onContextMenu={(event) => {
                const target = event.target as HTMLElement;
                if (target.closest("button,input,select,textarea,a,[role='button'],[data-todo-card]")) return;
                event.preventDefault();
                onRequestDeleteLane(dayIndex);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => dropOnDay(event, day)}
              style={{
                width: laneWidth,
                minWidth: laneWidth,
                maxWidth: laneWidth,
                flex: `0 0 ${laneWidth}px`,
                opacity: laneOpacity,
              }}
              className={`relative min-h-[320px] shrink-0 overflow-hidden rounded-xl border border-[#f0f0f2] p-3 transition-[width,min-width,max-width,flex-basis,opacity,background-color,border-color] duration-300 ease-out ${
                weekend ? "bg-[#f7f7f8]" : "bg-white"
              } ${draggingTodoId ? "ring-1 ring-[#d1d1d6]" : ""}`}
            >
              <div className="mb-3 flex items-start justify-between gap-2">
                <div
                  role={editable ? "button" : undefined}
                  tabIndex={editable ? 0 : undefined}
                  onClick={() => editable && onEditDate(dayIndex)}
                  className={`${editable ? "cursor-pointer rounded-md px-1 hover:bg-[#f2f2f7]" : ""}`}
                >
                  <div className="text-[12px] text-[#8a8a8e]">{formatWeekday(day)}</div>
                  <div className="text-[15px] text-[#1d1d1f]">{formatMonthDay(day)}</div>
                </div>
                <button
                  type="button"
                  onClick={() => onCreate(day)}
                  className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-[#fafbfc] text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                  title={`新建${formatMonthDay(day)}待办`}
                >
                  <Plus className="h-3.5 w-3.5" />
                </button>
              </div>
              {editingDateIndex === dayIndex && (
                <div className="absolute left-3 top-14 z-20 rounded-lg border border-[#e5e5ea] bg-white p-2 shadow-xl shadow-black/10">
                  <DatePicker
                    value={day}
                    min={todayIso()}
                    autoFocus
                    ariaLabel={`修改${formatMonthDay(day)}日期`}
                    onValueChange={(value) => onChangeDate(dayIndex, value)}
                    onBlur={() => onEditDate(null)}
                    className="h-8 text-[12px]"
                  />
                </div>
              )}
              <div className="space-y-2">
                {dayTodos.map((todo) =>
                  expanded ? (
                    <TodoCard
                      key={todo.id}
                      todo={todo}
                      expanded={!collapsedTodoIds.has(todo.id)}
                      draggable
                      onEdit={onEdit}
                      onDelete={onDelete}
                      onChangeStatus={onChangeStatus}
                      onToggleCollapse={onToggleCollapse}
                      onDragStart={onDragStart}
                      onDragEnd={onDragEnd}
                    />
                  ) : (
                    <CalendarCompactTodo
                      key={todo.id}
                      todo={todo}
                      onEdit={onEdit}
                      onDragStart={onDragStart}
                      onDragEnd={onDragEnd}
                    />
                  ),
                )}
                {dayTodos.length === 0 && <div className="text-[11px] text-[#c7c7cc]">无安排</div>}
              </div>
            </div>
            {dayIndex < days.length - 1 && <CalendarGapAdd onInsert={() => onInsertAfter(dayIndex)} />}
          </div>
        );
      })}
      <button
        type="button"
        onClick={() => onInsertAfter(days.length - 1)}
        data-calendar-add-lane
        style={{
          width: expanded ? 220 : 132,
          minWidth: expanded ? 220 : 132,
          maxWidth: expanded ? 220 : 132,
          flex: `0 0 ${expanded ? 220 : 132}px`,
        }}
        className="ml-3 flex min-h-[320px] shrink-0 items-center justify-center rounded-xl border border-dashed border-[#dedee3] bg-[#fafbfc] text-[#b8b8bd] transition-colors hover:bg-white hover:text-[#636366]"
        title="新增日期泳道"
      >
        <span className="flex h-14 w-14 items-center justify-center rounded-full border border-dashed border-[#d8d8de] bg-white">
          <Plus className="h-7 w-7" />
        </span>
      </button>
      </div>
      {deletingLane && (
        <CalendarLaneDeleteDialog
          laneDate={deletingLane.date}
          todos={deleteLaneTodos}
          assignments={deletingLane.assignments}
          dateOptions={deleteLaneDateOptions.length ? deleteLaneDateOptions : [addDays(deletingLane.date, 1)]}
          onAssign={onSetDeleteLaneAssignment}
          onCancel={onCancelDeleteLane}
          onConfirm={onConfirmDeleteLane}
        />
      )}
    </div>
  );
}

function TodoCard({
  todo,
  expanded,
  draggable = false,
  onEdit,
  onDelete,
  onChangeStatus,
  onReviewRegistration,
  canReviewRegistration = false,
  onToggleCollapse,
  onDragStart,
  onDragEnd,
}: {
  todo: AgentTodo;
  expanded: boolean;
  draggable?: boolean;
  onEdit: (todo: AgentTodo) => void;
  onDelete: (todoId: string) => void;
  onChangeStatus: (todo: AgentTodo, status: TodoStatus) => void;
  onReviewRegistration?: (todo: AgentTodo, approved: boolean) => void;
  canReviewRegistration?: boolean;
  onToggleCollapse: (todoId: string) => void;
  onDragStart?: (todoId: string) => void;
  onDragEnd?: () => void;
}) {
  const nextStatus: TodoStatus = todo.status === "todo" ? "in_progress" : todo.status === "in_progress" ? "done" : "todo";
  return (
    <div
      data-todo-card={todo.id}
      data-todo-status={todo.status}
      data-todo-due-date={todo.dueDate}
      data-todo-expanded={expanded ? "true" : "false"}
      draggable={draggable}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", todo.id);
        onDragStart?.(todo.id);
      }}
      onDragEnd={onDragEnd}
      className={`rounded-lg border border-[#f0f0f2] bg-white p-3 shadow-sm transition-all ${
        draggable ? "cursor-grab active:cursor-grabbing" : ""
      }`}
    >
      <div className="mb-2 flex items-start justify-between gap-2">
        <button onClick={() => onEdit(todo)} className="min-w-0 flex-1 text-left text-[13px] leading-[1.5] text-[#1d1d1f] hover:text-[#0b63ce]">
          {todo.title}
        </button>
        <div className="flex items-center gap-1">
          <PriorityDot priority={todo.priority} />
          <button
            type="button"
            onClick={() => onToggleCollapse(todo.id)}
            className="rounded-md p-1 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
            title={expanded ? "折叠任务" : "展开任务"}
          >
            {expanded ? <ChevronsUp className="h-3.5 w-3.5" /> : <ChevronsDown className="h-3.5 w-3.5" />}
          </button>
        </div>
      </div>
      {expanded ? (
        <>
          <p className="mb-2 line-clamp-2 text-[12px] leading-[1.6] text-[#8a8a8e]">{todo.description || "暂无补充说明"}</p>
          {todo.source === "weekly_report" && (
            <div className="mb-2 rounded-md bg-[#fafbfc] px-2 py-1.5 text-[10px] leading-[1.5] text-[#8a8a8e]">
              {todo.sourceText && <div>来源：{todo.sourceText}</div>}
              {todo.suggestion && <div>建议：{todo.suggestion}</div>}
            </div>
          )}
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            <PriorityBadge priority={todo.priority} />
            <SourceBadge source={todo.source} />
          </div>
          <TodoLabels labels={todo.labels} />
        </>
      ) : (
        <div className="flex flex-wrap items-center gap-1.5">
          <PriorityBadge priority={todo.priority} />
          <SourceBadge source={todo.source} />
        </div>
      )}
      <div className="mt-3 flex items-center justify-between border-t border-[#f5f5f7] pt-2">
        <div className="min-w-0 text-[11px] text-[#8a8a8e]">
          <div className="truncate">{todo.assignee}</div>
          <div>{formatMonthDay(todo.dueDate)}</div>
        </div>
        <div className="flex gap-1">
          {canReviewRegistration && isRegistrationTodo(todo) && onReviewRegistration ? (
            <RegistrationReviewButtons todo={todo} onReview={onReviewRegistration} />
          ) : (
            <>
              <button
                onClick={() => onChangeStatus(todo, nextStatus)}
                className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]"
                title={`流转到${statusConfig[nextStatus].label}`}
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => onEdit(todo)} className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#f2f2f7]">
                <PencilLine className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => onDelete(todo.id)} className="rounded-lg p-2 text-[#8a8a8e] hover:bg-[#fff1f0] hover:text-[#d92d20]">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function CalendarCompactTodo({
  todo,
  onEdit,
  onDragStart,
  onDragEnd,
}: {
  todo: AgentTodo;
  onEdit: (todo: AgentTodo) => void;
  onDragStart: (todoId: string) => void;
  onDragEnd: () => void;
}) {
  return (
    <div
      data-todo-card={todo.id}
      data-todo-status={todo.status}
      data-todo-due-date={todo.dueDate}
      data-todo-expanded="false"
      draggable
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", todo.id);
        onDragStart(todo.id);
      }}
      onDragEnd={onDragEnd}
      onClick={() => onEdit(todo)}
      className="w-full cursor-grab rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-2 text-left transition-colors hover:border-[#d1d1d6] active:cursor-grabbing"
    >
      <div className="mb-1 flex min-w-0 items-center gap-1.5">
        <span className="min-w-0 flex-1 truncate text-[12px] text-[#1d1d1f]">{todo.title}</span>
        <PriorityDot priority={todo.priority} />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[10px] text-[#8a8a8e]">{todo.assignee}</span>
        <span
          className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-semibold"
          style={{ color: statusConfig[todo.status].color, backgroundColor: statusConfig[todo.status].bg }}
        >
          {statusConfig[todo.status].label}
        </span>
      </div>
    </div>
  );
}

function CalendarLaneDeleteDialog({
  laneDate,
  todos,
  assignments,
  dateOptions,
  onAssign,
  onCancel,
  onConfirm,
}: {
  laneDate: string;
  todos: AgentTodo[];
  assignments: Record<string, string>;
  dateOptions: string[];
  onAssign: (todoId: string, dueDate: string) => void;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <FormDialog
      open
      title="删除日期泳道"
      description={`将删除 ${formatMonthDay(laneDate)} 泳道。${todos.length ? "请先为该泳道中的任务选择迁移日期。" : "该泳道没有任务，可直接删除。"}`}
      widthClassName="max-w-xl"
      zIndexClassName="z-[130]"
      onClose={onCancel}
      dataAttributes={{ "data-calendar-delete-dialog": "true" }}
      footer={<><FormDialogCancelButton onClick={onCancel} /><FormDialogPrimaryButton tone="danger" onClick={onConfirm}>删除</FormDialogPrimaryButton></>}
    >
        {todos.length > 0 && (
          <div className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-3">
            <div className="mb-2 text-[12px] text-[#636366]">迁移泳道内任务</div>
            <div className="space-y-2">
              {todos.map((todo) => (
                <div key={todo.id} className="grid grid-cols-[1fr_150px] items-center gap-3 rounded-lg bg-white px-3 py-2">
                  <div className="min-w-0">
                    <div className="truncate text-[12px] text-[#1d1d1f]">{todo.title}</div>
                    <div className="mt-0.5 truncate text-[11px] text-[#8a8a8e]">{todo.assignee} · {statusConfig[todo.status].label}</div>
                  </div>
                  <AppSelect
                    value={assignments[todo.id] || dateOptions[0]}
                    onChange={(event) => onAssign(todo.id, event.target.value)}
                    className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#1d1d1f] outline-none"
                  >
                    {dateOptions.map((date) => (
                      <option key={date} value={date}>
                        {formatMonthDay(date)}
                      </option>
                    ))}
                  </AppSelect>
                </div>
              ))}
            </div>
          </div>
        )}

    </FormDialog>
  );
}

function CalendarGapAdd({ onInsert }: { onInsert: () => void }) {
  const [pointerY, setPointerY] = useState(160);
  const updatePointer = (event: MouseEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setPointerY(Math.max(18, Math.min(rect.height - 18, event.clientY - rect.top)));
  };
  return (
    <div
      className="group relative flex w-4 shrink-0 items-stretch justify-center"
      onMouseMove={updatePointer}
    >
      <button
        type="button"
        onClick={onInsert}
        data-calendar-gap-add
        style={{ top: pointerY }}
        className="absolute left-1/2 z-10 flex h-7 w-7 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-dashed border-[#d8d8de] bg-white/95 text-[#b8b8bd] opacity-0 shadow-sm transition-[opacity,color,background-color] hover:bg-white hover:text-[#636366] group-hover:opacity-100"
        title="在此插入日期泳道"
      >
        <Plus className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function QuadChevron({ expanded }: { expanded: boolean }) {
  const Icon = expanded ? ChevronUp : ChevronDown;
  return (
    <span className="flex h-6 flex-col items-center justify-center gap-[1px] leading-none">
      {[0, 1, 2, 3].map((index) => (
        <Icon key={index} className="h-[5px] w-3" strokeWidth={2.3} />
      ))}
    </span>
  );
}

function EmptyTodoState() {
  return (
    <div className="rounded-xl border border-[#f0f0f2] bg-white p-10 text-center">
      <ListChecks className="mx-auto mb-3 h-8 w-8 text-[#c7c7cc]" />
      <div className="text-[14px] text-[#1d1d1f]">暂无符合条件的待办任务</div>
      <div className="mt-1 text-[12px] text-[#8a8a8e]">可以调整筛选条件，或新建个人/团队待办。</div>
    </div>
  );
}

function PriorityBadge({ priority }: { priority: TodoPriority }) {
  const config = priorityConfig[priority];
  return (
    <span className="shrink-0 rounded-full px-2 py-0.5 text-[10px]" style={{ color: config.color, backgroundColor: config.bg }}>
      {config.label}
    </span>
  );
}

function RegistrationReviewButtons({
  todo,
  onReview,
}: {
  todo: AgentTodo;
  onReview: (todo: AgentTodo, approved: boolean) => void;
}) {
  return (
    <div className="flex items-center gap-1" data-registration-review="true">
      <button
        type="button"
        onClick={() => onReview(todo, true)}
        className="rounded-lg px-2 py-1 text-[11px] text-[#258a3f] hover:bg-[#eef8f1]"
      >
        同意
      </button>
      <button
        type="button"
        onClick={() => onReview(todo, false)}
        className="rounded-lg px-2 py-1 text-[11px] text-[#d92d20] hover:bg-[#fff1f0]"
      >
        拒绝
      </button>
    </div>
  );
}

function PriorityDot({ priority }: { priority: TodoPriority }) {
  return <span className="mt-1 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: priorityConfig[priority].color }} />;
}

function SourceBadge({ source }: { source: TodoSource }) {
  const config = sourceConfig[source];
  return (
    <span className="shrink-0 rounded-full bg-[#f2f2f7] px-2 py-0.5 text-[10px]" style={{ color: config.color }}>
      {config.label}
    </span>
  );
}

function TodoLabels({ labels }: { labels: string[] }) {
  if (!labels.length) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1">
      {labels.map((label) => (
        <span key={label} className="inline-flex items-center gap-1 rounded bg-[#f2f2f7] px-1.5 py-0.5 text-[10px] text-[#8a8a8e]">
          <Tag className="h-2.5 w-2.5" />
          {label}
        </span>
      ))}
    </div>
  );
}

function DueDate({ todo }: { todo: AgentTodo }) {
  const overdue = !["done", "closed"].includes(todo.status) && todo.dueDate < todayIso();
  return (
    <div className={`text-[12px] ${overdue ? "text-[#d92d20]" : "text-[#636366]"}`}>
      {formatMonthDay(todo.dueDate)}
    </div>
  );
}

function emptyTodoForm(userName: string): TodoFormState {
  return {
    title: "",
    description: "",
    status: "todo",
    priority: "medium",
    dueDate: todayIso(),
    assignee: userName || "当前用户",
    listName: "个人待办",
    labels: "",
  };
}

async function persistTodoAction(tenantId: string, userId: string, userName: string, action: string, payload: Record<string, unknown>) {
  try {
    const response = await runApplicationAction<{ todos?: unknown[] }>({
      tenantId,
      userId,
      moduleKey: "agent_workspace",
      action,
      payload,
    });
    return normalizeTodos(response.module.state.todos, userId, userName);
  } catch {
    return null;
  }
}

function normalizeTodos(value: unknown, currentUserId: string, currentUserName = "当前用户"): AgentTodo[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => normalizeTodo(item, currentUserId, currentUserName)).filter((todo): todo is AgentTodo => Boolean(todo));
}

function normalizeTodo(value: unknown, currentUserId: string, currentUserName: string): AgentTodo | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Record<string, unknown>;
  const title = String(item.title || "").trim();
  if (!title) return null;
  const now = new Date().toISOString();
  const assigneeUserId = String(item.assigneeUserId || item.ownerUserId || item.createdBy || "").trim();
  const storedAssignee = String(item.assignee || "").trim();
  const assignee = assigneeUserId === currentUserId || storedAssignee === currentUserId
    ? currentUserName || "当前用户"
    : storedAssignee && storedAssignee !== assigneeUserId
      ? storedAssignee
      : "未知用户";
  return {
    id: String(item.id || makeTodoId()),
    title,
    description: String(item.description || ""),
    status: normalizeStatus(item.status),
    priority: normalizePriority(item.priority),
    dueDate: normalizeDate(item.dueDate),
    assignee,
    listName: String(item.listName || "个人待办"),
    labels: Array.isArray(item.labels) ? item.labels.map((label) => String(label).trim()).filter(Boolean) : [],
    source: normalizeSource(item.source),
    ownerUserId: String(item.ownerUserId || item.createdBy || ""),
    createdBy: String(item.createdBy || "system"),
    createdAt: String(item.createdAt || now),
    updatedAt: String(item.updatedAt || now),
    sourceVersionId: String(item.sourceVersionId || ""),
    sourceText: String(item.sourceText || ""),
    background: String(item.background || ""),
    suggestion: String(item.suggestion || ""),
    relatedOrg: String(item.relatedOrg || ""),
    relatedMetric: String(item.relatedMetric || ""),
    confidence: Number(item.confidence || 0),
    registrationRequestId: String(item.registrationRequestId || "").replace(/^todo_reg_/, "") || (String(item.id || "").startsWith("todo_reg_") ? String(item.id).slice("todo_reg_".length) : ""),
  };
}

function isRegistrationTodo(todo: AgentTodo) {
  return Boolean(todo.registrationRequestId) || todo.labels.includes("注册审批") || todo.id.startsWith("todo_reg_");
}

function normalizeStatus(value: unknown): TodoStatus {
  return value === "in_progress" || value === "done" || value === "todo" || value === "closed" ? value : "todo";
}

function normalizePriority(value: unknown): TodoPriority {
  return value === "urgent" || value === "high" || value === "medium" || value === "low" ? value : "medium";
}

function normalizeSource(value: unknown): TodoSource {
  return value === "system" || value === "weekly_report" || value === "agent" || value === "manual" ? value : "manual";
}

function normalizeDate(value: unknown) {
  const text = String(value || "").slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(text) ? text : todayIso();
}

function splitLabels(value: string) {
  return value
    .split(/[，,]/)
    .map((label) => label.trim())
    .filter(Boolean)
    .slice(0, 6);
}

function sortTodos(a: AgentTodo, b: AgentTodo) {
  const statusRank: Record<TodoStatus, number> = { todo: 1, in_progress: 2, done: 3, closed: 4 };
  return (
    statusRank[a.status] - statusRank[b.status] ||
    a.dueDate.localeCompare(b.dueDate) ||
    priorityConfig[b.priority].rank - priorityConfig[a.priority].rank ||
    b.updatedAt.localeCompare(a.updatedAt)
  );
}

function todayIso() {
  return formatLocalDate(new Date());
}

function addDaysIso(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return formatLocalDate(date);
}

function addDays(value: string, days: number) {
  const date = parseIsoLocalDate(value);
  date.setDate(date.getDate() + days);
  return formatLocalDate(date);
}

function diffDays(from: string, to: string) {
  const start = parseIsoUtcTime(from);
  const end = parseIsoUtcTime(to);
  return Math.round((end - start) / 86400000);
}

function isWeekend(value: string) {
  const day = parseIsoLocalDate(value).getDay();
  return day === 0 || day === 6;
}

function canEditCalendarDate(value: string) {
  return value > todayIso();
}

function formatMonthDay(value: string) {
  const [, month, day] = value.split("-");
  return `${Number(month)}月${Number(day)}日`;
}

function formatWeekday(value: string) {
  const date = parseIsoLocalDate(value);
  return ["周日", "周一", "周二", "周三", "周四", "周五", "周六"][date.getDay()];
}

function formatLocalDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoLocalDate(value: string) {
  const [year, month, day] = parseIsoDateParts(value);
  return new Date(year, month - 1, day);
}

function parseIsoUtcTime(value: string) {
  const [year, month, day] = parseIsoDateParts(value);
  return Date.UTC(year, month - 1, day);
}

function parseIsoDateParts(value: string): [number, number, number] {
  const [year, month, day] = value.split("-").map((part) => Number(part));
  if (!year || !month || !day) {
    const fallback = new Date();
    return [fallback.getFullYear(), fallback.getMonth() + 1, fallback.getDate()];
  }
  return [year, month, day];
}

function makeTodoId() {
  return `todo_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}
