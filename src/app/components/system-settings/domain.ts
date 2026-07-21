import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import {
  Settings,
  Activity,
  Users,
  Shield,
  Key,
  Database,
  Bell,
  Palette,
  ChevronRight,
  Plus,
  Edit3,
  Trash2,
  CheckCircle2,
  Clock,
  Search,
  Eye,
  EyeOff,
  ToggleRight,
  ToggleLeft,
  X,
  type LucideIcon,
} from "lucide-react";
import { operatingTenantNames } from "../../data/operatingTenants";
import { usePlatformContext } from "../../platform/PlatformContext";
import {
  deleteAccessUser,
  fetchAccessRolePolicies,
  fetchAccessUsers,
  saveAccessUser,
  saveAccessRolePolicy,
  type AccessTenantRole,
  type AccessRoleConfig,
  type AccessRolePermission,
  type AccessUser,
} from "../../services/accessControlApi";
import { fetchAuditLogs, type AuditLog } from "../../services/auditApi";
import {
  deleteDataConnection,
  deleteModelIntegration,
  deleteSpeechIntegration,
  fetchSystemConfig,
  saveDataConnection,
  saveModelIntegration,
  saveSpeechIntegration,
  saveSystemDataParam,
  testDataConnection,
  testModelIntegration,
  testSpeechIntegration,
  type DataConnection,
  type DataConnectionTestResult,
  type ModelIntegration,
  type ModelIntegrationTestResult,
  type SpeechIntegration,
  type SpeechIntegrationTestResult,
  type SystemDataParam,
} from "../../services/systemConfigApi";
import { apiErrorMessage } from "../../services/apiClient";
import { demoFallbackDisabledMessage, isDemoFallbackEnabled } from "../../services/apiContext";

export const customRoleOptions = ["客户经理分析岗", "周报分析岗", "指标维护岗"];
export const userRoleOptions = ["管理员", "操作员", ...customRoleOptions];
export const modelSourceOptions = ["中转站", "官方网站"];
export const dataSourceTypeOptions = ["智运平台（页面爬虫）", "毓数平台（SQL爬虫）", "API/URL", "邮件日报", "驾驶舱", "小程序数据", "毓数QBI"];
export const emptyUserForm = {
  name: "",
  department: "",
  email: "",
  status: "active",
  tenantRoles: [{ tenant: operatingTenantNames[0], role: "操作员" }] as AccessTenantRole[],
};
export type UserFormKey = Exclude<keyof typeof emptyUserForm, "tenantRoles">;

export const roles = [
  {
    name: "超级管理员",
    users: 1,
    permissions: "所有机构 · 所有菜单 · 所有数据",
    desc: "全局唯一最高权限，不挂在任何单个机构下，可管理全部机构、角色、菜单、数据、模型、MCP 和 Skill。",
  },
  {
    name: "机构管理员",
    users: 12,
    permissions: "授权机构 · 全菜单 · 全数据",
    desc: "可查看授权机构下所有菜单和数据，并可在本机构范围内给机构操作员授权。",
  },
  {
    name: "机构操作员",
    users: 86,
    permissions: "按分配菜单和数据访问",
    desc: "只能看到全局覆盖授权或机构管理员分配给他的菜单和数据；当两类授权冲突时，以全局覆盖授权为准。",
  },
];

export const permissionMenuGroups = [
  { label: "多机构分析", children: ["多机构分析"] },
  { label: "经营分析", children: ["经营周报", "机构督导"] },
  { label: "市场洞察", children: ["客群分析", "竞品分析"] },
  { label: "自助分析", children: ["智能分析", "我的报告"] },
  { label: "任务工作台", children: ["能力总览", "待办任务", "自动化任务", "Skill插件"] },
  { label: "数据资产", children: ["指标字典", "知识记忆", "数据管理", "质量监控"] },
  { label: "推送与订阅", children: ["预警规则", "订阅管理", "推送记录"] },
  { label: "系统管理", children: ["用户管理", "角色权限", "审计日志", "系统配置"] },
];

export const permissionMenus = permissionMenuGroups.flatMap((group) => group.children);

export const permissionDataScopes = [
  "经营指标汇总",
  "机构周报数据",
  "业务漏斗数据",
  "客户画像数据",
  "指标字典",
  "知识记忆",
  "用户行为习惯",
  "质量监控",
  "系统配置数据",
];

export const superAdminManagementScopes = [
  "机构管理",
  "用户管理",
  "角色授权",
  "菜单权限",
  "指标与数据权限",
  "模型接入",
  "数据接入",
  "Skill配置",
  "MCP管理",
  "审计与风控",
];

