import type { AnalysisSkillAsset } from "./dataAssetApi";

const sampleAnalysisDatasets = new Set(["loan_operation_mart", "risk_operation_mart"]);

function isGeneratedLearningSkill(skill: AnalysisSkillAsset) {
  return skill.learningOrigin === "smart_data_agent.hermes_learning";
}

function isSampleMartLearningSkill(skill: AnalysisSkillAsset) {
  const datasetId = String(skill.learningTrigger?.datasetId || "").trim();
  return sampleAnalysisDatasets.has(datasetId);
}

function canonicalSkillName(name: string) {
  return name
    .replace(/[（(]AI[）)]/gi, "")
    .split(" · ")[0]
    .trim();
}

/**
 * Keep the runtime picker and Skill plugin on one catalog contract. Legacy
 * learned copies stay hidden when the matching maintained Skill is present.
 */
export function displayedAnalysisSkills(skills: AnalysisSkillAsset[]) {
  const canonicalNames = new Set(
    skills
      .filter((skill) => !isGeneratedLearningSkill(skill))
      .map((skill) => canonicalSkillName(skill.name)),
  );

  return [...skills]
    .filter((skill) => {
      if (!isGeneratedLearningSkill(skill)) return true;
      if (isSampleMartLearningSkill(skill)) return false;
      if (skill.lifecycleStatus && skill.lifecycleStatus !== "active") return false;
      return !canonicalNames.has(canonicalSkillName(skill.name));
    })
    .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, "zh-CN"));
}

export function availableAnalysisSkills(skills: AnalysisSkillAsset[]) {
  return displayedAnalysisSkills(skills).filter(
    (skill) => skill.enabled && (!skill.lifecycleStatus || skill.lifecycleStatus === "active"),
  );
}

export function analysisSkillDisplayLocation(skill: AnalysisSkillAsset) {
  return skill.displayLocation === "hidden" ? "hidden" : "intelligent_analysis";
}

/** Hidden Skills remain available to runtime dispatch but never appear on pages. */
export function pageVisibleAnalysisSkills(skills: AnalysisSkillAsset[]) {
  return availableAnalysisSkills(skills).filter(
    (skill) => analysisSkillDisplayLocation(skill) === "intelligent_analysis",
  );
}

/** Backward-compatible name for the intelligent-analysis add menu consumer. */
export const intelligentAnalysisMenuSkills = pageVisibleAnalysisSkills;
