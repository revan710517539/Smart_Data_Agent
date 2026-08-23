export type TableSortState = { field: string; direction: "asc" | "desc" } | null;

export function nextTableSortState(current: TableSortState, field: string): TableSortState {
  if (!current || current.field !== field) return { field, direction: "asc" };
  if (current.direction === "asc") return { field, direction: "desc" };
  return null;
}

export function sortTableRows<T extends { raw: Record<string, unknown> }>(rows: T[], state: TableSortState): T[] {
  if (!state) return rows;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const leftValue = left.row.raw[state.field];
      const rightValue = right.row.raw[state.field];
      const leftEmpty = leftValue === null || leftValue === undefined || leftValue === "";
      const rightEmpty = rightValue === null || rightValue === undefined || rightValue === "";
      if (leftEmpty || rightEmpty) return leftEmpty === rightEmpty ? left.index - right.index : leftEmpty ? 1 : -1;
      const compared = compareTableValues(leftValue, rightValue);
      if (!compared) return left.index - right.index;
      return state.direction === "asc" ? compared : -compared;
    })
    .map(({ row }) => row);
}

export function compareTableValues(left: unknown, right: unknown) {
  const leftEmpty = left === null || left === undefined || left === "";
  const rightEmpty = right === null || right === undefined || right === "";
  if (leftEmpty || rightEmpty) return leftEmpty === rightEmpty ? 0 : leftEmpty ? 1 : -1;
  const leftNumber = sortableNumber(left);
  const rightNumber = sortableNumber(right);
  if (leftNumber !== null && rightNumber !== null) return leftNumber - rightNumber;
  return String(left).localeCompare(String(right), "zh-CN", { numeric: true, sensitivity: "base" });
}

function sortableNumber(value: unknown) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value).trim();
  if (!text || !/^[+-]?[\d,.]+%?$/.test(text)) return null;
  const parsed = Number(text.replace(/,/g, "").replace(/%$/, ""));
  return Number.isFinite(parsed) ? parsed : null;
}