export const allPermissionMenus = permissionMenus;
export const allPermissionDataScopes = permissionDataScopes;

export const fallbackAuditLogs = [
  { time: "09:32", user: "胥京波", action: "导出报表", target: "月度经营分析报告", ip: "10.12.*.* " },
  { time: "09:15", user: "胥京波", action: "登录系统", target: "—", ip: "10.12.*.* " },
  { time: "08:42", user: "李娜", action: "创建分析任务", target: "M1逾期率归因分析", ip: "10.15.*.* " },
  { time: "08:30", user: "赵敏", action: "修改预警规则", target: "动支率持续下降", ip: "10.18.*.* " },
  { time: "昨日 17:30", user: "王强", action: "查看机构数据", target: "华东分行穿透报表", ip: "10.20.*.* " },
];

export const systemConfig = [
  { id: "data_refresh_frequency", name: "数据刷新频率", value: "T+1（每日凌晨02:00）", category: "data", description: "经营主题数据同步节奏" },
  { id: "session_timeout", name: "会话超时时间", value: "30分钟", category: "security", description: "前端会话和后端 token 默认有效期" },
  { id: "password_policy", name: "密码复杂度", value: "强（需包含大小写+数字+特殊字符）", category: "security", description: "本地开发保留参数，生产接统一身份源" },
  { id: "ai_concurrency_limit", name: "AI分析并发上限", value: "10个/用户", category: "system", description: "单用户同时运行智能分析任务数量" },
  { id: "report_retention_days", name: "报告保留期限", value: "365天", category: "data", description: "周报、双周报和分析快照保留周期" },
  { id: "audit_retention_days", name: "操作日志保留", value: "180天", category: "security", description: "审计事件可查询窗口" },
];

export type SettingsSection = "users" | "roles" | "audit" | "config";
export type AccessModal = "model" | "data" | null;
export type PermissionRole = string;
export type SystemUser = AccessUser;

export type InstitutionPermission = AccessRolePermission;

export const initialModelIntegrations: ModelIntegration[] = [
  {
    id: "model_business_analysis_relay",
    name: "经营分析大模型",
    modelName: "中转站",
    key: "https://zetatechs.com/api/v1/business-analysis",
    value: "zetatechs-demo-key",
    applicationModule: "intelligent_analysis_reasoning",
    availableModels: ["qwen-plus", "deepseek-v3", "gpt-4o-mini"],
    enabledModels: ["qwen-plus"],
    testStatus: "untested",
    status: "available",
  },
  {
    id: "model_sql_generation_relay",
    name: "SQL生成模型",
    modelName: "中转站",
    key: "https://zetatechs.com/api/v1/sql-agent",
    value: "zetatechs-demo-key",
    applicationModule: "weekly_report_conclusion_regeneration",
    availableModels: ["qwen-plus", "deepseek-v3", "gpt-4o-mini"],
    enabledModels: ["qwen-plus"],
    testStatus: "untested",
    status: "available",
  },
];

export const initialSpeechIntegrations: SpeechIntegration[] = [
  {
    id: "speech_fun_asr",
    name: "阿里云 Fun-ASR",
    provider: "aliyun_fun_asr",
    source: "阿里云",
    apiBase: "https://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api/v1",
    apiKey: "dashscope-demo-key",
    applicationModule: "realtime_voice_input",
    testStatus: "untested",
    status: "available",
  },
];

export const initialDataConnections: DataConnection[] = [
  {
    id: "data_1",
    institution: "华兴银行",
    sourceName: "华兴毓数QBI经营数据",
    sourceType: "毓数平台（SQL爬虫）",
    apiUrl: "https://qbi.example.local/api",
    loginUrl: "https://qbi.example.local/login",
    queryPageUrl: "https://qbi.example.local/sql-editor",
    metadataPageUrl: "https://qbi.example.local/metadata",
    crawlerMode: "sql",
    account: "huaxing_ops",
    password: "******",
    token: "",
    dataset: "loan_operation_mart",
    defaultDatabase: "loan_operation_mart",
    enabled: true,
    mockEnabled: false,
    status: "connected",
  },
  {
    id: "data_2",
    institution: "广州银行",
    sourceName: "广州毓数QBI渠道数据",
    sourceType: "毓数平台（SQL爬虫）",
    apiUrl: "https://qbi.example.local/api",
    loginUrl: "https://qbi.example.local/login",
    queryPageUrl: "https://qbi.example.local/sql-editor",
    metadataPageUrl: "https://qbi.example.local/metadata",
    crawlerMode: "sql",
    account: "guangzhou_ops",
    password: "******",
    token: "",
    dataset: "channel_operation_mart",
    defaultDatabase: "channel_operation_mart",
    enabled: true,
    mockEnabled: false,
    status: "connected",
  },
];

