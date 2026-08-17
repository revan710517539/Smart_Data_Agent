import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = process.cwd();
const read = (path) => readFileSync(resolve(root, path), "utf8");
const todo = read("src/app/components/TodoWorkspace.tsx");
const messageBoard = read("src/app/components/MessageBoardManagement.tsx");
const auditDomain = read("src/app/components/system-settings/domain.ts");
const auditApi = read("src/app/services/auditApi.ts");
const applicationRoute = read("backend/platform/api/routes/application.py");
const applicationStore = read("backend/platform/application/store.py");
const messageBoardService = read("backend/platform/message_board/service.py");
const auditRoute = read("backend/platform/api/routes/audit.py");
const reportStore = read("backend/platform/reports/postgresql_store.py");
const weeklyDomain = read("src/app/components/weekly-report/domain.ts");
const weeklyReport = read("src/app/components/WeeklyReport.tsx");
const institutionCommentThread = read("src/app/components/context-rail/useInstitutionCommentThread.ts");

const checks = [
  [applicationRoute.includes('action_payload["actorDisplayName"]') && applicationRoute.includes("access_service.user_store.get_profile"), "待办创建必须从登录用户目录读取展示姓名"],
  [applicationStore.includes('payload.get("actorDisplayName") or "当前用户"') && applicationStore.includes('todo["assigneeUserId"] = str(actor_user_id or "")'), "应用存储必须保留内部 actor ID 并独立保存展示姓名"],
  [todo.includes("assigneeUserId === currentUserId || storedAssignee === currentUserId") && todo.includes('currentUserName || "当前用户"'), "历史待办的当前登录账号 ID 必须渲染为登录姓名"],
  [messageBoardService.includes("def _with_author_name") && messageBoardService.includes("user_store.get_profile(author_user_id)"), "留言读取必须用用户目录刷新作者姓名"],
  [!messageBoard.includes("{message.author_user_id}"), "留言板管理不得渲染内部作者 ID"],
  [auditRoute.includes('"actor_name": actor_name or "未知用户"') && auditApi.includes("actor_name: string"), "审计 API 必须独立返回操作人姓名"],
  [auditDomain.includes('user: log.actor_name || "未知用户"') && !auditDomain.includes("user: log.actor_user_id"), "审计页面不得把 actor_user_id 当作姓名"],
  [reportStore.includes("COALESCE(NULLIF(TRIM(author.display_name), ''), author.external_subject) AS author"), "MySQL 周报评论必须用用户档案姓名展示作者"],
  [reportStore.includes("COALESCE(NULLIF(TRIM(resolver.display_name), ''), resolver.external_subject) AS resolved_by"), "MySQL 周报评论完成人必须用用户档案姓名展示"],
  [weeklyDomain.includes("storedAuthor === normalizedUserId") && weeklyDomain.includes('return normalizedUserName && normalizedUserName !== normalizedUserId ? normalizedUserName : "当前用户"'), "历史评论中的当前账号 ID 必须归一化为登录姓名"],
  [weeklyReport.includes("normalizeComments(response.comments, userId, userName)") && institutionCommentThread.includes("normalizeComments(response.comments, userId, userName)") && institutionCommentThread.includes("[reportId, replaceComments, scopeKey, tenantId, userId, userName]"), "周报和多机构分析评论消费者必须传入并跟踪当前登录姓名映射"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(`登录账号名称展示契约失败：\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

console.log(`登录账号名称展示契约通过（${checks.length} 项）`);
