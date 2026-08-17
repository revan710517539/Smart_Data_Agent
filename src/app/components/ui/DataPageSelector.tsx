import { useEffect, useState } from "react";

type DataPageSelectorProps = {
  page: number;
  totalPages: number;
  shownCount: number;
  totalCount?: number;
  onChange: (page: number) => void;
  ariaLabel?: string;
  compact?: boolean;
  className?: string;
};

export function DataPageSelector({
  page,
  totalPages,
  shownCount,
  totalCount = shownCount,
  onChange,
  ariaLabel = "数据分页",
  compact = false,
  className = "",
}: DataPageSelectorProps) {
  const safePageCount = Math.max(1, totalPages);
  const safePage = Math.max(1, Math.min(page, safePageCount));
  return (
    <div className={`flex shrink-0 items-center gap-2 text-[11px] text-[#8a8a8e] ${className}`}>
      <select
        value={safePage}
        onChange={(event) => onChange(Number(event.target.value))}
        className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2.5 text-[11px] text-[#636366] outline-none hover:bg-[#f8f8f8] focus:border-[#7db797]"
        aria-label={ariaLabel}
      >
        {Array.from({ length: safePageCount }, (_, index) => (
          <option key={index + 1} value={index + 1}>
            第 {index + 1} 页 / 共 {safePageCount} 页
          </option>
        ))}
      </select>
      <span className={compact ? "hidden xl:inline" : ""}>{shownCount} / {totalCount} 条</span>
    </div>
  );
}

export function useClientPagination<T>(items: T[], pageSize = 20) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  useEffect(() => setPage((current) => Math.min(current, totalPages)), [totalPages]);
  return {
    page,
    setPage,
    totalPages,
    total: items.length,
    items: items.slice((page - 1) * pageSize, page * pageSize),
    paginated: items.length > pageSize,
  };
}
