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

export function catalogTenantId(value: string) {
  const normalized = String(value || "").trim();
  if (!normalized) return "";
  return normalized.startsWith("tenant:") || normalized === "tenant_demo" ? normalized : `tenant:${normalized}`;
}

function localSourceKeys(entries: Array<{ tenantId?: string; sourceKey?: string }>, tenantId: string) {
  const current = catalogTenantId(tenantId);
  return entries.flatMap((entry) => {
    const sourceKey = String(entry.sourceKey || "").trim();
    if (!sourceKey) return [];
    const owner = catalogTenantId(String(entry.tenantId || ""));
    if (owner && owner !== current) return [];
    return [sourceKey];
  });
}

export function pageDataAvailableForRawCatalog(item: PageDataAsset, tenantId: string, sourceKeys: Set<string>) {
  if (!sourceKeys.size) return false;
  if (pageDataScope(item) === "multi_institution") {
    const sources = item.institutionSources || [];
    const tenants = new Set(sources.map((source) => catalogTenantId(String(source.tenantId || ""))).filter(Boolean));
    const localKeys = localSourceKeys(sources, tenantId);
    return tenants.size >= 2 && localKeys.length > 0 && localKeys.every((key) => sourceKeys.has(key));
  }
  const sourceKey = String(item.sourceKey || "").trim();
  return Boolean(sourceKey) && sourceKeys.has(sourceKey);
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
