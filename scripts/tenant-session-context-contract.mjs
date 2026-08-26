import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(
  new URL("../src/app/platform/PlatformContext.tsx", import.meta.url),
  "utf8",
);
const authSource = await readFile(new URL("../src/app/services/authApi.ts", import.meta.url), "utf8");
const layoutSource = await readFile(new URL("../src/app/components/Layout.tsx", import.meta.url), "utf8");
const settingsSource = await readFile(new URL("../src/app/components/SystemSettings.tsx", import.meta.url), "utf8");
const dataAssetsSource = await readFile(new URL("../src/app/components/DataAssets.tsx", import.meta.url), "utf8");

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
  /const targetTenantId = resolveTenantIdForInstitution\(target, authSession, tenantIdByInstitution\)/,
  "切换显示名时必须先从目录解析权威租户 ID",
);
assert.match(
  source,
  /const current = await switchTenantSession\(targetTenantId\)/,
  "机构切换必须通过服务端重签有状态会话，不能只改本地缓存",
);
assert.match(
  authSource,
  /apiRequest<AuthSession>\("\/api\/auth\/switch-tenant",[\s\S]*?tenant_id: tenantId/,
  "认证客户端必须调用权威租户切换接口",
);
assert.doesNotMatch(
  source,
  /const nextSession: AuthSession = \{[\s\S]{0,500}tenant_id:/,
  "前端不得自行合成切换后的认证会话",
);
assert.match(
  layoutSource,
  /const switched = await setSelectedInstitution\(institution\)/,
  "租户选择器必须等待服务端切换结果后再提交页面动作",
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
assert.match(
  settingsSource,
  /systemDataParams\.find\(\(param\) => param\.id === paramId && \(param\.tenantId \|\| tenantId\) === tenantId\)\?\.value[\s\S]*?configReadStatus/,
  "系统运行参数必须按当前租户读取，加载失败不得回退其他租户的参数",
);
assert.match(
  settingsSource,
  /showSystemConfigSummary = canReadSystemParams \|\| \(isSuperAdmin && configReadStatus !== "ready"\)/,
  "超级管理员加载失败时必须保留系统配置模块并显示错误状态",
);
assert.match(
  dataAssetsSource,
  /尚未配置指标，请由管理员新增或批量导入/,
  "新租户的空指标字典必须显示正式空状态",
);

console.log("tenant session context contract passed");
