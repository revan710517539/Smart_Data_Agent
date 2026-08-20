import { ChevronsDown, ChevronsUp, Sparkles } from "lucide-react";
import type { AnalysisTopicShortcut, TopicShortcutMenuState } from "./domain";

export function AnalysisTopicShortcuts({
  topics,
  expanded,
  editingId,
  menu,
  onToggleExpanded,
  onRunTopic,
  onOpenMenu,
  onRenameTopic,
  onFinishEditing,
  onStartEditing,
  onDeleteTopic,
}: {
  topics: AnalysisTopicShortcut[];
  expanded: boolean;
  editingId: string | null;
  menu: TopicShortcutMenuState;
  onToggleExpanded: () => void;
  onRunTopic: (topic: AnalysisTopicShortcut) => void;
  onOpenMenu: (state: Exclude<TopicShortcutMenuState, null>) => void;
  onRenameTopic: (topicId: string, title: string) => void;
  onFinishEditing: (topicId: string) => void;
  onStartEditing: (topicId: string) => void;
  onDeleteTopic: (topicId: string) => void;
}) {
  const openTopic = menu ? topics.find((topic) => topic.id === menu.id) : null;
  const canToggleExpanded = topics.length > 4;
  if (!topics.length) return null;
  return (
    <div className="relative">
      <div className={`flex flex-wrap gap-2 ${canToggleExpanded ? "pr-9" : ""} ${canToggleExpanded && !expanded ? "max-h-[62px] overflow-hidden" : ""}`}>
        {topics.map((topic) => (
          <div key={topic.id} className="relative">
            {editingId === topic.id ? (
              <input
                autoFocus
                value={topic.title}
                onChange={(event) => onRenameTopic(topic.id, event.target.value)}
                onBlur={() => onFinishEditing(topic.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onFinishEditing(topic.id);
                  }
                  if (event.key === "Escape") {
                    event.preventDefault();
                    onFinishEditing(topic.id);
                  }
                }}
                className="h-7 w-[220px] rounded-md border border-[#d1d1d6] bg-white px-2 text-[11px] font-semibold text-[#1d1d1f] outline-none focus:border-[#8e8e93]"
              />
            ) : (
              <button
                type="button"
                onClick={() => onRunTopic(topic)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  onOpenMenu({ id: topic.id, x: event.clientX, y: event.clientY });
                }}
                title={`分析方法：${topic.method}\nSQL：${topic.sql}\n结论生成方式：${topic.conclusionMode}`}
                className="inline-flex h-7 max-w-[280px] items-center gap-1.5 rounded-md border border-[#d7efd9] bg-[#eef8f1] px-2.5 text-[11px] font-semibold text-[#258a3f] transition-colors hover:bg-[#e1f3e6]"
              >
                <Sparkles className="h-3 w-3 shrink-0" />
                <span className="truncate">{topic.title}</span>
              </button>
            )}
          </div>
        ))}
      </div>
      {canToggleExpanded && (
        <button
          type="button"
          onClick={onToggleExpanded}
          className="absolute bottom-0 right-0 flex h-7 w-7 items-center justify-center rounded-full border border-[#e5e5ea] bg-white text-[#8a8a8e] shadow-sm hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
          aria-label={expanded ? "折叠分析主题" : "展开历史分析主题"}
        >
          {expanded ? <ChevronsUp className="h-3.5 w-3.5" /> : <ChevronsDown className="h-3.5 w-3.5" />}
        </button>
      )}
      {menu && openTopic && (
        <div
          className="fixed z-[100] w-24 rounded-lg border border-[#e5e5ea] bg-white p-1 shadow-lg shadow-black/10"
          style={{ left: menu.x, top: menu.y + 6 }}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={(event) => event.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => onStartEditing(openTopic.id)}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]"
          >
            编辑
          </button>
          <button
            type="button"
            onClick={() => onDeleteTopic(openTopic.id)}
            className="w-full rounded-md px-2 py-1.5 text-left text-[12px] text-[#d93025] hover:bg-[#f2f2f7]"
          >
            删除
          </button>
        </div>
      )}
    </div>
  );
}
