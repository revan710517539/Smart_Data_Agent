import type { PageDataAsset, PageDataInstitutionScope, PageDataPageCode } from "../../services/dataAssetApi";

export function pageDataScope(asset: PageDataAsset): PageDataInstitutionScope {
  if (asset.institutionScope) return asset.institutionScope;
  if (asset.targetPages.length === 1 && asset.targetPages[0] === "customer_segment_analysis") return "customer_segment";
  return asset.targetPages.length === 1 && asset.targetPages[0] === "dashboard" ? "multi_institution" : "single_institution";
}

export function singleInstitutionAssignedPage(
  asset?: Pick<PageDataAsset, "targetPages"> | null,
): Extract<PageDataPageCode, "weekly_report" | "institution_supervision"> {
  return asset?.targetPages.includes("institution_supervision") ? "institution_supervision" : "weekly_report";
}

export function pageDataBelongsToPage(asset: PageDataAsset, pageCode: PageDataPageCode): boolean {
  const scope = pageDataScope(asset);
  if (pageCode === "dashboard") {
    return scope === "multi_institution" && asset.targetPages.includes("dashboard");
  }
  if (pageCode === "customer_segment_analysis") {
    return scope === "customer_segment" && asset.targetPages.includes("customer_segment_analysis");
  }
  if (pageCode !== "weekly_report" && pageCode !== "institution_supervision") {
    return false;
  }
  return scope === "single_institution" && singleInstitutionAssignedPage(asset) === pageCode;
}

export function resolvePageDataLayout(
  savedLayout: string[],
  availableIds: string[],
  options: { includeNewlyAssigned?: boolean } = {},
): string[] {
  const available = new Set(availableIds);
  const kept = savedLayout.filter((id) => available.has(id));
  const extras = availableIds.filter((id) => !kept.includes(id));
  if (options.includeNewlyAssigned) return [...kept, ...extras];
  return kept.length ? kept : [...availableIds];
}