export const initialUserList: SystemUser[] = [
  {
    id: "u_super_admin",
    name: "胥京波",
    department: "平台管理中心",
    status: "active",
    lastLogin: "今日 09:15",
    email: "xujingbo-jk@qifu.com",
    tenantRoles: [{ tenant: "全部机构", role: "超级管理员" }],
  },
  {
    id: "u_lina",
    name: "李娜",
    department: "华兴银行",
    status: "active",
    lastLogin: "今日 08:42",
    email: "lina@bank.com",
    tenantRoles: [{ tenant: "华兴银行", role: "管理员" }],
  },
  {
    id: "u_wangqiang",
    name: "王强",
    department: "广州银行",
    status: "active",
    lastLogin: "昨日 17:30",
    email: "wangqiang@bank.com",
    tenantRoles: [{ tenant: "广州银行", role: "管理员" }],
  },
  {
    id: "u_zhaomin",
    name: "赵敏",
    department: "郑州银行",
    status: "active",
    lastLogin: "昨日 15:20",
    email: "zhaomin@bank.com",
    tenantRoles: [{ tenant: "郑州银行", role: "操作员" }],
  },
  {
    id: "u_liuyang",
    name: "刘洋",
    department: "南京银行",
    status: "inactive",
    lastLogin: "1周前",
    email: "liuyang@bank.com",
    tenantRoles: [{ tenant: "南京银行", role: "操作员" }],
  },
  {
    id: "u_chenlei",
    name: "陈磊",
    department: "三峡银行",
    status: "active",
    lastLogin: "今日 09:30",
    email: "chenlei@bank.com",
    tenantRoles: [{ tenant: "三峡银行", role: "周报分析岗" }],
  },
];

export const initialPermissionInstitutions: InstitutionPermission[] = operatingTenantNames.map((tenant, index) => {
  return {
    id: `tenant_${index + 1}`,
    institution: tenant,
    adminMenus: allPermissionMenus,
    adminDataScopes: allPermissionDataScopes,
    operatorSuperMenus: [],
    operatorSuperDataScopes: [],
    operatorAdminMenus: ["多机构分析", "经营周报", "客群分析", "自助分析"],
    operatorAdminDataScopes: ["经营指标汇总", "机构周报数据", "业务漏斗数据", "客户画像数据"],
    manageableRoles: ["操作员", "客户经理分析岗", "周报分析岗"],
    customRoles: customRoleOptions,
    updatedBy: index % 2 === 0 ? "胥京波" : "机构管理员",
    updatedAt: index % 2 === 0 ? "今天 09:20" : "昨日 17:30",
  };
});

export const emptyModelForm = { name: "", modelName: "中转站", applicationModule: "", key: "", value: "" };
export const emptySpeechForm = {
  name: "阿里云 Fun-ASR",
  provider: "aliyun_fun_asr",
  source: "阿里云",
  apiBase: "https://ws-nvbkaw0atdgdbvv7.cn-beijing.maas.aliyuncs.com/api/v1",
  apiKey: "",
  applicationModule: "realtime_voice_input",
};

export function maskApiSecret(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (trimmed === "******") return trimmed;
  if (trimmed.length <= 8) return "******";
  return `${trimmed.slice(0, 4)}${"•".repeat(6)}${trimmed.slice(-4)}`;
}

export function speechProviderLabel(provider: string) {
  if (provider === "aliyun_fun_asr") return "阿里云 Fun-ASR";
  return provider || "未配置";
}

export function modelSourceLabel(source: string) {
  return modelSourceOptions.includes(source) ? source : modelSourceOptions[0];
}

export const dataConnectionDatasetByType: Record<string, string> = {
  毓数QBI: "loan_operation_mart",
  "毓数平台（SQL爬虫）": "yushu_crawler_mart",
  "智运平台（页面爬虫）": "channel_operation_mart",
  "API/URL": "external_api_mart",
  智运平台: "channel_operation_mart",
  邮件日报: "weekly_mail_report_mart",
  驾驶舱: "management_dashboard_mart",
  小程序数据: "mini_program_operation_mart",
};

export function defaultDatasetForDataConnection(sourceType: string, sourceName: string, institution: string) {
  const mappedDataset = dataConnectionDatasetByType[sourceType];
  if (mappedDataset) return mappedDataset;
  const fallback = `${institution}_${sourceName || sourceType || "data_source"}`
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^\w\u4e00-\u9fa5]/g, "_")
    .replace(/_+/g, "_");
  return fallback || "mock_generated_dataset";
}

