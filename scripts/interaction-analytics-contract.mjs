import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const layout = read("src/app/components/Layout.tsx");
const page = read("src/app/components/InteractionAnalytics.tsx");
const routes = read("src/app/routes.ts");
const preload = read("src/app/routePreload.ts");
const dataPreload = read("src/app/routeDataPreload.ts");
const service = read("src/app/services/interactionAnalyticsApi.ts");
const telemetry = read("src/app/services/interactionTelemetry.ts");
const visuals = read("src/app/components/self-analysis/ResultViews.tsx");
const permissionDomain = read("src/app/components/system-settings/domain.ts");
const accessService = read("backend/platform/access/service.py");
const analyticsRoute = read("backend/platform/api/routes/interaction_events.py");

function expect(condition, message) {
  if (!condition) throw new Error(message);
  process.stdout.write(`PASS ${message}\n`);
}

const messageBoardIndex = layout.indexOf('key: "task-workbench.message-board"');
const analyticsIndex = layout.indexOf('key: "task-workbench.interaction-analytics"');
expect(messageBoardIndex >= 0 && analyticsIndex > messageBoardIndex, "埋点分析必须紧邻留言板管理之后");
expect(routes.includes('path: "agent/interaction-analytics"') && preload.includes("interactionAnalytics"), "埋点分析必须进入统一路由与预加载链路");
expect(dataPreload.includes('path.startsWith("/agent/interaction-analytics")') && service.includes("/api/interaction-events/analytics"), "埋点分析必须读取同一张事件表的轻量汇总接口");
expect(service.includes('scope: "global"') && analyticsRoute.includes("list_global_range") && analyticsRoute.includes('"scope": "global"'), "超级管理员埋点分析必须覆盖全平台跨机构行为");
expect(page.includes("全平台跨机构视角") && page.includes("tenantDisplayName"), "全平台埋点页面必须明确展示机构归属");
expect(page.includes('className="min-h-full p-7"') && page.includes('text-[18px] tracking-tight text-[#1d1d1f]') && page.includes('text-[13px] text-[#aeaeb2]'), "页面边距、标题和副标题必须沿用留言板管理排版");
expect(page.includes('data-page-header-actions="true"') && page.includes('h-9 rounded-lg border border-[#e5e5ea] bg-white'), "页头操作区必须沿用系统按钮高度和边框风格");
expect(page.includes("useState(7)") && service.includes("{ days = 7") && analyticsRoute.includes('int(value or "7")'), "埋点分析前后端默认统计周期必须统一为近 7 天");
expect(page.includes("analyticsRetryDelaysMs") && page.includes("isRetryableInteractionAnalyticsError") && page.includes("页面将在服务就绪后自动恢复"), "API 启动期必须有界自动恢复并明确展示重试状态");
expect(service.includes("normalizeInteractionAnalyticsSnapshot") && service.includes("arrayOrEmpty") && service.includes("breakpoint_summary"), "旧版或不完整响应必须在请求边界补齐集合字段，避免页面崩溃");
expect(page.includes("重新读取") && page.includes('setLoadStatus("failed")'), "不可恢复错误必须保留人工重新读取入口");
expect(page.includes("访问人数") && page.includes("高频指标") && page.includes("访问链路追索"), "页面必须覆盖总览、数据使用和用户轨迹");
expect(page.includes('useState<TrendMetricKey>("visits")') && page.includes("data-trend-metric-card") && page.includes("aria-pressed={selected}"), "总览卡片必须默认选择访问次数，并提供可访问的选择状态");
expect(page.includes('data-weekly-trend-metric={metric}') && page.includes("每周访问人数趋势") && page.includes("每周行为事件趋势") && page.includes("每周访问高峰趋势"), "点击总览卡片必须切换对应的每周趋势口径");
expect(service.includes("peak_hour: number | null") && service.includes("item?.peak_hour ?? null"), "周峰值小时字段必须兼容旧版响应");
expect(telemetry.includes("sanitizeExtensionValue") && telemetry.includes("Array.isArray(value)"), "轻量采集必须保留经过限制的指标与维度数组");
expect(visuals.includes('trackVisual("visualization_result"') && visuals.includes("metric_fields") && visuals.includes("dimension_fields"), "图表必须在最终选择后记录指标和维度结果");
expect(!permissionDomain.includes('"埋点分析"') && !accessService.includes('"埋点分析"'), "角色权限不得提供埋点分析勾选项");
expect(!permissionDomain.includes('"留言板管理"') && !accessService.includes('"留言板管理"'), "角色权限不得提供留言板管理勾选项");
expect(layout.includes("superAdminOnlyMenuKeys") && layout.includes("task-workbench.message-board") && layout.includes("isSuperAdmin"), "留言板管理必须仅超级管理员可见");
