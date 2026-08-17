import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [platformSource, resetSource, routeSource, workbenchSource, visualSource, pendingSource, domainSource, selfAnalysisSource] = await Promise.all([
  read("src/app/platform/PlatformContext.tsx"),
  read("src/app/platform/sessionUiState.ts"),
  read("src/app/routes.ts"),
  read("src/app/components/self-analysis/useSelfAnalysisWorkbenchPersistence.ts"),
  read("src/app/components/self-analysis/ResultViews.tsx"),
  read("src/app/components/self-analysis/pendingAnalysisRun.ts"),
  read("src/app/components/self-analysis/domain.ts"),
  read("src/app/components/SelfAnalysis.tsx"),
]);

const expectedSessionPrefixes = [
  "sda:self-analysis:workbench:v1:",
  "sda:visual-card:v1:",
  "sda:visual-card:v2:",
  "smart-data-agent:pending-analysis:",
  "smart_data_agent_self_analysis_session_v1:",
];
for (const prefix of expectedSessionPrefixes) {
  assert.ok(resetSource.includes(`\"${prefix}\"`), `新登录必须清理临时状态前缀 ${prefix}`);
}

assert.match(platformSource, /const login = \(session: AuthSession\) => \{[\s\S]*?resetTransientUiStateForNewAuthSession\(\);[\s\S]*?const logout =/);
assert.match(platformSource, /const logout = \(\) => \{[\s\S]*?resetTransientUiStateForNewAuthSession\(\);[\s\S]*?const currentTenantRoles/);
assert.ok(resetSource.includes("analysisConversationStoragePrefix") && resetSource.includes("conversationSessionIds") && resetSource.includes("key.endsWith"), "新登录必须让当前对话草稿脱离旧会话");

assert.ok(workbenchSource.includes(expectedSessionPrefixes[0]), "工作台持久化前缀必须纳入重置注册表");
assert.ok(visualSource.includes(expectedSessionPrefixes[2]), "当前可视化卡片持久化前缀必须纳入重置注册表");
assert.ok(pendingSource.includes("smart-data-agent:pending-analysis:"), "待恢复分析前缀必须纳入重置注册表");
assert.ok(domainSource.includes("smart_data_agent_self_analysis_session_v1"), "当前对话会话前缀必须纳入重置注册表");
assert.ok(workbenchSource.includes("sessionStorage.getItem") && workbenchSource.includes("sessionStorage.setItem"), "同一登录会话内离开页面后仍须恢复工作台");
assert.ok(workbenchSource.includes("clearSelfAnalysisWorkbenchPersistence") && workbenchSource.includes("sessionStorage.removeItem"), "页面恢复必须定点删除智能分析工作台快照");
assert.match(selfAnalysisSource, /data-self-analysis-restore="true"/);
assert.match(selfAnalysisSource, /analysisGenerationRef\.current \+= 1[\s\S]*?analysisWaitAbortRef\.current\?\.abort\(\)/, "恢复必须先让旧异步分析结果失效");
assert.match(selfAnalysisSource, /clearPendingAnalysisRun\(tenantId, userId\)[\s\S]*?clearSelfAnalysisWorkbenchPersistence\(tenantId, userId\)/, "恢复必须同时清理待恢复任务与当前工作台快照");
for (const preservedSetter of ["setSavedAnalysisResults", "setAnalysisTopicShortcuts", "setExecutionHistoryTasks", "setSelectedModel"]) {
  const restoreBody = selfAnalysisSource.slice(selfAnalysisSource.indexOf("const restoreInitialAnalysisWorkspace"), selfAnalysisSource.indexOf("const runConfiguredAnalysisShortcut"));
  assert.ok(!restoreBody.includes(`${preservedSetter}(`), `恢复不得删除历史、推荐或模型偏好：${preservedSetter}`);
}

assert.ok(routeSource.includes("smart-data-agent:route-import-retry"), "动态路由恢复保护必须继续存在");
assert.ok(!resetSource.includes("route-import-retry"), "新登录不得清理动态路由恢复保护");
assert.ok(!resetSource.includes("sessionStorage.clear") && !resetSource.includes("localStorage.clear"), "不得粗暴清空浏览器存储");

const preservedBusinessStorageKeys = [
  "smart_data_agent_saved_analysis_results",
  "smart_data_agent_self_analysis_topics_v1",
  "smart-data-agent:text-model-selection",
  "smart_data_agent_metric_dictionary_v2",
  "smart_data_agent_report_comments",
  "smart_data_agent_weekly_report_versions",
  "smart_data_agent_weekly_analysis_modules_v2",
  "smart_data_agent_agent_supervisor_conversations_v1",
];
for (const key of preservedBusinessStorageKeys) {
  assert.ok(!resetSource.includes(key), `正式业务或偏好数据不得被登录重置删除：${key}`);
}

console.log(`session UI reset contract passed (${expectedSessionPrefixes.length} transient prefixes, ${preservedBusinessStorageKeys.length} preserved business keys)`);