export const defaultRelayModelOptions = ["deepseek-v4-flash", "gpt-5.3-codex-spark", "qwen-plus", "glm-5", "deepseek-r1"];

export const modelOptionDescriptions: Record<string, string> = {
  "deepseek-v4-flash": "适合经营分析、归因判断和长文本总结，响应速度较快。",
  "deepseek-v4-pro": "适合复杂推理、策略分析和多步骤经营诊断。",
  "gpt-5.3-codex-spark": "适合代码、SQL、脚本和结构化分析任务。",
  "codex-auto-review": "适合自动检查、结果复核和分析过程校验。",
  "qwen-plus": "适合中文业务分析、周报总结和通用问答。",
  "qwen-max": "适合复杂中文推理和高质量报告生成。",
  "glm-5": "适合中文场景理解、摘要和经营分析补充判断。",
  "glm-5.1": "适合中文文本生成和多轮分析对话。",
  "glm-5.2": "适合更强的中文推理和长上下文总结。",
  "deepseek-r1": "适合强推理、归因拆解和复杂问题链路分析。",
};

export function modelOptionDescription(modelName: string) {
  return modelOptionDescriptions[modelName] || "由中转站返回的可调用模型，可用于智能分析、SQL生成和报告总结。";
}

export function defaultModelOptionsForSource(source: string, modelName: string) {
  if (modelSourceLabel(source) === "中转站") return defaultRelayModelOptions;
  const directModel = modelName.trim();
  return directModel ? [directModel] : [];
}

export function availableModelOptions(model: ModelIntegration) {
  const options = model.availableModels?.length
    ? model.availableModels
    : defaultModelOptionsForSource(model.modelName, model.name);
  return Array.from(new Set([...(model.enabledModels || []), ...options])).filter(Boolean);
}

export const speechCapabilityDescriptions: Record<string, { title: string; model: string; description: string }[]> = {
  aliyun_fun_asr: [
    {
      title: "实时语音识别",
      model: "fun-asr-realtime",
      description: "通过 WebSocket 接收麦克风音频流，实时返回中文语音转文字结果。",
    },
    {
      title: "上下文增强转写",
      model: "fun-asr-context",
      description: "结合当前智能分析上下文和术语提示，提升业务词、指标名和机构名识别稳定性。",
    },
  ],
};

export function speechCapabilityOptions(integration: SpeechIntegration) {
  return speechCapabilityDescriptions[integration.provider] || [
    {
      title: speechProviderLabel(integration.provider),
      model: integration.provider,
      description: "语音转文字平台能力，测试通过后可被智能分析实时语音入口调用。",
    },
  ];
}

export const initialSystemDataParams: SystemDataParam[] = systemConfig;
export const emptyDataForm = {
  institution: "",
  sourceName: "",
  sourceType: "智运平台（页面爬虫）",
  apiUrl: "",
  loginUrl: "",
  queryPageUrl: "",
  metadataPageUrl: "",
  spaceId: "",
  account: "",
  password: "",
  token: "",
  dataset: "",
  defaultDatabase: "",
  enabled: true,
  mockEnabled: false,
};

export function getSettingsSection(pathname: string): SettingsSection {
  if (pathname.endsWith("/roles")) return "roles";
  if (pathname.endsWith("/audit")) return "audit";
  if (pathname.endsWith("/config")) return "config";
  return "users";
}

export function formatAuditLog(log: AuditLog) {
  return {
    time: formatAuditTime(log.created_at),
    user: log.actor_user_id,
    action: auditActionLabels[log.action] || log.action,
    target: log.target_id || log.target_type,
    ip: log.ip_address || "—",
  };
}

export function formatAuditTime(value: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

export const auditActionLabels: Record<string, string> = {
  "access.user.upsert": "保存用户",
  "access.user.delete": "删除用户",
  "access.role_policy.save": "保存角色权限",
  "system.model.upsert": "保存模型接入",
  "system.model.delete": "删除模型接入",
  "system.model.test": "测试模型接入",
  "system.speech.upsert": "保存语音转文字接入",
  "system.speech.test": "测试语音转文字接入",
  "system.speech.delete": "删除语音转文字接入",
  "system.data_connection.upsert": "保存数据接入",
  "system.data_connection.test": "测试数据接入",
  "system.data_connection.delete": "删除数据接入",
  "system.param.upsert": "保存系统数据参数",
  "data_asset.item.upsert": "保存数据资产",
  "data_asset.item.delete": "删除数据资产",
  "metric.dictionary.replace": "初始化指标字典",
  "metric.dictionary.upsert": "保存指标",
  "metric.dictionary.delete": "删除指标",
};
