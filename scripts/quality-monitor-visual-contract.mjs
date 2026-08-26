import fs from "node:fs";

const source = fs.readFileSync("src/app/components/DataAssets.tsx", "utf8");

function expect(condition, message) {
  if (!condition) throw new Error(message);
  process.stdout.write(`PASS ${message}\n`);
}

expect(source.includes('data-quality-monitor="true"'), "质量监控必须保留独立页面语义边界");
expect(source.includes('data-quality-runtime-panel="true"') && source.includes('data-health-summary-grid="true"'), "运行健康必须使用紧凑响应式摘要网格");
expect(source.includes('grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6'), "运行健康必须在窄、中、宽屏稳定为 2/3/6 列");
expect(source.includes('data-quality-overview="true"') && source.includes('data-quality-metric-grid="true"'), "四类质量指标必须归入明确的质量概览层级");
expect(source.includes('data-quality-detail-grid="true"') && source.includes("xl:grid-cols-2"), "异常与覆盖必须在桌面并排、窄屏堆叠");
expect(source.includes('mode === "governed_origin_topic_csv"') && source.includes('return "治理主题 CSV"'), "治理主题数据源编码必须转换为中文且避免溢出");
expect(source.includes("尚无质量评估结果，暂时无法判断是否存在异常"), "没有质量结果时不得误报为健康或无异常");
expect(source.includes("当前不能声称任何数据表已被质量监控覆盖"), "没有任务时不得虚构监控覆盖");
expect(source.includes('text-[14px] text-[#1d1d1f]') && source.includes('text-[11px] text-[#8a8a8e]'), "标题和说明文字必须复用系统字号与颜色层级");
