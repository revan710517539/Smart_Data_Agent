import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(
  new URL("../src/app/platform/PlatformContext.tsx", import.meta.url),
  "utf8",
);

assert.match(
  source,
  /setTenantIdByInstitution\(buildTenantIdCatalog\((?:response\.tenants|tenants)\)\)/,
  "租户目录必须同时保留后端权威 ID 与显示名",
);
assert.match(
  source,
  /refreshTenantCatalog/,
  "租户目录变更后必须能主动刷新权威机构列表",
);
assert.match(
  source,
  /tenantCatalogStatus === "ready" \|\| !authorizedInstitutions\.length[\s\S]*?\? tenantCatalog[\s\S]*?: authorizedInstitutions/,
  "已认证全局会话必须等待权威目录成功加载，加载中或失败时保留签发机构",
);
assert.match(
  source,
  /setTenantCatalogStatus\("unavailable"\)/,
  "租户目录失败必须显式关闭，不能回退静态目录并改写认证上下文",
);
assert.doesNotMatch(
  source,
  /catch \{[\s\S]{0,120}setTenantCatalog\(operatingTenantNames\)/,
  "租户目录失败不得把已认证会话切到静态演示机构",
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
