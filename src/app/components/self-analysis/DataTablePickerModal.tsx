import { useState } from "react";
import { Search, X } from "lucide-react";
import type { RawTableAsset, TopicTableAsset } from "../../services/dataAssetApi";
import { rawTableToSelection, topicTableToSelection, type AnalysisDataTableSelection } from "./domain";

export function DataTablePickerModal({
  rawTables,
  topicTables,
  selectedTables,
  onChange,
  onClose,
}: {
  rawTables: RawTableAsset[];
  topicTables: TopicTableAsset[];
  selectedTables: AnalysisDataTableSelection[];
  onChange: (tables: AnalysisDataTableSelection[]) => void;
  onClose: () => void;
}) {
  const [activeTab, setActiveTab] = useState<"raw" | "topic">("raw");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [suggestionsOpen, setSuggestionsOpen] = useState(false);
  const selectedId = selectedTables[0]?.id || "";
  const selectTable = (table: AnalysisDataTableSelection) => onChange([table]);
  const rows = activeTab === "raw"
    ? rawTables.map(rawTableToSelection)
    : topicTables.map(topicTableToSelection);
  const normalizeTableName = (value: string) => value.toLocaleLowerCase().replace(/[\s_./-]+/g, "");
  const matchesTableName = (table: AnalysisDataTableSelection, query: string) => {
    const normalizedQuery = normalizeTableName(query);
    return !normalizedQuery || normalizeTableName(table.name).includes(normalizedQuery);
  };
  const filteredRows = rows.filter((table) => matchesTableName(table, appliedSearch));
  const suggestions = searchText.trim() ? rows.filter((table) => matchesTableName(table, searchText)).slice(0, 8) : [];
  const applySearch = (query = searchText) => {
    setSearchText(query);
    setAppliedSearch(query);
    setSuggestionsOpen(false);
  };
  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[820px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">选择数据表</h3>
            <p className="mt-1 text-[11px] text-[#8a8a8e]">与站内数据同源，选中后会将对应 SQL 和字段信息注入智能分析上下文。</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7]"><X className="h-4 w-4" /></button>
        </div>
        <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-3">
          <div className="inline-flex rounded-lg bg-[#f2f2f7] p-1">
            {[{ key: "raw", label: `原始表 ${rawTables.length}` }, { key: "topic", label: `主题表 ${topicTables.length}` }].map((tab) => (
              <button key={tab.key} type="button" onClick={() => { setActiveTab(tab.key as "raw" | "topic"); setSuggestionsOpen(false); }} className={`rounded-md px-3 py-1.5 text-[12px] transition-colors ${activeTab === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"}`}>{tab.label}</button>
            ))}
          </div>
          <div className="relative flex items-center">
            {searchOpen && (
              <input autoFocus value={searchText} onChange={(event) => { setSearchText(event.target.value); setSuggestionsOpen(true); }} onFocus={() => setSuggestionsOpen(true)} onKeyDown={(event) => { if (event.key === "Enter") applySearch(); if (event.key === "Escape") setSuggestionsOpen(false); }} placeholder="按表名称搜索" aria-label="按表名称搜索" data-table-picker-search="true" className="h-7 w-40 border-b border-[#d1d1d6] bg-transparent px-1.5 text-[12px] text-[#1d1d1f] outline-none placeholder:text-[#aeaeb2] focus:border-[#636366]" />
            )}
            <button type="button" onClick={() => searchOpen ? applySearch() : setSearchOpen(true)} aria-label={searchOpen ? "查询数据表" : "打开数据表搜索"} title={searchOpen ? "查询" : "搜索数据表"} className="ml-1 rounded-md p-1.5 text-[#636366] transition-colors hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"><Search className="h-4 w-4" /></button>
            {suggestionsOpen && suggestions.length > 0 && (
              <div className="absolute right-0 top-full z-10 mt-1 w-max max-w-[10cm] overflow-hidden rounded-lg border border-[#e5e5ea] bg-white py-1 shadow-lg shadow-black/10">
                {suggestions.map((table) => <button key={table.id} type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applySearch(table.name)} className="block max-w-full whitespace-nowrap truncate px-3 py-1.5 text-left text-[12px] text-[#3a3a3c] hover:bg-[#f2f2f7]" title={table.name}>{table.name}</button>)}
              </div>
            )}
          </div>
        </div>
        <div className="max-h-[460px] overflow-y-auto p-5">
          <div className="overflow-hidden rounded-lg border border-[#f0f0f2]">
            <div className="grid grid-cols-[1.1fr_0.8fr_1.7fr_70px] gap-3 bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]"><span>表名称</span><span>编码</span><span>描述</span><span className="text-right">选择</span></div>
            {filteredRows.map((table) => (
              <label key={table.id} className="grid cursor-pointer grid-cols-[1.1fr_0.8fr_1.7fr_70px] items-center gap-3 border-t border-[#f8f8f8] px-3 py-2.5 hover:bg-[#fafbfc]">
                <span className="text-[12px] text-[#1d1d1f]">{table.name}</span><span className="truncate font-mono text-[11px] text-[#8a8a8e]">{table.code}</span><span className="truncate text-[11px] text-[#636366]">{table.description}</span>
                <span className="flex justify-end"><input type="radio" name="analysis-data-table" checked={selectedId === table.id} onChange={() => selectTable(table)} aria-label={`选择数据表${table.name}`} className="h-4 w-4 accent-[#1d1d1f]" /></span>
              </label>
            ))}
            {!rows.length && <div className="px-3 py-8 text-center text-[12px] text-[#aeaeb2]">暂无可选数据表</div>}
            {!!rows.length && !filteredRows.length && <div className="px-3 py-8 text-center text-[12px] text-[#aeaeb2]">未找到匹配的表名称</div>}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-[#f0f0f2] px-5 py-3"><span className="text-[11px] text-[#8a8a8e]">{selectedId ? "已选择 1 张表" : "一次分析仅使用 1 张数据表"}</span><button type="button" onClick={onClose} className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e]">完成</button></div>
      </div>
    </div>
  );
}
