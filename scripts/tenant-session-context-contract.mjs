import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(
  new URL("../src/app/platform/PlatformContext.tsx", import.meta.url),
  "utf8",
);

assert.match(
  source,
  /setTenantIdByInstitution\(buildTenantIdCatalog\(response\.tenants\)\)/,
  "租户目录必须同时保留后端权威 ID 与显示名",
);
assert.match(
  source,
  /tenant_id: resolveTenantIdForInstitution\(target, authSession, tenantIdByInstitution\)/,
  "切换显示名时必须从目录解析权威租户 ID",
);
assert.match(
  source,
  /tenantId: resolveTenantIdForInstitution\(selectedInstitution, authSession, tenantIdByInstitution\)/,
  "请求上下文不得从租户显示名猜测 ID",
);
assert.match(
  source,
  /normalized === sessionInstitution \|\| normalized === sessionTenantLabel/,
  "登录与恢复必须保留后端签发会话的租户 ID",
);
assert.doesNotMatch(
  source,
  /tenantId: tenantIdFromInstitution\(selectedInstitution\)/,
  "页面上下文不得直接把显示名拼成租户 ID",
);

console.log("tenant session context contract passed");
