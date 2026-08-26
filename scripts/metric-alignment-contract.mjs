import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const [dataAssets, dictionary, store, postgres] = await Promise.all([
  readFile(new URL("../src/app/components/DataAssets.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/app/data/metricDictionary.ts", import.meta.url), "utf8"),
  readFile(new URL("../backend/platform/metrics/store.py", import.meta.url), "utf8"),
  readFile(new URL("../backend/platform/metrics/postgresql_store.py", import.meta.url), "utf8"),
]);

assert.match(dictionary, /alignmentStatus\?: "aligned" \| "unaligned"/, "指标类型必须声明对齐状态");
assert.match(dataAssets, /alignmentStatus: "unaligned"/, "新增和缺省指标必须默认未对齐");
assert.match(dataAssets, /data-metric-primary-actions="true"[\s\S]*data-metric-alignment-select="true"/, "三个操作按钮必须在第一行、对齐状态在第二行");
assert.match(dataAssets, /className="w-24 space-y-1\.5"[\s\S]*className="h-7 w-24/, "操作按钮组和对齐下拉框必须同为 96px 宽");
assert.match(dataAssets, /disabled=\{!canEditMetric\(metric\) \|\| Boolean\(alignmentSavingId\)\}/, "无指标编辑权限时不得修改对齐状态");
assert.match(dataAssets, /saveMetricDictionaryItem\([\s\S]*alignmentStatus/, "对齐状态必须复用后端指标保存入口");
assert.match(dataAssets, /setMetrics\(\(current\) => current\.map[\s\S]*previousMetric/, "保存失败必须回滚原对齐状态");
assert.match(store, /_normalize_alignment_status[\s\S]*\{"aligned", "unaligned"\}/, "后端必须默认并校验对齐状态");
assert.match(postgres, /payload\["alignmentStatus"\] = _normalize_alignment_status/, "旧生产记录读取时必须补齐未对齐默认值");

console.log("metric alignment contract passed");
