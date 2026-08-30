import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const componentRoot = path.join(root, "src/app/components");

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => {
    const target = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(target);
    return entry.name.endsWith(".tsx") ? [target] : [];
  }));
  return nested.flat();
}

const files = await sourceFiles(componentRoot);
const sources = new Map(await Promise.all(files.map(async (file) => [path.relative(root, file), await readFile(file, "utf8")])));
const read = (file) => sources.get(file) || "";

const nativeSelectOwners = [...sources].filter(([, source]) => /<select\b/.test(source)).map(([file]) => file);
assert.deepEqual(nativeSelectOwners, ["src/app/components/ui/AppSelect.tsx"], "业务页面不得绕过统一 AppSelect 使用原生 select");
assert.ok(![...sources.values()].some((source) => /type=["']date["']/.test(source)), "业务页面不得绕过统一 DatePicker 使用原生日期输入");

const overlayExceptions = new Set([
  "src/app/components/DataAssets.tsx", // 指标版本侧滑抽屉
  "src/app/components/agent-supervisor/AgentSupervisor.tsx", // 可拖动 Agent 工作台
  "src/app/components/self-analysis/ExecutionHistoryDrawer.tsx", // 执行历史抽屉
  "src/app/components/self-analysis/VoiceInputPopover.tsx", // 语音浮层
]);
const customOverlays = [...sources]
  .filter(([file, source]) => !file.startsWith("src/app/components/ui/") && /fixed inset-0/.test(source) && !overlayExceptions.has(file))
  .map(([file]) => file);
assert.deepEqual(customOverlays, [], "普通业务弹窗必须使用 FormDialog；仅允许登记的抽屉、浮层和工作台例外");

const formDialog = read("src/app/components/ui/FormDialog.tsx");
assert.match(formDialog, /DialogPrimitive\.Portal[\s\S]*?DialogPrimitive\.Overlay[\s\S]*?DialogPrimitive\.Content/, "复杂弹窗必须共享 Portal、遮罩和内容语义");
assert.match(formDialog, /min-h-0 flex-1 overflow-y-auto overscroll-contain/, "复杂弹窗内容超高时必须自动纵向滚动");
assert.match(formDialog, /widthClassName[\s\S]*?heightClassName/, "复杂弹窗必须允许按内容配置宽高上限");

const confirmDialog = read("src/app/components/ui/ConfirmDialog.tsx");
assert.match(confirmDialog, /role="alertdialog"/, "简单确认弹窗必须使用警示确认语义");
assert.match(confirmDialog, /max-w-\[380px\]/, "简单确认弹窗必须保持紧凑尺寸");

const datePicker = read("src/app/components/ui/DatePicker.tsx");
assert.match(datePicker, /data-app-date-picker="true"[\s\S]*?<Calendar/, "日期入口和日历面板必须由统一 DatePicker 组合");
assert.match(datePicker, /format\(day, "yyyy-MM-dd"\)/, "日期组件必须保持既有 ISO 日期数据契约");

const standardPage = read("src/app/components/page-data/StandardAnalysisPage.tsx");
const visualReport = read("src/app/components/VisualReportBuilder.tsx");
const skinManagement = read("src/app/components/SkinManagement.tsx");
const skinTemplateSource = await readFile(path.join(root, "src/app/theme/skinTemplates.ts"), "utf8");
const visualRefreshSource = await readFile(path.join(root, "src/styles/sda-visual-refresh.css"), "utf8");
assert.match(standardPage, /export function StandardReportPageCanvas/, "新报表初始化页必须有共享画布组件");
assert.match(standardPage, /新增页面模块[\s\S]*?点击右上角编辑/, "初始化画布必须提供白色子模块和编辑提示");
assert.match(visualReport, /<StandardAnalysisPageHeader[\s\S]*?<StandardReportPageCanvas/, "可视化报表必须复用机构督导的页头与初始化画布");
assert.match(visualReport, /<StandardAnalysisPageStickyNote/, "新报表页必须复用统一便签交互");
assert.match(standardPage, /data-page-header-actions="true"/, "统一页头必须为便签、编辑和留言板保留同一操作区");
assert.match(skinManagement, /data-skin-management="true"[\s\S]*?data-skin-template=/, "皮肤管理必须提供可审计的模板列表页");
assert.match(skinManagement, /data-skin-preview-dialog[\s\S]*?更换皮肤/, "皮肤模板必须先进入共享弹窗预览并提供明确换肤动作");
assert.match(skinManagement, /功能、字段、权限与点击方式保持不变/, "皮肤管理必须明确视觉变更不改变功能与交互契约");
assert.equal((skinTemplateSource.match(/skin\(\{ id:/g) || []).length, 20, "皮肤管理必须提供二十套独立语义令牌模板");
assert.match(skinTemplateSource, /lightSurfaceTextTokens = \{[\s\S]*?text: "#000000"/, "浅色皮肤必须定义共享的纯黑主文字令牌");
assert.match(skinTemplateSource, /template\.mode === "light"[\s\S]*?\.\.\.lightSurfaceTextTokens/, "所有浅色皮肤必须从共享入口获得高对比文字令牌");
assert.match(visualRefreshSource, /--sda-text: #000000;[\s\S]*?text-\[#3a3a3c\][\s\S]*?color: var\(--sda-text\) !important;/, "白底页面的正文与数据文字必须映射到纯黑主文字令牌");
assert.match(visualRefreshSource, /#root th,[\s\S]*?color: var\(--sda-text\);[\s\S]*?#root td,[\s\S]*?color: var\(--sda-text\);/, "表头和数据单元格必须默认使用主文字令牌");
assert.match(skinManagement, /data-page-header-actions="true"[\s\S]*?恢复默认/, "皮肤页恢复默认和全局留言板必须共用紧凑页头操作区");
assert.match(skinManagement, /\{skinTemplates\.length\} 套/, "皮肤模板数量必须来自唯一模板目录，不能硬编码");

const formDialogConsumers = [...sources.values()].filter((source) => /<FormDialog\b/.test(source)).length;
assert.ok(formDialogConsumers >= 12, `统一复杂弹窗覆盖不足：当前仅 ${formDialogConsumers} 个组件文件`);

console.log(`组件系统合同通过：${formDialogConsumers} 个复杂弹窗消费者，原生下拉框与日期输入均已收口`);
