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
  "src/app/platform/PlatformContext.tsx",
  "src/app/components/SystemSettings.tsx",
  "src/app/components/self-analysis/ResultViews.tsx",
  "src/app/components/agent-supervisor/AgentSupervisor.tsx",
  "src/app/services/interactionTelemetry.ts",
  "backend/platform/api/routes/interaction_events.py",
  "backend/platform/api/routes/auth.py",
  "backend/platform/access/service.py",
  "backend/platform/interaction_events.py",
  "backend/platform/database/mysql/migrations/0031_user_interaction_events.sql",
].map((path) => readFile(path, "utf8")));

const [visualReport, selfAnalysis, dataAssets, relationships, login, pagination, layout, platformContext, systemSettings, visualCard, supervisor, telemetryClient, telemetryRoute, authRoute, accessService, telemetryStore, migration] = files;

assert.ok(!visualReport.includes('label="存主题"'), "可视化报表不得显示存主题按钮");
assert.ok(!selfAnalysis.includes('handleSaveTarget("topic")'), "智能分析不得显示存主题入口");
assert.match(visualReport, /if \(destination !== "topic"\) await saveAsTopic\(/, "三个可视化报表保存入口必须自动沉淀 SQL");
assert.ok(!selfAnalysis.includes("await saveAsTopicTable(false)"), "存报表/存周报/存经验不得再顺带存主题表");
assert.match(selfAnalysis, /useTopicTablePrecipitation/, "智能分析必须在换问题和退出时自动沉淀主题表");
assert.match(selfAnalysis, /prepareQuestionSwitch/, "切换分析问题时必须先沉淀上一轮可存主题表的 SQL");
assert.match(platformContext, /runBeforeLogout/, "退出登录前必须有机会沉淀最新一轮主题表 SQL");

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

assert.match(login, /data-registration-entry="true"[\s\S]*?注册新用户/, "登录页必须开放注册新用户入口");
assert.match(login, /mode === "register"/, "登录页必须提供注册界面");
assert.match(login, /手机号或邮箱/, "注册界面必须允许录入手机号或邮箱");
assert.ok(!login.includes("建设中……"), "注册入口不得再显示建设中占位");
assert.ok(!login.includes('data-registration-placeholder="true"'), "注册入口不得再使用不可用占位按钮");
assert.match(login, /data-login-primary-actions="true"/, "取消和登录按钮必须保持右侧操作组");
assert.match(login, /const \[password, setPassword\] = useState\(""\)/, "登录页密码必须默认留空");
assert.match(login, /setPassword\(""\)/, "取消登录必须清空密码");
assert.match(login, /data-login-survey="true"/, "登录页左侧必须提供数据使用调查");
assert.match(login, /你需要什么指标？/, "登录调查必须询问用户所需指标");
assert.match(login, /你平时怎么用报表？/, "登录调查必须询问报表使用方式");
assert.ok(!login.includes("提交问卷并登录"), "登录调查区不得保留独立提交按钮");
assert.match(login, /loginSurveyDraft\("login"/, "点击登录必须携带当前问卷草稿");
assert.match(login, /loginSurveyDraft\("cancel"/, "点击取消必须触发问卷自动保存");
assert.match(login, /loginSurveyDraft\("pagehide"/, "关闭或离开页面必须触发问卷卸载回传");
assert.match(login, /sendLoginSurveyBeacon/, "页面关闭必须使用浏览器卸载回传能力");
assert.match(login, /setNeededMetrics\(""\)[\s\S]*?setReportUsage\(""\)/, "问卷成功提交或取消后必须恢复为空白");
assert.match(authRoute, /page_key": "login-survey"/, "登录问卷必须写入既有留言板权威存储");
assert.match(authRoute, /message_board\.login_survey\.create/, "登录问卷必须产生独立审计事件");
assert.match(authRoute, /_best_effort_login_survey/, "问卷保存不得改变原有登录成功或失败行为");
assert.ok(!login.includes("123456"), "登录页源码不得包含可用的默认密码");
assert.match(authRoute, /login_by_email\([\s\S]*password=password/, "开发登录必须校验当前账号自己的密码");
assert.ok(!authRoute.includes("SMART_DATA_AGENT_DEVELOPMENT_LOGIN_PASSWORD"), "认证路由不得再使用全员共享的环境登录密码");
assert.ok(!authRoute.includes('"123456"'), "认证路由不得保留历史密码兜底");
assert.match(layout, /data-account-password-toggle="true"/, "登录后必须提供修改本人密码入口");
assert.match(systemSettings, /institutionOptions=\{visibleInstitutions\}/, "新增用户只能选择权威目录中已登记的机构");
assert.match(systemSettings, /tenantId: tenantIdForInstitution\(nextTenant\)/, "新增用户必须把稳定 tenant ID 与显示名分开提交");
assert.ok(!systemSettings.includes("institutionOptions={isSuperAdmin ? operatingTenantNames"), "超级管理员也不得向未登记静态机构授权");
assert.match(systemSettings, /setUserEditorError\(message\)[\s\S]*?setAccessNotice\(message\)/, "新增用户失败必须保留弹窗和表单并显示具体原因");
assert.match(systemSettings, /role="alert" aria-live="polite"[\s\S]*?\{saveError\}/, "新增用户校验错误必须在弹窗内可访问地呈现");
assert.match(systemSettings, /visibleInCurrentInstitution[\s\S]*?当前列表仅显示\$\{selectedInstitution\}用户/, "跨机构新增用户不得短暂插入当前机构列表，且必须解释保存目标");
assert.match(systemSettings, /切换到\{accessNoticeTargetInstitution\}查看/, "跨机构新增用户必须提供显式切换查看入口");
assert.match(systemSettings, /title=\{model\.key \|\| "未配置 API 地址"\}/, "用户接入模型的非敏感 API 地址必须直接可见");
assert.match(systemSettings, /model\.key \|\| "未配置 API 地址"/, "模型地址不得被系统预置地址占位文案替代");
assert.ok(!systemSettings.includes("系统预置地址"), "模型配置不得隐藏系统预置 API 地址");
assert.match(platformContext, /normalized === "sda-internal" \|\| normalized === "SDA 内部环境"/, "机构选择器不得暴露内部技术租户");
assert.match(accessService, /existing_by_email and not requested_user_id[\s\S]*?用户邮箱已存在/, "新增用户不得用已存在邮箱隐式覆盖已有账号");
assert.match(selfAnalysis, /reportKindTab === "analysis" \? "新建智能分析" : "新建可视化报表"/);
assert.match(selfAnalysis, />精选<\/button>/);
assert.match(selfAnalysis, /reportKindTab !== "featured"/);
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
assert.match(wheelHandler, /data-visual-table-scroll/);
assert.ok(!wheelHandler.includes("event.preventDefault("), "图表滚轮不得触发 passive preventDefault 错误");

console.log("product consistency and telemetry contract passed");
