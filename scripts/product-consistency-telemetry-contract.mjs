import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const files = await Promise.all([
  "src/app/components/VisualReportBuilder.tsx",
  "src/app/components/SelfAnalysis.tsx",
  "src/app/components/DataAssets.tsx",
  "src/app/components/data-assets/TableRelationshipBuilder.tsx",
  "src/app/components/LoginPage.tsx",
  "src/app/components/ui/DataPageSelector.tsx",
  "src/app/components/Layout.tsx",
  "src/app/components/self-analysis/ResultViews.tsx",
  "src/app/components/agent-supervisor/AgentSupervisor.tsx",
  "src/app/services/interactionTelemetry.ts",
  "backend/platform/api/routes/interaction_events.py",
  "backend/platform/api/routes/auth.py",
  "backend/platform/interaction_events.py",
  "backend/platform/database/mysql/migrations/0031_user_interaction_events.sql",
].map((path) => readFile(path, "utf8")));

const [visualReport, selfAnalysis, dataAssets, relationships, login, pagination, layout, visualCard, supervisor, telemetryClient, telemetryRoute, authRoute, telemetryStore, migration] = files;

assert.ok(!visualReport.includes('label="存主题"'), "可视化报表不得显示存主题按钮");
assert.ok(!selfAnalysis.includes('handleSaveTarget("topic")'), "智能分析不得显示存主题入口");
assert.match(visualReport, /if \(destination !== "topic"\) await saveAsTopic\(/, "三个可视化报表保存入口必须自动沉淀 SQL");
assert.match(selfAnalysis, /await saveAsTopicTable\(false\)/, "智能分析保存结果必须自动沉淀 SQL");

assert.match(dataAssets, /onClick=\{\(\) => setRawUploadOpen\(true\)\}[\s\S]*?上传Excel文件/, "上传 Excel 按钮必须打开上传弹窗");
assert.match(dataAssets, /createPortal\(<div[\s\S]*?data-static-workbook-modal-overlay="true"[\s\S]*?<section role="dialog"[\s\S]*?data-static-workbook-dialog="true"[\s\S]*?document\.body\)/, "上传必须使用 Portal 弹窗而非页面跳转");
assert.match(relationships, /createPortal\(<div[\s\S]*?data-table-relationship-modal-overlay="true"[\s\S]*?<section role="dialog"[\s\S]*?data-table-relationship-dialog="true"[\s\S]*?document\.body\)/, "新增表关系必须使用 Portal 弹窗而非页面样式");
assert.match(dataAssets, /event\.key === "Escape" && !uploading/, "上传弹窗必须支持 Escape 安全关闭");
assert.match(relationships, /event\.key === "Escape" && !saving/, "表关系弹窗必须支持 Escape 安全关闭");
assert.ok(!relationships.includes("每个横条是一组经过权限和主键校验的多表关系"), "表关系说明横条必须移除");
assert.ok(!relationships.includes("系统血缘证据"), "系统血缘证据块必须移除");
assert.match(relationships, /const canvasExtent = useMemo/);
assert.match(relationships, /data-relationship-canvas="true"/);
assert.match(relationships, /saving \? "正在保存中……"/);
assert.match(relationships, /onChanged\(saved\)/, "表关系保存后必须用返回值更新列表，不能强制全量重载");
assert.match(dataAssets, /upsertTableRelationship/);

assert.match(login, /data-registration-placeholder="true"[\s\S]*?onClick=\{\(\) => setNotice\(registrationNotice\)\}[\s\S]*?注册新用户/, "登录页必须显示不可注册但可反馈的注册占位按钮");
assert.match(login, /aria-disabled="true"[\s\S]*?cursor-not-allowed/, "注册占位按钮必须使用灰显的不可用语义和样式");
assert.match(login, /registrationNotice = "建设中……"/, "注册占位按钮必须反馈建设中状态");
assert.match(login, /data-login-primary-actions="true"/, "取消和登录按钮必须保持右侧操作组");
assert.match(login, /const \[password, setPassword\] = useState\(""\)/, "登录页密码必须默认留空");
assert.match(login, /setPassword\(""\)/, "取消登录必须清空密码");
assert.ok(!login.includes("123456"), "登录页源码不得包含可用的默认密码");
assert.match(authRoute, /os\.getenv\("SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD", ""\)/, "开发登录密码缺失时必须失败关闭");
assert.ok(!authRoute.includes('"123456"'), "认证路由不得保留历史密码兜底");
assert.match(selfAnalysis, /reportKindTab === "analysis" \? "新建智能分析" : "新建可视化报表"/);
assert.ok(!selfAnalysis.includes(">全部</button>"), "我的报表智能分析 Tab 不得保留全部按钮");

assert.match(pagination, /pageSize = 20/);
assert.match(pagination, /paginated: items\.length > pageSize/);
for (const component of [relationships, selfAnalysis]) {
  assert.ok(component.includes("useClientPagination"), "可能超过 20 条的列表必须接入统一分页");
}

for (const eventName of ["primary_menu_click", "secondary_menu_click", "institution_select", "sidebar_todo_click", "sidebar_collapse_click", "sidebar_expand_click", "model_select"]) {
  assert.ok(layout.includes(eventName), `缺少 ${eventName} 埋点`);
}
for (const eventName of ["visual_follow_up_click", "visual_show_data_click", "visual_hide_data_click", "visual_style_click", "visual_metric_click", "visual_dimension_click", "visual_voice_click", "visual_more_click", "visual_condition_click", "visual_copy_click", "visual_delete_click"]) {
  assert.ok(visualCard.includes(eventName), `缺少 ${eventName} 埋点`);
}
for (const eventName of ["assistant_robot_click", "assistant_current_page_click", "assistant_metric_click", "assistant_memory_click", "assistant_skill_click", "assistant_analysis_click", "assistant_voice_click", "assistant_realtime_voice_click", "assistant_question_submit", "assistant_reply"]) {
  assert.ok(supervisor.includes(eventName), `缺少 ${eventName} 埋点`);
}
assert.match(telemetryClient, /keepalive: true/);
assert.ok(!telemetryClient.includes("apiRequest<"), "埋点写入不得清空页面读缓存");
assert.match(telemetryRoute, /_require_explicit_session\(handler\)/);
assert.match(authRoute, /event_name="login_submit"/);
assert.match(authRoute, /except Exception:[\s\S]*?Telemetry is best effort/);
assert.match(telemetryStore, /sanitize_interaction_extension/);
assert.match(migration, /CREATE TABLE platform_user_interaction_events/);

const wheelHandler = visualCard.match(/const passWheelToPage = \(event:[\s\S]*?\n  \};/)?.[0] || "";
assert.match(wheelHandler, /scrollOwner\.scrollBy/);
assert.ok(!wheelHandler.includes("event.preventDefault("), "图表滚轮不得触发 passive preventDefault 错误");

console.log("product consistency and telemetry contract passed");
