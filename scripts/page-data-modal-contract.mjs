import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [modalSource, pageSource, composerSource, dashboardSource, supervisionSource, assetRouteSource, applicationRouteSource, assetApiSource] = await Promise.all([
  read("src/app/components/data-assets/PageDataAssets.tsx"),
  read("src/app/components/DataAssets.tsx"),
  read("src/app/components/page-data/PageDataComposer.tsx"),
  read("src/app/components/Dashboard.tsx"),
  read("src/app/components/InstitutionSupervision.tsx"),
  read("backend/platform/api/routes/assets.py"),
  read("backend/platform/api/routes/application.py"),
  read("src/app/services/dataAssetApi.ts"),
]);

assert.match(modalSource, /data-page-data-modal-overlay="true"[\s\S]*?<section[\s\S]*?role="dialog"[\s\S]*?data-page-data-modal="true"/, "全屏遮罩与弹窗内容必须是两个语义层");
assert.doesNotMatch(modalSource, /data-page-data-modal-overlay="true"\s+role="dialog"/, "遮罩本身不得再声明为 dialog");
assert.match(modalSource, /role="dialog"[\s\S]*?aria-modal="true"[\s\S]*?aria-labelledby="page-data-create-title"/, "弹窗内容必须保留可访问的模态语义");
assert.match(modalSource, /data-page-data-primary-fields="true"[\s\S]*?\{scopeLabel\}名称[\s\S]*?原始表/, "名称必须在左、数据集选择必须在右");
assert.match(modalSource, /grid gap-4 md:grid-cols-2 md:items-start/, "两个主字段必须在桌面端同排并在窄屏回落为单列");
assert.ok((modalSource.match(/mt-1\.5 h-10 w-full rounded-lg border border-\[#dedee3\]/g) || []).length >= 2, "名称输入框和原始表下拉框必须保持同高同形态");
assert.match(modalSource, /bg-\[rgba\(18,33,27,0\.22\)\]/, "遮罩必须保留系统的轻量深绿中性色");
assert.doesNotMatch(modalSource, /data-page-data-modal-overlay="true"[\s\S]{0,260}backdrop-(?:blur|filter)/, "页面数据弹窗不得使用高成本背景模糊");
assert.match(modalSource, /style=\{\{ contain: "layout paint" \}\}/, "弹窗内容必须隔离布局与绘制范围");
assert.match(modalSource, /event\.key === "Escape"[\s\S]*?onClose\(\)/, "Escape 必须关闭未保存的弹窗");
assert.match(modalSource, /event\.target === event\.currentTarget && !saving/, "点击遮罩必须只关闭未保存的弹窗");
assert.match(modalSource, /经营周报[\s\S]*?机构督导/, "单机构页面下拉框只能提供经营周报和机构督导");
assert.match(modalSource, /<select[\s\S]*?onPageChange[\s\S]*?<Pencil[\s\S]*?<Trash2/, "数据横条右侧必须依次提供页面下拉框、编辑和删除");
assert.match(modalSource, /新增单机构数据/, "必须提供新增单机构数据按钮文案");
assert.match(modalSource, /新增多机构数据/, "必须提供新增多机构数据按钮文案");
assert.match(pageSource, /单机构页面[\s\S]*?多机构页面[\s\S]*?主题表[\s\S]*?表关系/, "数据管理必须提供相邻的单机构页面和多机构页面标签");
assert.match(pageSource, /fetchMultiInstitutionPageDataCandidates\(\{ tenantId, userId \}\)/, "多机构弹窗必须按当前账号读取受权候选");
assert.match(modalSource, /已在表关系中显式关联且结构一致/, "多机构弹窗必须说明显式表关系和同构约束");
assert.match(modalSource, /系统不会根据同名表或同名字段自动匹配/, "无表关系时必须失败关闭而不是按名称猜测");
assert.match(pageSource, /saveDataAssetItem\(\{ tenantId, userId, itemType: "page_data", item \}\)/, "保存必须继续复用当前账号的既有授权 API");
assert.match(assetRouteSource, /def _multi_relationship_endpoint[\s\S]*?relationshipScope/, "后端候选必须只接受显式多机构表关系");
assert.match(assetRouteSource, /def _multi_institution_candidates[\s\S]*?schemas = \{str\(table\.get\("schemaFingerprint"\)/, "后端候选必须校验结构指纹一致");
assert.match(applicationRouteSource, /module_key in \{"dashboard", "institution_supervision"\}[\s\S]*?has_super_admin_role/, "多机构分析和机构督导布局保存必须由后端校验超级管理员");
assert.match(dashboardSource, /isSuperAdmin[\s\S]*?canEditLayout=\{isSuperAdmin\}[\s\S]*?showEditorControls=\{isSuperAdmin\}/, "多机构分析页面级编辑控件必须仅对超级管理员显示");
assert.match(supervisionSource, /isSuperAdmin[\s\S]*?canEditLayout=\{isSuperAdmin\}[\s\S]*?showEditorControls=\{isSuperAdmin\}/, "机构督导页面级编辑控件必须仅对超级管理员显示");
assert.match(composerSource, /<AnalysisVisualCard[\s\S]*?onTypeChange=[\s\S]*?onConfigChange=/, "非超级管理员仍必须保留图表内部样式、指标和维度配置入口");
assert.match(composerSource, /const commitLayout[\s\S]*?setLayoutIds\(nextIds\)[\s\S]*?const saveLayout[\s\S]*?runApplicationAction/, "编辑过程必须本地暂存并在点击保存后统一持久化");
assert.match(dashboardSource, /PAGE_DATA_PAGE_GUTTER_CLASS/, "多机构分析必须复用统一页面边距");
assert.match(supervisionSource, /PAGE_DATA_PAGE_GUTTER_CLASS/, "机构督导必须复用统一页面边距");
assert.match(dashboardSource, /!pageData\.loading && pageData\.visibleAssets\.length === 0 && <DashboardState/, "多机构分析已呈现页面数据时不得继续显示内置数据空态");
assert.match(supervisionSource, /!pageData\.loading && pageData\.visibleAssets\.length === 0 && <SupervisionState/, "机构督导已呈现页面数据时不得继续显示内置数据空态");
assert.doesNotMatch(modalSource, /window\.location|navigate\(|href=/, "打开弹窗不得导航或替换当前页面");
assert.match(assetApiSource, /normalizeDataAssetBundle[\s\S]*?table_relationships:\s*Array\.isArray\(bundle\.table_relationships\)\s*\?\s*bundle\.table_relationships\s*:\s*\[\]/, "旧版数据资产响应缺少表关系集合时必须归一为空数组");
assert.match(assetApiSource, /apiRequest<DataAssetBundleWire>[\s\S]*?return normalizeDataAssetBundle\(bundle\)/, "所有数据资产消费者必须经过统一的响应兼容层");

console.log("单机构/多机构页面数据、权限、关系与布局合同通过");
