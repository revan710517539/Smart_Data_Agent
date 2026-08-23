import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const source = readFileSync(resolve(process.cwd(), "src/app/components/CompetitionAnalysis.tsx"), "utf8");
const standardHeader = readFileSync(resolve(process.cwd(), "src/app/components/page-data/StandardAnalysisPage.tsx"), "utf8");
const headerStart = source.indexOf('<StandardAnalysisPageHeader title="竞品分析"');
const switchStart = source.indexOf('data-competition-product-switch="true"');
const gridStart = source.indexOf('<StandardAnalysisPageGrid moduleKey="competition_analysis"');

const checks = [
  [headerStart >= 0, "竞品分析必须保留可识别的标题区"],
  [switchStart >= 0 && source.includes("leadingActions={productSwitch}"), "消费贷/经营贷切换器必须作为标题区右侧首个动作"],
  [gridStart > headerStart, "竞品可视化模块必须紧随标准页头并使用统一编辑网格"],
  [(source.match(/data-competition-product-switch="true"/g) || []).length === 1, "页面只能保留一个竞品产品切换器"],
  [source.includes('aria-label="竞品产品类型"') && source.includes("aria-pressed={productView === tab.key}"), "产品切换器必须保留可访问的选中状态"],
  [standardHeader.indexOf("{leadingActions}") < standardHeader.indexOf("<StickyNoteButton"), "业务切换器必须排在便签按钮左侧"],
  [standardHeader.includes("PageDataModeToggle") && standardHeader.includes("canEditLayout"), "标准页头必须提供权限受控的编辑/保存按钮"],
  [!source.includes("当前租户暂无已授权、带证据的市场观测；页面不会使用内置竞品数字补位。"), "竞品页头不得显示市场观测免责声明"],
];

const failures = checks.filter(([passed]) => !passed).map(([, message]) => message);
if (failures.length) {
  console.error(`竞品分析布局合同失败：\n- ${failures.join("\n- ")}`);
  process.exit(1);
}

console.log("竞品分析布局合同通过（标准页头、右上产品切换、便签、可编辑模块）");
