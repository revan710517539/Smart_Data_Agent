import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

const dataAssets = read("src/app/components/DataAssets.tsx");
const pageDataAssets = read("src/app/components/data-assets/PageDataAssets.tsx");
const customerPage = read("src/app/components/CustomerSegmentAnalysis.tsx");
const standardPage = read("src/app/components/page-data/StandardAnalysisPage.tsx");
const layout = read("src/app/components/Layout.tsx");
const routes = read("src/app/routes.ts");
const customerApi = read("src/app/services/customerSegmentApi.ts");
const customerList = read("backend/platform/customer_segment/customer_list.py");
const assetRoutes = read("backend/platform/api/routes/assets.py");
const csvSource = read("backend/platform/ingestion/csv_folder.py");
const unifiedSource = read("backend/platform/ingestion/unified_raw.py");
const applicationStore = read("backend/platform/application/store.py");
const apiRouter = read("backend/platform/api/router.py");

assert.ok(
  dataAssets.indexOf('{ key: "single_page"') < dataAssets.indexOf('{ key: "relationships"')
  && dataAssets.indexOf('{ key: "relationships"') < dataAssets.indexOf('{ key: "multi_page"')
  && dataAssets.indexOf('{ key: "multi_page"') < dataAssets.indexOf('{ key: "customer_segment_page"'),
  "表关系必须位于单机构页面和多机构页面之间，分客群页面必须位于多机构页面右侧",
);
assert.match(dataAssets, /activeTab === "customer_segment_page"[\s\S]*?<PageDataCreateButton scope="customer_segment"/, "分客群 Tab 必须在标签左侧提供新增明细数据入口");
assert.match(dataAssets, /customerDetailTables = bundle\.raw_tables\.filter[\s\S]*?customerDetailTableKey/, "分客群数据源必须先按客户号唯一主键过滤");
assert.match(dataAssets, /rawTables=\{pageDataEditor\.scope === "customer_segment" \? customerDetailTables : rawTables\}/, "分客群弹窗不得收到其他原始表");
assert.match(pageDataAssets, /primaryFields\.length !== 1/, "客户明细表必须只有一个主键");
assert.match(pageDataAssets, /客户号|customerid/, "客户明细表主键必须具备客户号语义");

assert.match(layout, /business-analysis\.supervision[\s\S]*?business-analysis\.customer-segment/, "分客群分析必须位于机构督导之后");
assert.match(routes, /path: "customer-segment-analysis"[\s\S]*?CustomerSegmentAnalysis/, "分客群分析必须有真实路由");
assert.match(customerPage, /data-upload-customer-segment-list="true"/, "页面右上角必须有上传客群名单按钮");
assert.match(customerPage, /StandardAnalysisPageHeader[\s\S]*?leadingActions=[\s\S]*?data-upload-customer-segment-list/, "上传客群名单必须位于标准页头默认动作左侧");
assert.match(customerPage, /StandardAnalysisPageStickyNote/, "分客群分析必须显示与机构督导一致的页面便签");
assert.doesNotMatch(customerPage, /<PageDataModeToggle/, "分客群工作区不得重复渲染编辑按钮");
assert.ok(standardPage.indexOf("{leadingActions}") < standardPage.indexOf("<StickyNoteButton"), "标准页头动作顺序必须为业务动作、便签、编辑");
assert.match(customerPage, /\.xlsx 格式[\s\S]*?data-customer-segment-preview[\s\S]*?个不重复客户号/, "上传弹窗必须显示 Excel 限制与去重客户数");
assert.match(customerPage, /data-customer-segment-confirm="true"/, "名单校验通过后必须由右下角确认保存");
assert.match(customerApi, /customer-segment\/list\/preview[\s\S]*?customer-segment\/list\/confirm/, "名单预览和确认必须分别调用后端 API");

assert.match(customerList, /worksheet\.iter_rows\(values_only=True\)[\s\S]*?value = row\[0\]/, "后端必须从首个工作表 A1 开始读取且不识别表头");
assert.match(customerList, /if customer_id in seen[\s\S]*?duplicate_count \+= 1/, "后端必须确定性去重客户号");
assert.match(customerList, /ownerUserId/, "确认后的名单必须绑定当前用户");
assert.match(applicationStore, /customerSegmentListsByUser[\s\S]*?actor_user_id/, "非生产适配器也必须按用户隔离名单状态");
assert.match(csvSource, /def read_rows_matching_values[\s\S]*?for source_row in reader/, "Crawler CSV 必须完整扫描并只保留名单客户");
assert.match(unifiedSource, /def read_rows_matching_values/, "静态工作簿原始表必须复用同一名单匹配合同");
assert.match(assetRoutes, /read_rows_matching_values[\s\S]*?source_by_customer[\s\S]*?for customer_id in customer_ids/, "页面数据必须以名单顺序为左表关联明细数据");
assert.doesNotMatch(assetRoutes, /max_rows=50_000 if customer_ids is not None/, "分客群关联不得只读取明细表前五万行");
assert.match(apiRouter, /customer-segment\/list\/preview[\s\S]*?customer-segment\/list\/confirm/, "运行时路由目录必须登记名单预览和确认接口");

console.log("分客群分析合同通过（标准页头、便签编辑、Excel 名单、用户隔离、全量左关联）");
