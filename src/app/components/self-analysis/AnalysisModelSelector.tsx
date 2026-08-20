import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import type { ModelIntegration } from "../../services/systemConfigApi";
import { createSelectedAnalysisModel, groupAnalysisModelOptions } from "./domain";

export function AnalysisModelSelector({
  models,
  selectedModel,
  onSelect,
}: {
  models: ModelIntegration[];
  selectedModel: ModelIntegration | null;
  onSelect: (model: ModelIntegration) => void;
}) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const groups = groupAnalysisModelOptions(models);
  useEffect(() => {
    if (!open) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && menuRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [open]);
  return (
    <div ref={menuRef} className="relative shrink-0">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        disabled={!groups.length}
        aria-label="选择分析模型"
        aria-expanded={open}
        className="flex h-7 max-w-[220px] items-center gap-1 rounded-md px-1.5 text-[11px] text-[#636366] transition-colors hover:bg-[#f2f2f7] disabled:cursor-not-allowed disabled:text-[#aeaeb2]"
        title={groups.length ? "选择智能分析推理模型" : "智能分析推理分析模块暂无已鉴权模型"}
      >
        <span className="truncate">{selectedModel?.name || "未配置分析模型"}</span>
        <ChevronDown className={`h-3 w-3 shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && groups.length > 0 && (
        <div className="absolute left-0 top-full z-50 mt-2 max-h-[420px] w-[300px] overflow-y-auto rounded-xl border border-[#e5e5ea] bg-white py-2 shadow-xl shadow-black/10">
          {groups.map((group) => (
            <div key={group.id} data-model-group={group.category} className="border-b border-[#f2f2f7] pb-1.5 last:border-b-0 last:pb-0">
              <div className="px-3 pb-1 pt-1.5 text-[10px] font-semibold text-[#8a8a8e]">{group.category}</div>
              {group.options.map((option) => {
                const selected = option.model.id === selectedModel?.id && option.value === selectedModel.selectedModelName;
                return (
                  <button
                    key={option.id}
                    data-model-option={option.value}
                    type="button"
                    onClick={() => {
                      onSelect(createSelectedAnalysisModel(option));
                      setOpen(false);
                    }}
                    className={`flex w-full items-center justify-between px-3 py-2 text-left text-[12px] transition-colors ${selected ? "bg-[#f2f2f7] font-medium text-[#1d1d1f]" : "text-[#3a3a3c] hover:bg-[#f7f7f9]"}`}
                  >
                    <span className="truncate">{option.label}</span>
                    {selected && <span className="ml-3 h-1.5 w-1.5 shrink-0 rounded-full bg-[#1d1d1f]" />}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
