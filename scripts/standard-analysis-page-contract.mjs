import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

const standard = read("src/app/components/page-data/StandardAnalysisPage.tsx");
const customerSegment = read("src/app/components/CustomerSegmentAnalysis.tsx");
const customers = read("src/app/components/CustomerInsight.tsx");
const competition = read("src/app/components/CompetitionAnalysis.tsx");
const visualReportBuilder = read("src/app/components/VisualReportBuilder.tsx");
const supervision = read("src/app/components/InstitutionSupervision.tsx");
const dashboard = read("src/app/components/Dashboard.tsx");
const applicationStore = read("backend/platform/application/store.py");
const applicationRoute = read("backend/platform/api/routes/application.py");
const postgresStore = read("backend/platform/application/postgresql_store.py");
const layout = read("src/app/components/Layout.tsx");
const dataAssets = read("src/app/components/DataAssets.tsx");

assert.match(standard, /StandardAnalysisPageHeader[\s\S]*?\{leadingActions\}[\s\S]*?<StickyNoteButton[\s\S]*?<PageDataModeToggle/, "标准分析页头必须固定按业务动作、便签、编辑排列");
assert.match(standard, /DEFAULT_REPORT_PAGE_TEMPLATE = "institution-supervision"[\s\S]*?data-default-report-page-template=\{DEFAULT_REPORT_PAGE_TEMPLATE\}/, "机构督导样式必须是后续新报表页面的唯一默认模板");
assert.match(standard, /readVisualGridItemSize[\s\S]*?set_page_visual_layout/, "内置分析页面保存时必须读取并持久化可视化模块尺寸");
assert.match(standard, /拖动排序[\s\S]*?隐藏[\s\S]*?ResizableVisualizationGrid/, "统一编辑态必须支持排序、显隐和缩放");

for (const [name, source] of [["分客群分析", customerSegment], ["客群分析", customers], ["竞品分析", competition], ["机构督导", supervision], ["多机构分析", dashboard]]) {
  assert.match(source, /StandardAnalysisPageHeader/, `${name}必须复用标准分析页头`);
  assert.match(source, /StandardAnalysisPageStickyNote/, `${name}必须复用标准页面便签`);
}
assert.match(customers, /StandardAnalysisPageGrid moduleKey="customer_insight"/, "客群分析必须使用统一可编辑模块网格");
assert.doesNotMatch(customers, /全部分行|selectedBank|select_bank|data-customer-product-switch|消费贷客群|经营贷客群|当前数据模式/, "客群分析不得显示分行、数据模式或贷款客群切换控件");
assert.match(customers, /buildCustomerModel\(snapshot\)[\s\S]*?segmentName[\s\S]*?productLine/, "移除产品切换后必须保留全产品客群内容并明确产品归属");
assert.match(competition, /StandardAnalysisPageGrid moduleKey="competition_analysis"/, "竞品分析必须使用统一可编辑模块网格");
assert.match(competition, /leadingActions=\{productSwitch\}/, "竞品贷款类型滑块必须位于便签左侧");
assert.doesNotMatch(competition, /当前租户暂无已授权、带证据的市场观测；页面不会使用内置竞品数字补位。/, "竞品分析不得显示租户市场观测免责声明");
assert.match(visualReportBuilder, /PAGE_DATA_PAGE_GUTTER_CLASS[\s\S]*?data-default-report-page-template=\{DEFAULT_REPORT_PAGE_TEMPLATE\}/, "新建可视化报表必须默认使用机构督导页面模板和统一边距");

assert.match(applicationStore, /"customer_insight": \{[^\n]*"set_page_visual_layout"[^\n]*"set_page_sticky_note"/, "客群分析必须登记布局与便签动作");
assert.match(applicationStore, /"competition_analysis": \{[^\n]*"set_page_visual_layout"[^\n]*"set_page_sticky_note"/, "竞品分析必须登记布局与便签动作");
assert.match(applicationRoute, /set_page_visual_layout[\s\S]*?has_super_admin_role/, "内置分析页面布局保存必须由后端复核超级管理员权限");
assert.match(postgresStore, /customer_insight[\s\S]*?competition_analysis[\s\S]*?pageVisualLayout/, "生产状态存储必须共享读取客群和竞品页面布局");

assert.match(layout, /data-assets\.data-management", path: "\/data-assets\/data-management", label: "站内数据"/, "左侧菜单必须显示站内数据");
assert.match(dataAssets, /title: "站内数据"[\s\S]*?>站内数据<\/h3>/, "站内数据页面标题必须完成改名");
assert.doesNotMatch(dataAssets, /已连接后端资产配置/, "站内数据成功加载后不得显示后端连接状态子模块");
assert.match(dataAssets, /setBundle\(response\);\s*setNotice\(""\);/, "站内数据成功加载后必须清空同步状态提示");
assert.match(dataAssets, /function AssetNotice[\s\S]*?if \(!notice\) return null;/, "站内数据没有状态提示时不得渲染空白状态子模块");

console.log("标准分析页合同通过（默认便签/编辑、客群与竞品布局、站内数据命名）");
