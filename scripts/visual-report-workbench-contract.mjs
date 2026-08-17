import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [layout, routes, builder, library, cards, visualCard, contextRail, selfAnalysis, dataTablePicker, analysisRoute, reportsRoute, application, applicationRoute, productionAssetStore] = await Promise.all([
  readFile("src/app/components/Layout.tsx", "utf8"),
  readFile("src/app/routes.ts", "utf8"),
  readFile("src/app/components/VisualReportBuilder.tsx", "utf8"),
  readFile("src/app/components/visual-report/VisualReportLibrary.tsx", "utf8"),
  readFile("src/app/components/visual-report/VisualReportCards.tsx", "utf8"),
  readFile("src/app/components/self-analysis/ResultViews.tsx", "utf8"),
  readFile("src/app/components/context-rail/ContextSideRail.tsx", "utf8"),
  readFile("src/app/components/SelfAnalysis.tsx", "utf8"),
  readFile("src/app/components/self-analysis/DataTablePickerModal.tsx", "utf8"),
  readFile("backend/platform/api/routes/analysis.py", "utf8"),
  readFile("backend/platform/api/routes/reports.py", "utf8"),
  readFile("backend/platform/application/store.py", "utf8"),
  readFile("backend/platform/api/routes/application.py", "utf8"),
  readFile("backend/platform/assets/postgresql_store.py", "utf8"),
]);

assert.ok(layout.indexOf('label: "可视化报表"') < layout.indexOf('label: "智能分析"'), "可视化报表必须位于智能分析上方");
assert.match(layout, /path: "\/self-analysis\/reports", label: "我的报表"/);
assert.ok(layout.indexOf('label: "经营分析"') < layout.indexOf('label: "我的报表"') && layout.indexOf('label: "我的报表"') < layout.indexOf('label: "自助分析"'), "我的报表必须作为一级菜单位于经营分析与自助分析之间");
assert.equal((layout.match(/label: "我的报表"/g) || []).length, 1, "我的报表菜单只能保留一个入口");
assert.match(routes, /path: "self-analysis\/visual-reports"/);

assert.match(builder, /useState<"browse" \| "edit">\("browse"\)/, "报表必须默认浏览态");
assert.match(builder, /useState<"landing" \| "editor">\("landing"\)/, "可视化报表路由必须先进入落地页");
assert.match(builder, /placeholder="搜索曾经创建过的报表"/);
assert.match(builder, /data-new-visual-report="true"/);
assert.match(builder, /title="最近创建"/);
assert.match(builder, /title="推荐使用"/);
assert.match(builder, /openReport\(newVisualReport\(\), "edit"\)/, "新建报表必须直接进入编辑态");
assert.match(builder, /savedSignatureRef\.current = reportSignature\(selected\)/, "二次编辑必须沿用原报表 ID 与保存签名");
assert.match(builder, /mode === "browse" \? "编辑" : "保存"/, "编辑态按钮必须显示保存");
assert.match(builder, /const saved = await persistReport\(report\)/, "退出编辑态前必须保存当前报表");
assert.match(builder, /navigate\("\/self-analysis\/reports"\)/, "存我的后必须进入我的报表");
assert.match(builder, /WHERE :tenant_id IS NOT NULL/, "存主题必须保留显式租户绑定 SQL 契约");
assert.match(builder, /onDoubleClick=\{\(\) => setEditingTitle\(true\)\}/);
assert.match(builder, /onBlur=\{commitTitle\}/);
assert.match(builder, /data-add-visual-report-chart="true"/);
assert.match(builder, />取消<\/button>/);
assert.match(builder, /data-visual-report-restore="true"/);
assert.match(builder, />保存<\/button>/);
assert.ok(builder.indexOf(">取消</button>") < builder.indexOf("data-visual-report-restore") && builder.indexOf("data-visual-report-restore") < builder.indexOf(">保存</button>"), "新增图表底部按钮必须按取消、恢复、保存排列");
assert.match(builder, /Record<string, VisualChartDraft>/, "未保存图表配置必须按数据集隔离保留");
assert.match(builder, /visualDatasetDraftKey\(dataset\)/, "原始表和主题表切换后必须按数据集恢复草稿");
assert.match(builder, /setVisualChartDrafts\(\{\}\)/, "恢复必须清空本次新增流程的图表草稿");
const draftType = builder.match(/type VisualChartDraft = \{([\s\S]*?)\};/)?.[1] || "";
assert.ok(draftType && !draftType.includes("rows"), "图表草稿不能缓存授权数据行");
for (const label of ["存我的", "存经验", "存周报"]) assert.ok(builder.includes(`label="${label}"`));
assert.ok(!builder.includes('label="存主题"'), "可视化报表不得保留存主题按钮");
assert.match(builder, /if \(destination !== "topic"\) await saveAsTopic\(/, "三个保存入口必须自动沉淀对应 SQL 到主题表");

assert.match(cards, /AnalysisVisualCard/);
assert.match(cards, /revealVisualFollowUp/);
assert.match(cards, /revealVisualComment/);
assert.match(builder, /showFollowUp=\{false\}/, "新增图表弹窗预览必须隐藏追问");
assert.match(visualCard, /showFollowUp = true/, "落地后的标准图表默认必须显示追问");
assert.match(visualCard, /\{showFollowUp && <button[\s\S]*data-visual-follow-up="true"/, "追问按钮显示应由标准图表契约控制");
for (const label of ["评论", "AI 分析", "留言板"]) assert.ok(contextRail.includes(label), `追问右侧栏必须保留${label}`);
assert.match(library, /destination: Extract<VisualReportDestination, "mine" \| "weekly">/);
assert.match(selfAnalysis, />智能分析<\/button>/);
assert.match(selfAnalysis, />可视化报表<\/button>/);
assert.match(dataTablePicker, /label: `多机构页面 \$\{pageDataTables\.length\}`/, "智能分析的数据表选择器必须提供多机构页面");
assert.match(analysisRoute, /consumer="self_analysis"/, "智能分析必须通过受治理的多机构页面读取接口取数");
assert.match(builder, />多机构页面 \{pageDataTables\.length\}<\/button>/, "可视化报表弹窗必须提供多机构页面");
assert.match(builder, /pageCode: "visual_report"/, "可视化报表编辑器必须按自身消费者身份读取多机构页面");
assert.match(cards, /pageCode: railPageKey === "my-reports" \? "my_reports" : "visual_report"/, "我的报表回读可视化报表时必须重新校验多机构页面授权");
assert.match(reportsRoute, /topic_data_store\.read_reference/, "我的报表智能分析 Tab 必须从分析执行的受治理快照回读数据");

assert.match(application, /"upsert_visual_report", "delete_visual_report"/);
assert.match(application, /"visualReports": \[\]/);
assert.doesNotMatch(application, /next_state\["visualReports"\].*rows/s, "可视化报表状态不能持久化原始数据行");
assert.match(applicationRoute, /visual_report_dataset_unavailable/);
assert.match(applicationRoute, /"schemaFingerprint"/);
assert.match(productionAssetStore, /UPDATE platform_data_asset_items[\s\S]*?RETURNING asset_item_id, payload/, "主题候选删除必须返回归档所需的 payload");

console.log("visual report workbench contract passed");
