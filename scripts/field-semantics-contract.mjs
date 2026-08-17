import assert from "node:assert/strict";
import fs from "node:fs";

const dataAssets = fs.readFileSync("src/app/components/DataAssets.tsx", "utf8");
const semantics = fs.readFileSync("src/app/data/fieldSemantics.ts", "utf8");
const model = fs.readFileSync("src/app/components/visualization/visualizationDataModel.ts", "utf8");
const views = fs.readFileSync("src/app/components/self-analysis/ResultViews.tsx", "utf8");
const routes = fs.readFileSync("backend/platform/api/routes/assets.py", "utf8");

assert.match(dataAssets, /字段角色[\s\S]*是否主键/, "字段列表必须在类型前展示角色，并提供是否主键选择");
assert.match(dataAssets, /<option value="metric">指标<\/option><option value="dimension">维度<\/option><option value="date">日期<\/option>/, "角色必须包含指标、维度、日期");
assert.match(semantics, /\["integer", "rate", "decimal"\]/, "指标类型必须包含 integer、rate、decimal");
assert.match(semantics, /minimumFractionDigits: 2, maximumFractionDigits: 2/, "decimal/rate 必须固定显示两位小数");
assert.match(semantics, /type === "rate" \? `\$\{formatted\}%`/, "rate 必须追加百分号");
assert.match(semantics, /type === "integer"[\s\S]*maximumFractionDigits: 0/, "integer 不得显示小数位");
assert.match(model, /semanticRole === "date"[\s\S]*isPrimaryKey/, "趋势图必须先按日期、再按主键选择横轴");
assert.match(views, /normalizeVisualizationSelections\([\s\S]*fieldMetadata\)/, "共享可视化选择必须消费字段语义");
assert.match(routes, /raw_table_metadata_schema_changed/, "字段配置必须校验当前 CSV 结构指纹");
assert.match(routes, /"primaryKeys": primary_keys/, "后端必须投影联合主键");

console.log("field semantics contract passed");
