import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

const manager = read("src/app/components/SkillPluginManager.tsx");
const catalog = read("src/app/services/analysisSkillCatalog.ts");
const selfAnalysis = read("src/app/components/SelfAnalysis.tsx");
const analysisConfig = read("src/app/components/AnalysisConfigManager.tsx");
const dataWorkspace = read("src/app/components/DataAgentWorkspace.tsx");
const store = read("backend/platform/assets/store.py");
const profiles = read("backend/platform/analysis_profiles.py");

assert.ok(!manager.includes("<span>显示位置</span>"), "Skill 场景/主题列表不得保留显示位置列");
assert.ok(!manager.includes("data-skill-display-location"), "Skill 列表不得保留显示位置下拉框");
assert.ok(manager.includes("<span>关联能力</span><span>展示</span><span className=\"text-right\">操作</span>"), "Skill 列表必须在关联能力后回显展示列");
assert.ok(manager.includes("data-skill-display-status={skill.id}"), "每条 Skill 必须回显展示状态");
assert.ok(manager.includes('bg-[#eef8f1] text-[#258a3f]') && manager.includes('bg-[#f2f2f7] text-[#8a8a8e]'), "展示状态必须复用分析配置的绿灰状态样式");
assert.ok(manager.includes('isPageVisible ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />') && manager.includes('isPageVisible ? "展示" : "不展示"'));
assert.ok(manager.includes("启用 Skill 运行时能力</label>") && manager.includes("展示在智能分析页面</label>"), "编辑详情必须水平显示运行时启用和智能分析展示勾选框");
assert.ok(manager.indexOf("启用 Skill 运行时能力</label>") < manager.indexOf("展示在智能分析页面</label>"), "智能分析展示勾选框必须位于运行时启用勾选框右侧");
assert.ok(manager.includes('analysisSkillDisplayLocation(draft) === "intelligent_analysis"'));
assert.ok(manager.includes('displayLocation: event.target.checked ? "intelligent_analysis" : "hidden"'), "勾选状态必须写回既有显示位置字段");
assert.ok(manager.includes('itemType: "analysis_skill"') && manager.includes("normalizeDraftReferences(draft"), "显示位置必须随现有 Skill 保存 API 持久化");
assert.ok(manager.includes("canonicalCoreTopicId") && manager.includes("机构差异应沉淀到 Memory"), "前端必须在提交前解释并阻止机构命名的三类重复 Skill");

assert.ok(catalog.includes("pageVisibleAnalysisSkills"));
assert.ok(catalog.includes('analysisSkillDisplayLocation(skill) === "intelligent_analysis"'));
assert.ok(selfAnalysis.includes('intelligentAnalysisMenuSkills as selectAvailableAnalysisSkills'), "智能分析加号菜单必须使用统一页面可见目录");
assert.ok(analysisConfig.includes("pageVisibleAnalysisSkills"), "分析配置弹窗不得显示运行时内部 Skill");
assert.ok(dataWorkspace.includes("pageVisibleAnalysisSkills"), "自动分析任务等页面选择器不得显示运行时内部 Skill");
assert.ok(catalog.includes("Hidden Skills remain available to runtime dispatch"), "不显示只控制页面可见性，不得移出运行时调度目录");

assert.ok(store.includes("canonical_core_topic_skill_id"));
assert.ok(store.includes("data_asset_duplicate_core_topic_skill"), "后端必须阻止机构名复制三类核心 Skill");
assert.ok(store.includes("data_asset_invalid_analysis_skill_display_location"));
assert.ok(profiles.includes("institution_skills_archived"));
assert.ok(profiles.includes('duplicate_id = f"institution.{slug}.{kind}"'));
assert.ok(!profiles.includes('"name": f"{institution}{method[\'label\']}"'), "准备流程不得再生成机构命名主题 Skill");

console.log("Skill 显示位置与通用主题归并合同通过");
