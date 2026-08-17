import type { ReactNode } from "react";
import { Sparkles, Table2, Upload } from "lucide-react";
import type { AnalysisSkillOption } from "./domain";

export function AnalysisSkillMenu({
  skills,
  onUpload,
  onSelectDataTable,
  onSelectSkill,
}: {
  skills: AnalysisSkillOption[];
  onUpload: () => void;
  onSelectDataTable: () => void;
  onSelectSkill: (skill: AnalysisSkillOption) => void;
}) {
  const sceneSkills = skills.filter((skill) => skill.category === "场景");
  const topicSkills = skills.filter((skill) => skill.category === "主题");
  return <div className="absolute left-0 top-10 z-50 max-h-[420px] w-[520px] max-w-[calc(100vw-48px)] overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white p-1.5 shadow-xl shadow-black/[0.08]">
    <MenuGroup title="添加">
      <button type="button" onClick={onUpload} className="flex h-8 w-full items-center gap-2 rounded-lg px-3 text-left text-[13px] text-[#3a3a3c] hover:bg-[#f2f2f7]"><Upload className="h-4 w-4 text-[#636366]" /><span className="shrink-0">文件上传</span><span className="ml-auto truncate text-[11px] text-[#aeaeb2]">支持多文件</span></button>
      <button type="button" onClick={onSelectDataTable} className="flex h-8 w-full items-center gap-2 rounded-lg px-3 text-left text-[13px] text-[#3a3a3c] hover:bg-[#f2f2f7]"><Table2 className="h-4 w-4 text-[#636366]" /><span className="shrink-0">数据表</span><span className="ml-auto truncate text-[11px] text-[#aeaeb2]">原始表/主题表</span></button>
    </MenuGroup>
    <MenuGroup title="场景">{sceneSkills.map((skill) => <SkillMenuButton key={skill.id} skill={skill} onSelect={onSelectSkill} />)}</MenuGroup>
    <MenuGroup title="主题">{topicSkills.map((skill) => <SkillMenuButton key={skill.id} skill={skill} onSelect={onSelectSkill} />)}</MenuGroup>
  </div>;
}

function MenuGroup({ title, children }: { title: string; children: ReactNode }) {
  return <div className="py-0.5"><div className="px-3 pb-0.5 text-[12px] leading-5 text-[#aeaeb2]">{title}</div><div className="space-y-px">{children}</div></div>;
}

function SkillMenuButton({ skill, onSelect }: { skill: AnalysisSkillOption; onSelect: (skill: AnalysisSkillOption) => void }) {
  return <button type="button" onClick={() => onSelect(skill)} className="flex h-7 w-full items-center gap-2 rounded-lg px-3 text-left hover:bg-[#f2f2f7]"><Sparkles className="h-4 w-4 shrink-0 text-[#636366]" /><span className="flex min-w-0 flex-1 items-baseline gap-2"><span className="shrink-0 text-[13px] font-normal text-[#4b4b50]">{skill.name}</span><span className="min-w-0 truncate whitespace-nowrap text-[11px] text-[#aeaeb2]">{skill.description}</span></span></button>;
}
