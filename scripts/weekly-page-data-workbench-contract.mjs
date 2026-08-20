import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const weekly = await readFile(path.join(root, "src/app/components/WeeklyReport.tsx"), "utf8");
const menu = await readFile(path.join(root, "src/app/components/weekly-report/AnalysisModules.tsx"), "utf8");
const composer = await readFile(path.join(root, "src/app/components/page-data/PageDataComposer.tsx"), "utf8");
const assignment = await readFile(path.join(root, "src/app/components/page-data/assignment.ts"), "utf8");

assert.doesNotMatch(weekly, /<PageDataComposer\b/, "周报页不应继续渲染独立页面数据入口");
assert.match(composer, /data-weekly-page-data-mode-toggle="true"/, "周报页应复用单一编辑保存切换按钮");
assert.match(composer, /controller\.mode === "browse" \? "编辑" : controller\.savingLayout \? "保存中" : "保存"/, "编辑态按钮必须显示保存并提供保存中状态");
assert.match(weekly, /PageDataModeToggle controller=\{weeklyPageData\} onSave=\{saveReportVersion\}/, "周报保存按钮应同时保存页面布局与周报版本");
assert.match(weekly, /StickyNoteButton onClick=\{stickyNote.show\}/, "经营周报必须在编辑按钮左侧提供统一便签入口");
assert.match(weekly, /StickyNotePanel className="mb-4"/, "经营周报便签必须显示在可视化图表上方");
assert.doesNotMatch(weekly, />\s*保存版本\s*<\/button>/, "周报页不应保留独立保存版本按钮");
assert.match(weekly, /PageDataVisualizationModules controller=\{weeklyPageData\}[\s\S]*assetIds=\{\[item\.sourceId\]\}[\s\S]*showEditorControls=\{false\}[\s\S]*layoutEditable=\{weeklyPageData\.mode === "edit"\}/, "页面数据应按统一条目顺序逐项渲染，编辑态允许缩放且不显示删除控件");
assert.match(weekly, /const defaults: WeeklyDataModule\[\] = \[[\s\S]*weeklyPageData\.assets\.map[\s\S]*analysisModules\.filter/, "页面数据条默认必须位于其他数据条之前");
assert.doesNotMatch(weekly, /kind: "core" as const/, "经营周报不得再把核心指标表现作为周报数据条");
assert.doesNotMatch(menu, /核心指标表现/, "统一周报数据列表不得展示核心指标表现");
assert.match(weekly, /weeklyDataItems\.filter\(\(item\) => item\.visible\)\.map/, "周报正文应按统一数据条的顺序和显隐状态渲染");
assert.match(weekly, /kind: "page-data" as const[\s\S]*deletable: false/, "页面数据条不得提供删除能力");
assert.match(weekly, /kind: "visual-report" as const[\s\S]*deletable: true/, "同步的可视化报表条应提供删除能力");
assert.match(weekly, /kind: "saved-analysis" as const[\s\S]*deletable: true/, "同步的智能分析条应提供删除能力");
assert.match(weekly, /className="rounded-lg px-2\.5 py-1\.5" data-report-meta-key/, "会议时间、汇报人和报告周期外层不得保留底色");
assert.match(weekly, /data-weekly-visual-order-item=\{item\.id\}/, "周报正文中的可视化条目必须声明统一排序目标");
assert.match(weekly, /data-weekly-visual-order-handle=\{item\.id\}/, "周报编辑态中的可视化条目必须提供拖动排序手柄");
assert.match(weekly, /event\.dataTransfer\.setData\("text\/x-weekly-data-item", item\.id\)/, "周报正文拖动必须携带当前条目身份");
assert.match(weekly, /moveWeeklyDataItem\(event\.dataTransfer\.getData\("text\/x-weekly-data-item"\), item\.id\)/, "周报正文放置必须复用统一排序持久化入口");
assert.match(weekly, /VisualReportCards report=\{report\}[\s\S]*layoutEditable=\{weeklyPageData\.mode === "edit"\}/, "周报内同步的可视化报表也必须在编辑态开放缩放");

assert.match(menu, /data-weekly-unified-data-menu="true"/, "下拉框应使用统一周报数据列表");
assert.doesNotMatch(menu, />分析模块</, "统一列表不应再显示分析模块分组");
assert.doesNotMatch(menu, />页面数据</, "统一列表不应再显示页面数据分组");
assert.match(menu, /draggable=\{editable\}/, "不同类型数据条应在编辑态支持统一拖动排序");
assert.match(menu, /aria-label=\{`\$\{item\.visible \? "隐藏" : "显示"\}\$\{item\.title\}`\}/, "每个数据条应提供独立显隐按钮");
assert.match(menu, /item\.deletable \? <button/, "删除按钮只能由条目删除契约控制");

assert.match(assignment, /singleInstitutionAssignedPage\(asset\) === pageCode/, "单机构页面数据必须按数据管理的唯一放置页进入经营周报或机构督导");
assert.match(assignment, /includeNewlyAssigned/, "经营周报和机构督导必须把数据管理新指定的单机构数据追加进页面布局");
assert.match(assignment, /kept.length \? kept : \[\.\.\.availableIds\]/, "多机构分析在没有可用已保存项时仍回落到当前页已配置数据集");
assert.match(composer, /pageDataBelongsToPage\(asset, pageCode\)/, "周报和督导必须按放置页过滤页面数据");
assert.match(composer, /resolvePageDataLayout\(workspace.layout \|\| \[\], availableIds, \{/, "页面必须用统一规则解析已保存布局");
assert.match(composer, /export function usePageDataComposer/, "页面数据状态应复用统一控制器");
assert.match(composer, /fetchPageDataWorkspace/, "页面数据必须一次读取布局与行，避免目录后再逐图请求");
assert.match(composer, /export function PageDataVisualizationModules/, "页面数据图表应支持无独立工具栏渲染");
assert.match(composer, /showEditorControls = true/, "页面数据渲染器应允许周报关闭卡片级删除控件");
assert.match(composer, /layoutEditable = showEditorControls/, "图表网格编辑能力必须与卡片删除复制控件解耦");
assert.match(composer, /ResizableVisualizationGrid editable=\{layoutEditable && mode === "edit"\}/, "页面数据图表只能在编辑态开放缩放");
assert.match(composer, /onCreateText=\{\(config\) => addTextCard\(asset.id, config, instanceKey\)\}/, "页面数据浏览态也必须开放文本框");
assert.match(composer, /action: "set_page_data_notes"/, "文本框必须能在不进入布局编辑时单独保存");
assert.match(composer, /data-page-data-picker="true"/, "其他页面原有页面数据选择器必须保留");
assert.match(composer, /data-page-data-mode-switch="true"/, "其他页面原有编辑保存开关必须保留");

console.log("weekly page data workbench contract passed");
