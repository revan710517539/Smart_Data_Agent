import type { AnalysisSkillAsset } from "./dataAssetApi";

function isGeneratedLearningSkill(skill: AnalysisSkillAsset) {
  return skill.learningOrigin === "smart_data_agent.hermes_learning";
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
    .filter((skill) => !isGeneratedLearningSkill(skill) || !canonicalNames.has(canonicalSkillName(skill.name)))
    .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, "zh-CN"));
}

export function availableAnalysisSkills(skills: AnalysisSkillAsset[]) {
  return displayedAnalysisSkills(skills).filter(
    (skill) => skill.enabled && (!skill.lifecycleStatus || skill.lifecycleStatus === "active"),
  );
}
