export const operatingTenantNames = [
  "华兴银行",
  "广州银行",
  "兰州银行",
  "汉口银行",
  "石嘴山银行",
  "郑州银行",
  "临商银行",
  "瑞丰银行",
  "南京银行",
  "兴业消金",
  "三峡银行",
];

export type OperatingTenantName = (typeof operatingTenantNames)[number];

export const demoInstitutionName = "演示机构";

export function institutionNameFromTenant(value: string) {
  const normalized = value.trim();
  if (!normalized) return "";
  if (normalized === "tenant_demo") return demoInstitutionName;
  if (normalized.startsWith("tenant:")) return normalized.slice("tenant:".length).trim();
  return normalized;
}

export function tenantIdFromInstitution(institution: string) {
  const normalized = institution.trim();
  if (!normalized) return "tenant_demo";
  if (normalized === demoInstitutionName) return "tenant_demo";
  if (normalized.startsWith("tenant:") || normalized === "tenant_demo") return normalized;
  return `tenant:${normalized}`;
}
