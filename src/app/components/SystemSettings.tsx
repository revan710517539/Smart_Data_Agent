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
import { operatingTenantNames } from "../data/operatingTenants";
import { usePlatformContext } from "../platform/PlatformContext";
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
} from "../services/accessControlApi";
import { fetchAuditLogs, type AuditLog } from "../services/auditApi";
import {
  deleteModelIntegration,
  deleteSpeechIntegration,
  fetchSystemConfig,
  saveModelIntegration,
  saveSpeechIntegration,
  saveSystemDataParam,
  testModelIntegration,
  testSpeechIntegration,
  type ModelIntegration,
  type ModelIntegrationTestResult,
  type SpeechIntegration,
  type SpeechIntegrationTestResult,
  type SystemDataParam,
} from "../services/systemConfigApi";
import { ApiRequestError, apiErrorMessage } from "../services/apiClient";
import { demoFallbackDisabledMessage, isDemoFallbackEnabled } from "../services/apiContext";
import { modelApplicationModuleLabel, modelApplicationModuleOptions } from "../data/modelApplicationModules";
import {
  type UserFormKey,
  type SettingsSection,
  type AccessModal,
  type PermissionRole,
  type SystemUser,
  type InstitutionPermission,
  customRoleOptions,
  userRoleOptions,
  modelSourceOptions,
  emptyUserForm,
  roles,
  permissionMenuGroups,
  permissionMenus,
  permissionDataScopes,
  superAdminManagementScopes,
  allPermissionMenus,
  allPermissionDataScopes,
  fallbackAuditLogs,
  systemConfig,
  initialModelIntegrations,
  initialSpeechIntegrations,
  initialUserList,
  initialPermissionInstitutions,
  emptyModelForm,
  emptySpeechForm,
  maskApiSecret,
  speechProviderLabel,
  modelSourceLabel,
  defaultRelayModelOptions,
  modelOptionDescriptions,
  modelOptionDescription,
  defaultModelOptionsForSource,
  availableModelOptions,
  speechCapabilityDescriptions,
  speechCapabilityOptions,
  initialSystemDataParams,
  getSettingsSection,
  formatAuditLog,
  formatAuditTime,
  auditActionLabels,
} from "./system-settings/domain";

function normalizedModelName(value: string) {
  return value.trim().toLocaleLowerCase().replace(/\s+/g, " ");
}

function hasDuplicateModelName(models: ModelIntegration[], name: string, currentModelId = "") {
  const target = normalizedModelName(name);
  if (!target) return false;
  return models.some((model) => model.id !== currentModelId && normalizedModelName(model.name) === target);
}

export function SystemSettings() {
  const location = useLocation();
  const {
    institutions: visibleInstitutions,
    isSuperAdmin,
    selectedInstitution,
    tenantId,
    userId,
  } = usePlatformContext();
  const activeTab = getSettingsSection(location.pathname);
  const [searchTerm, setSearchTerm] = useState("");
  const [accessModal, setAccessModal] = useState<AccessModal>(null);
  const [modelIntegrations, setModelIntegrations] = useState<ModelIntegration[]>(
    isDemoFallbackEnabled() ? initialModelIntegrations : [],
  );
  const [speechIntegrations, setSpeechIntegrations] = useState<SpeechIntegration[]>(
    isDemoFallbackEnabled() ? initialSpeechIntegrations : [],
  );
  const [systemDataParams, setSystemDataParams] = useState<SystemDataParam[]>(
    isDemoFallbackEnabled() ? initialSystemDataParams : [],
  );
  const [configNotice, setConfigNotice] = useState("");
  const [testingModelId, setTestingModelId] = useState("");
  const [testingSpeechIntegrationId, setTestingSpeechIntegrationId] = useState("");
  const [modelTestResults, setModelTestResults] = useState<Record<string, ModelIntegrationTestResult>>({});
  const [speechTestResults, setSpeechTestResults] = useState<Record<string, SpeechIntegrationTestResult>>({});
  const [modelForm, setModelForm] = useState(emptyModelForm);
  const [speechForm, setSpeechForm] = useState(emptySpeechForm);
  const [users, setUsers] = useState<SystemUser[]>(isDemoFallbackEnabled() ? initialUserList : []);
  const [accessNotice, setAccessNotice] = useState("");
  const [auditRows, setAuditRows] = useState<ReturnType<typeof formatAuditLog>[]>([]);
  const [auditNotice, setAuditNotice] = useState("");
  const [userEditorOpen, setUserEditorOpen] = useState(false);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [userForm, setUserForm] = useState(emptyUserForm);
  const [permissionInstitutions, setPermissionInstitutions] =
    useState<InstitutionPermission[]>(isDemoFallbackEnabled() ? initialPermissionInstitutions : []);
  const [editingPermissionId, setEditingPermissionId] = useState<string | null>(null);
  const [permissionRole, setPermissionRole] = useState<PermissionRole>("管理员");
  useEffect(() => {
    let cancelled = false;

    const syncSystemConfig = async () => {
      try {
        const response = await fetchSystemConfig({ tenantId, userId });
        if (cancelled) return;
        setModelIntegrations(response.models);
        setSpeechIntegrations(response.speech_integrations || []);
        setSystemDataParams(response.system_params);
        setConfigNotice(
          response.count.models || response.count.speech_integrations || response.count.system_params
            ? `系统接入配置已连接后端：${selectedInstitution}`
            : `系统接入配置已连接后端：${selectedInstitution}，当前暂无模型或语音配置。`,
        );
      } catch (error) {
        if (cancelled) return;
        if (isDemoFallbackEnabled()) {
          setModelIntegrations(initialModelIntegrations);
          setSpeechIntegrations(initialSpeechIntegrations);
          setSystemDataParams(initialSystemDataParams);
          setConfigNotice(`系统接入配置后端暂不可用，已使用显式 demo 本地状态。${apiErrorMessage(error, "")}`);
          return;
        }
        setModelIntegrations([]);
        setSpeechIntegrations([]);
        setSystemDataParams([]);
        setConfigNotice(`${demoFallbackDisabledMessage("系统接入配置加载")} ${apiErrorMessage(error, "")}`);
      }
    };

    void syncSystemConfig();
    return () => {
      cancelled = true;
    };
  }, [selectedInstitution, tenantId, userId]);

  useEffect(() => {
    let cancelled = false;

    const syncAccessUsers = async () => {
      try {
        const [userResponse, permissionResponse] = await Promise.all([
          fetchAccessUsers({ tenantId }),
          fetchAccessRolePolicies({ tenantId }),
        ]);
        if (cancelled) return;
        setUsers(userResponse.users);
        setPermissionInstitutions(permissionResponse.permissions);
        setAccessNotice(`用户与授权已连接后端：${selectedInstitution}`);
      } catch (error) {
        if (cancelled) return;
        if (isDemoFallbackEnabled()) {
          setUsers(initialUserList);
          setPermissionInstitutions(initialPermissionInstitutions);
          setAccessNotice(`用户与授权后端暂不可用，已使用显式 demo 本地状态。${apiErrorMessage(error, "")}`);
          return;
        }
        setUsers([]);
        setPermissionInstitutions([]);
        setAccessNotice(`${demoFallbackDisabledMessage("用户与授权加载")} ${apiErrorMessage(error, "")}`);
      }
    };

    void syncAccessUsers();
    return () => {
      cancelled = true;
    };
  }, [selectedInstitution, tenantId]);

  useEffect(() => {
    if (activeTab !== "audit") return;
    let cancelled = false;
    setAuditNotice("审计日志同步中...");

    const syncAuditLogs = async () => {
      try {
        const response = await fetchAuditLogs({ tenantId });
        if (cancelled) return;
        setAuditRows(response.logs.map(formatAuditLog));
        setAuditNotice(`审计日志已连接后端：${selectedInstitution} · ${response.count} 条`);
      } catch (error) {
        if (cancelled) return;
        if (isDemoFallbackEnabled()) {
          setAuditRows(fallbackAuditLogs);
          setAuditNotice(`审计后端暂不可用，已显示显式 demo 样例日志。${apiErrorMessage(error, "")}`);
          return;
        }
        setAuditRows([]);
        setAuditNotice(`${demoFallbackDisabledMessage("审计日志加载")} ${apiErrorMessage(error, "")}`);
      }
    };

    void syncAuditLogs();
    return () => {
      cancelled = true;
    };
  }, [activeTab, selectedInstitution, tenantId]);

  const addModelIntegration = async () => {
    const nextName = modelForm.name.trim();
    if (!nextName || !modelForm.modelName.trim() || !modelForm.applicationModule.trim() || !modelForm.key.trim() || !modelForm.value.trim()) return;
    if (hasDuplicateModelName(modelIntegrations, nextName)) {
      setConfigNotice("模型名称已存在，请使用不同的模型名称。");
      return;
    }
    const previousModels = modelIntegrations;
    const availableModels = defaultModelOptionsForSource(modelForm.modelName, modelForm.name);
    const nextModel: ModelIntegration = {
      id: `model_${Date.now()}`,
      name: nextName,
      modelName: modelForm.modelName.trim(),
      key: modelForm.key.trim(),
      value: modelForm.value.trim(),
      applicationModule: modelForm.applicationModule.trim(),
      availableModels,
      enabledModels: availableModels.slice(0, 1),
      status: "available",
    };
    setModelIntegrations((current) => [...current, nextModel]);
    setModelForm(emptyModelForm);
    try {
      const response = await saveModelIntegration({ tenantId, userId, model: nextModel });
      const latest = await fetchSystemConfig({ tenantId, userId, forceRefresh: true });
      setModelIntegrations(latest.models.length ? latest.models : [response.model]);
      setConfigNotice(nextModel.applicationModule === "memory_extraction" ? "模型接入已同步到后端；记忆模块仅保留当前这一条模型绑定。" : "模型接入已同步到后端。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`模型接入已保留在 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setModelIntegrations(previousModels);
      setConfigNotice(`${demoFallbackDisabledMessage("模型接入新增")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const removeModelIntegration = async (id: string) => {
    const previousModels = modelIntegrations;
    setModelIntegrations((current) => current.filter((item) => item.id !== id));
    try {
      await deleteModelIntegration({ tenantId, userId, modelId: id });
      setConfigNotice("模型接入已从后端删除。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`模型接入已从 demo 本地状态删除，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setModelIntegrations(previousModels);
      setConfigNotice(`${demoFallbackDisabledMessage("模型接入删除")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const updateModelIntegration = async (
    model: ModelIntegration,
    patch: Partial<Pick<ModelIntegration, "name" | "modelName" | "applicationModule" | "key" | "value" | "availableModels" | "enabledModels" | "lastTestedAt" | "testStatus" | "testMessage" | "testResponse" | "status">>,
  ) => {
    const previousModels = modelIntegrations;
    const patchValue = patch.value?.trim();
    const nextName = patch.name?.trim() || model.name;
    if (hasDuplicateModelName(modelIntegrations, nextName, model.id)) {
      setConfigNotice("模型名称已存在，请使用不同的模型名称。");
      throw new Error("模型名称已存在，请使用不同的模型名称。");
    }
    const nextSource = modelSourceLabel(patch.modelName || model.modelName);
    const availableModels =
      patch.availableModels ??
      (model.availableModels?.length ? model.availableModels : defaultModelOptionsForSource(nextSource, nextName));
    const rawEnabledModels = patch.enabledModels ?? model.enabledModels ?? [];
    const enabledModels =
      patch.enabledModels !== undefined
        ? rawEnabledModels.filter((modelName) => !availableModels.length || availableModels.includes(modelName))
        : rawEnabledModels.filter((modelName) => !availableModels.length || availableModels.includes(modelName)).length
          ? rawEnabledModels.filter((modelName) => !availableModels.length || availableModels.includes(modelName))
          : availableModels.slice(0, 1);
    const nextModel: ModelIntegration = {
      ...model,
      ...patch,
      name: nextName,
      modelName: nextSource,
      key: patch.key?.trim() || model.key,
      value: patchValue || model.value,
      availableModels,
      enabledModels,
    };
    if (!nextModel.key || !nextModel.value) return;
    setModelIntegrations((current) => current.map((item) => (item.id === model.id ? nextModel : item)));
    try {
      const response = await saveModelIntegration({ tenantId, userId, model: nextModel });
      const latest = await fetchSystemConfig({ tenantId, userId, forceRefresh: true });
      setModelIntegrations(latest.models.length ? latest.models : [response.model]);
      setConfigNotice(nextModel.applicationModule === "memory_extraction" ? "模型接入已更新；记忆模块仅保留当前这一条模型绑定。" : "模型接入已更新。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`模型接入已保留在 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setModelIntegrations(previousModels);
      setConfigNotice(`${demoFallbackDisabledMessage("模型接入修改")} ${apiErrorMessage(error, "未知错误")}`);
      throw error;
    }
  };

  const runModelIntegrationTest = async (model: ModelIntegration) => {
    setTestingModelId(model.id);
    setConfigNotice("正在测试模型接入...");
    try {
      const response = await testModelIntegration({ tenantId, userId, modelId: model.id });
      setModelTestResults((current) => ({ ...current, [model.id]: response.result }));
      if (response.model) {
        setModelIntegrations((current) => current.map((item) => (item.id === model.id ? response.model! : item)));
      }
      setConfigNotice(response.result.message);
    } catch (error) {
      const result: ModelIntegrationTestResult = {
        model_id: model.id,
        model_name: model.name,
        source: modelSourceLabel(model.modelName),
        callable: false,
        status: "failed",
        message: error instanceof ApiRequestError && error.code === "request_timeout" ? "模型测试请求超时，本次未改变已保存的模型列表和可用状态，请稍后重试。" : error instanceof Error ? error.message : "模型接入测试失败",
        available_models: [],
        response_preview: "",
        tested_at: new Date().toISOString(),
      };
      setModelTestResults((current) => ({ ...current, [model.id]: result }));
      setConfigNotice(`模型接入测试失败：${result.message}`);
    } finally {
      setTestingModelId("");
    }
  };

  const addSpeechIntegration = async () => {
    if (!speechForm.name.trim() || !speechForm.provider.trim() || !speechForm.applicationModule.trim() || !speechForm.apiBase.trim() || !speechForm.apiKey.trim()) return;
    const previousIntegrations = speechIntegrations;
    const nextIntegration: SpeechIntegration = {
      id: `speech_${Date.now()}`,
      name: speechForm.name.trim(),
      provider: speechForm.provider.trim(),
      source: speechForm.source.trim() || speechProviderLabel(speechForm.provider),
      apiBase: speechForm.apiBase.trim(),
      apiKey: speechForm.apiKey.trim(),
      applicationModule: speechForm.applicationModule,
      status: "available",
    };
    setSpeechIntegrations((current) => [...current, nextIntegration]);
    setSpeechForm(emptySpeechForm);
    try {
      const response = await saveSpeechIntegration({ tenantId, speechIntegration: nextIntegration });
      setSpeechIntegrations((current) => current.map((item) => (item.id === nextIntegration.id ? response.speech_integration : item)));
      setConfigNotice("语音转文字接入已同步到后端。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`语音转文字接入已保留在 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSpeechIntegrations(previousIntegrations);
      setConfigNotice(`${demoFallbackDisabledMessage("语音转文字接入新增")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const runSpeechIntegrationTest = async (integration: SpeechIntegration) => {
    setTestingSpeechIntegrationId(integration.id);
    setConfigNotice("正在测试语音转文字接入...");
    try {
      const response = await testSpeechIntegration({ tenantId, integrationId: integration.id });
      setSpeechTestResults((current) => ({ ...current, [integration.id]: response.result }));
      if (response.speech_integration) {
        setSpeechIntegrations((current) => current.map((item) => (item.id === integration.id ? response.speech_integration! : item)));
      }
      setConfigNotice(response.result.message);
    } catch (error) {
      const result: SpeechIntegrationTestResult = {
        integration_id: integration.id,
        name: integration.name,
        provider: integration.provider,
        source: integration.source || speechProviderLabel(integration.provider),
        callable: false,
        status: "failed",
        message: error instanceof Error ? error.message : "语音转文字接入测试失败",
        endpoint: "",
        response_preview: "",
        tested_at: new Date().toISOString(),
      };
      setSpeechTestResults((current) => ({ ...current, [integration.id]: result }));
      setConfigNotice(`语音转文字接入测试失败：${result.message}`);
    } finally {
      setTestingSpeechIntegrationId("");
    }
  };

  const closeModelAccessModal = () => {
    setAccessModal(null);
    setTestingModelId("");
    setTestingSpeechIntegrationId("");
    setModelTestResults({});
    setSpeechTestResults({});
  };

  const removeSpeechIntegration = async (id: string) => {
    const previousIntegrations = speechIntegrations;
    setSpeechIntegrations((current) => current.filter((item) => item.id !== id));
    try {
      await deleteSpeechIntegration({ tenantId, integrationId: id });
      setConfigNotice("语音转文字接入已从后端删除。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`语音转文字接入已从 demo 本地状态删除，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSpeechIntegrations(previousIntegrations);
      setConfigNotice(`${demoFallbackDisabledMessage("语音转文字接入删除")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const updateSpeechIntegration = async (
    integration: SpeechIntegration,
    patch: Partial<Pick<SpeechIntegration, "name" | "provider" | "source" | "apiBase" | "apiKey" | "applicationModule" | "lastTestedAt" | "testStatus" | "testMessage" | "testResponse" | "status">>,
  ) => {
    const previousIntegrations = speechIntegrations;
    const nextIntegration: SpeechIntegration = {
      ...integration,
      ...patch,
      name: patch.name?.trim() || integration.name,
      provider: patch.provider?.trim() || integration.provider,
      source: patch.source?.trim() || integration.source || speechProviderLabel(integration.provider),
      apiBase: patch.apiBase?.trim() || integration.apiBase,
      apiKey: patch.apiKey?.trim() || integration.apiKey,
      applicationModule: patch.applicationModule?.trim() || integration.applicationModule,
      status: patch.status || integration.status,
    };
    if (!nextIntegration.name || !nextIntegration.provider || !nextIntegration.applicationModule || !nextIntegration.apiBase || !nextIntegration.apiKey) return;
    setSpeechIntegrations((current) => current.map((item) => (item.id === integration.id ? nextIntegration : item)));
    try {
      const response = await saveSpeechIntegration({ tenantId, speechIntegration: nextIntegration });
      setSpeechIntegrations((current) => current.map((item) => (item.id === integration.id ? response.speech_integration : item)));
      setConfigNotice("语音转文字接入已更新。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`语音转文字接入已保留在 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSpeechIntegrations(previousIntegrations);
      setConfigNotice(`${demoFallbackDisabledMessage("语音转文字接入修改")} ${apiErrorMessage(error, "未知错误")}`);
      throw error;
    }
  };

  const updateSystemDataParam = async (param: SystemDataParam, value: string) => {
    const previousParams = systemDataParams;
    const nextParam = { ...param, value };
    setSystemDataParams((current) => current.map((item) => (item.id === param.id ? nextParam : item)));
    try {
      const response = await saveSystemDataParam({ tenantId, param: nextParam });
      setSystemDataParams((current) => current.map((item) => (item.id === param.id ? response.param : item)));
      setConfigNotice("系统数据参数已同步到后端。");
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        setConfigNotice(`系统数据参数已保留在 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
        return;
      }
      setSystemDataParams(previousParams);
      setConfigNotice(`${demoFallbackDisabledMessage("系统数据参数保存")} ${apiErrorMessage(error, "未知错误")}`);
    }
  };

  const openUserEditor = (user?: SystemUser) => {
    if (user) {
      setEditingUserId(user.id);
      setUserForm({
        name: user.name,
        department: user.department,
        email: user.email,
        status: user.status,
        tenantRoles: user.tenantRoles.length ? user.tenantRoles : [{ tenant: selectedInstitution, role: "操作员" }],
      });
    } else {
      setEditingUserId(null);
      setUserForm({
        ...emptyUserForm,
        department: selectedInstitution,
        tenantRoles: [{ tenant: selectedInstitution, role: "操作员" }],
      });
    }
    setUserEditorOpen(true);
  };

  const saveUser = async () => {
    if (!userForm.name.trim() || !userForm.email.trim()) return;
    const fallbackUserId = editingUserId ?? `u_local_${Date.now()}`;
    const tenantRoles = userForm.tenantRoles.length
      ? userForm.tenantRoles
      : [{ tenant: selectedInstitution, role: "操作员" }];
    const draftUser: SystemUser = {
      id: editingUserId ?? "",
      name: userForm.name.trim(),
      department: userForm.department.trim() || tenantRoles[0]?.tenant || selectedInstitution,
      email: userForm.email.trim(),
      status: userForm.status,
      lastLogin: editingUserId ? "刚刚" : "未登录",
      tenantRoles,
    };
    try {
      const response = await saveAccessUser({ tenantId, user: draftUser });
      setUsers((current) =>
        editingUserId
          ? current.map((user) => (user.id === editingUserId ? response.user : user))
          : [response.user, ...current],
      );
      setAccessNotice("用户信息和角色授权已同步到后端。");
      setUserEditorOpen(false);
      setEditingUserId(null);
    } catch (error) {
      if (isDemoFallbackEnabled()) {
        const localUser = { ...draftUser, id: fallbackUserId };
        setUsers((current) =>
          editingUserId
            ? current.map((user) => (user.id === editingUserId ? localUser : user))
            : [localUser, ...current],
        );
        setAccessNotice(`用户已保存到 demo 本地状态，后端同步失败：${apiErrorMessage(error, "未知错误")}`);
      } else {
        setAccessNotice(`${demoFallbackDisabledMessage("用户保存")} ${apiErrorMessage(error, "未知错误")}`);
      }
      setUserEditorOpen(false);
      setEditingUserId(null);
    }
  };

  const removeUser = async (user: SystemUser) => {
    if (user.tenantRoles.some((role) => role.role === "超级管理员")) return;
    const previousUsers = users;
    setUsers((current) => current.filter((item) => item.id !== user.id));
    try {
      await deleteAccessUser({ tenantId, targetUserId: user.id });
      setAccessNotice("用户和角色授权已从后端删除。");
    } catch (error) {
      setUsers(previousUsers);
      setAccessNotice(`删除失败，已恢复本地列表：${error instanceof Error ? error.message : "未知错误"}`);
    }
  };

  const openPermissionEditor = (institutionId: string) => {
    setEditingPermissionId(institutionId);
    setPermissionRole("管理员");
  };

  const updateInstitutionPermission = async (nextPermission: InstitutionPermission) => {
    const previousPermissions = permissionInstitutions;
    const optimisticPermission = {
      ...nextPermission,
      updatedBy: "当前用户",
      updatedAt: "刚刚",
    };
    setPermissionInstitutions((current) =>
      current.map((item) =>
        item.id === nextPermission.id ? optimisticPermission : item,
      ),
    );
    try {
      const response = await saveAccessRolePolicy({ tenantId, permission: optimisticPermission });
      setPermissionInstitutions((current) =>
        current.map((item) => (item.id === response.permission.id ? response.permission : item)),
      );
      setAccessNotice(`${response.permission.institution}角色权限已同步到后端策略库。`);
    } catch (error) {
      setPermissionInstitutions(previousPermissions);
      setAccessNotice(`角色权限保存失败，已恢复本地配置：${error instanceof Error ? error.message : "未知错误"}`);
      throw error;
    }
  };

  const editingPermission = permissionInstitutions.find((item) => item.id === editingPermissionId) ?? null;

  return (
    <div className="p-7">
      <div className="mb-7">
        <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">系统管理</h2>
        <p className="text-[13px] text-[#aeaeb2] mt-1">用户管理 · 角色权限 · 审计日志 · 系统配置</p>
      </div>

      <div className="mb-6 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <section className="rounded-xl border border-[#f0f0f2] bg-white p-4">
          <div className="mb-3 flex items-center justify-between">
            <div className="text-[13px] text-[#1d1d1f]">用户与角色概览</div>
            <span className="text-[11px] text-[#aeaeb2]">当前机构</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { label: "角色数", value: String(roles.length), icon: Shield, color: "#636366" },
              { label: "总用户数", value: String(users.length), icon: Users, color: "#636366" },
              { label: "今日登录", value: "42", icon: Key, color: "#636366" },
              { label: "在线用户", value: String(users.filter((user) => user.status === "active").length), icon: CheckCircle2, color: "#636366" },
            ].map((s) => (
              <div key={s.label} className="rounded-lg bg-[#fafbfc] p-3">
                <div className="mb-2 flex items-center justify-between"><s.icon className="h-4 w-4" style={{ color: s.color }} /></div>
                <div className="text-[21px] tracking-tight text-gray-900">{s.value}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">{s.label}</div>
              </div>
            ))}
          </div>
        </section>
        <AccessConfigCard
          title="模型接入"
          subtitle="统一维护大模型与语音转文字接入"
          icon={Key}
          items={[
            `${modelIntegrations.length} 个大模型接入`,
            `${speechIntegrations.length} 个语音转文字接入`,
            modelIntegrations.map((item) => item.name).join("、") || "暂无大模型配置",
            speechIntegrations.map((item) => `${item.name}(${speechProviderLabel(item.provider)})`).join("、") || "暂无语音配置",
          ]}
          onEdit={() => setAccessModal("model")}
        />
      </div>

      {(activeTab === "users" || activeTab === "roles") && accessNotice && (
        <div className="mb-4 rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[12px] text-[#258a3f]">
          {accessNotice}
        </div>
      )}

      {activeTab === "users" && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
              <input
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="搜索用户..."
                className="pl-9 pr-4 py-2 bg-[#f2f2f7] rounded-lg text-[12px] w-[200px] focus:outline-none focus:ring-1 focus:ring-[#c7c7cc]"
              />
            </div>
            <button
              type="button"
              onClick={() => openUserEditor()}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-[#1d1d1f] text-white rounded-lg text-[12px]"
            >
              <Plus className="w-3.5 h-3.5" /> 添加用户
            </button>
          </div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-gray-400 text-[11px]">
                <th className="text-left py-2.5 px-3">用户</th>
                <th className="text-left py-2.5 px-3">部门</th>
                <th className="text-center py-2.5 px-3">角色</th>
                <th className="text-center py-2.5 px-3">状态</th>
                <th className="text-left py-2.5 px-3">最近登录</th>
                <th className="text-center py-2.5 px-3">操作</th>
              </tr>
            </thead>
            <tbody>
              {users
                .filter((u) => !searchTerm || u.name.includes(searchTerm) || u.department.includes(searchTerm))
                .map((u) => (
                  <tr key={u.id} className="border-t border-gray-50 text-gray-700 hover:bg-[#f5f5f7]">
                    <td className="py-3 px-3">
                      <div className="flex items-center gap-2.5">
                        <div className="w-8 h-8 rounded-full bg-gradient-to-br from-[#34c759]/15 to-[#007aff]/10 flex items-center justify-center text-[11px] text-gray-600">
                          {u.name[0]}
                        </div>
                        <div>
                          <div className="text-[12px] text-gray-800">{u.name}</div>
                          <div className="text-[10px] text-gray-400">{u.email}</div>
                        </div>
                      </div>
                    </td>
                    <td className="py-3 px-3">{u.department}</td>
                    <td className="py-3 px-3 text-center">
                      <div className="flex flex-col items-center gap-1">
                        {u.tenantRoles.map((role) => (
                          <span key={`${u.id}_${role.tenant}_${role.role}`} className="text-[10px] bg-[#f5f5f7] px-2 py-0.5 rounded-full">
                            {role.tenant} · {role.role}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="py-3 px-3 text-center">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full ${u.status === "active" ? "bg-[#34c759]/8 text-[#34c759]" : "bg-gray-100 text-gray-400"}`}>
                        {u.status === "active" ? "活跃" : "停用"}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-gray-400">{u.lastLogin}</td>
                    <td className="py-3 px-3 text-center">
                      <div className="flex items-center justify-center gap-1">
                        <button
                          type="button"
                          onClick={() => openUserEditor(u)}
                          className="p-1.5 hover:bg-[#f5f5f7] rounded-lg"
                          aria-label={`编辑${u.name}`}
                        >
                          <Edit3 className="w-3 h-3 text-gray-400" />
                        </button>
                        <button
                          type="button"
	                          onClick={() => {
	                            void removeUser(u);
	                          }}
                          disabled={u.tenantRoles.some((role) => role.role === "超级管理员")}
                          className="p-1.5 hover:bg-[#fff0f0] rounded-lg disabled:cursor-not-allowed disabled:opacity-30"
                          aria-label={`删除${u.name}`}
                        >
                          <Trash2 className="w-3 h-3 text-gray-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === "roles" && (
        <RolePermissionView
          institutions={permissionInstitutions}
          onEdit={openPermissionEditor}
        />
      )}

      {activeTab === "audit" && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <h3 className="text-[14px] text-gray-800">操作审计日志</h3>
            {auditNotice && <span className="text-[11px] text-[#8a8a8e]">{auditNotice}</span>}
          </div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-gray-400 text-[11px]">
                <th className="text-left py-2.5 px-3">时间</th>
                <th className="text-left py-2.5 px-3">用户</th>
                <th className="text-left py-2.5 px-3">操作</th>
                <th className="text-left py-2.5 px-3">对象</th>
                <th className="text-left py-2.5 px-3">IP地址</th>
              </tr>
            </thead>
            <tbody>
              {(auditRows.length ? auditRows : isDemoFallbackEnabled() ? fallbackAuditLogs : []).map((log, i) => (
                <tr key={i} className="border-t border-gray-50 text-gray-700 hover:bg-[#f5f5f7]">
                  <td className="py-3 px-3 text-gray-400">{log.time}</td>
                  <td className="py-3 px-3">{log.user}</td>
                  <td className="py-3 px-3">
                    <span className="text-[10px] bg-[#f5f5f7] px-2 py-0.5 rounded-full">{log.action}</span>
                  </td>
                  <td className="py-3 px-3 text-gray-600">{log.target}</td>
                  <td className="py-3 px-3 text-gray-400 font-mono text-[11px]">{log.ip}</td>
                </tr>
              ))}
              {!auditRows.length && !isDemoFallbackEnabled() && (
                <tr className="border-t border-gray-50">
                  <td className="px-3 py-6 text-center text-[12px] text-[#8a8a8e]" colSpan={5}>
                    暂无后端审计日志，或当前角色无权查看。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {activeTab === "config" && (
        <div className="space-y-5">
          {configNotice && (
            <div className="rounded-lg border border-[#d7efd9] bg-[#eef8f1] px-3 py-2 text-[12px] text-[#258a3f]">
              {configNotice}
            </div>
          )}
          <SystemDataParamsPanel params={systemDataParams} onSave={updateSystemDataParam} />
        </div>
      )}

      {accessModal === "model" && (
        <ModelAccessModal
          models={modelIntegrations}
          form={modelForm}
          speechIntegrations={speechIntegrations}
          speechForm={speechForm}
          onFormChange={(key, value) => setModelForm((current) => ({ ...current, [key]: value }))}
          onSpeechFormChange={(key, value) => setSpeechForm((current) => ({ ...current, [key]: value }))}
          onAdd={addModelIntegration}
          onAddSpeech={addSpeechIntegration}
          onUpdate={updateModelIntegration}
          onUpdateSpeech={updateSpeechIntegration}
          onDelete={removeModelIntegration}
          onDeleteSpeech={removeSpeechIntegration}
          onTest={runModelIntegrationTest}
          onTestSpeech={runSpeechIntegrationTest}
          testingModelId={testingModelId}
          testingSpeechIntegrationId={testingSpeechIntegrationId}
          testResults={modelTestResults}
          speechTestResults={speechTestResults}
          onClose={closeModelAccessModal}
        />
      )}

      {editingPermission && (
        <PermissionEditorModal
          institution={editingPermission}
          activeRole={permissionRole}
          onRoleChange={setPermissionRole}
          onChange={updateInstitutionPermission}
          onClose={() => setEditingPermissionId(null)}
        />
      )}

      {userEditorOpen && (
        <UserEditorModal
          editing={editingUserId !== null}
          form={userForm}
          institutionOptions={isSuperAdmin ? operatingTenantNames : visibleInstitutions}
          rolePermissions={permissionInstitutions}
          canGrantAdminRole={isSuperAdmin}
          onChange={(key, value) => setUserForm((current) => ({ ...current, [key]: value }))}
          onTenantRolesChange={(tenantRoles) => setUserForm((current) => ({ ...current, tenantRoles }))}
          onSave={saveUser}
          onClose={() => setUserEditorOpen(false)}
        />
      )}
    </div>
  );
}

function AccessConfigCard({
  title,
  subtitle,
  icon: Icon,
  items,
  onEdit,
}: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  items: string[];
  onEdit: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onEdit}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") onEdit();
      }}
      className="cursor-pointer rounded-xl border border-[#f0f0f2] bg-white p-5 transition-colors hover:border-[#d1d1d6]"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#f2f2f7]">
            <Icon className="h-4 w-4 text-[#636366]" />
          </div>
          <div>
            <div className="text-[14px] text-[#1d1d1f]">{title}</div>
            <div className="mt-0.5 text-[12px] text-[#8a8a8e]">{subtitle}</div>
          </div>
        </div>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onEdit();
          }}
          className="rounded-lg p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
          aria-label={`编辑${title}`}
        >
          <Edit3 className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="mt-4 space-y-2 rounded-lg bg-[#fafbfc] p-3">
        {items.map((item, index) => (
          <div key={`${title}_${index}`} className="text-[12px] text-[#636366]">
            {item || "暂无配置"}
          </div>
        ))}
      </div>
    </div>
  );
}

function UserEditorModal({
  editing,
  form,
  institutionOptions,
  rolePermissions,
  canGrantAdminRole,
  onChange,
  onTenantRolesChange,
  onSave,
  onClose,
}: {
  editing: boolean;
  form: typeof emptyUserForm;
  institutionOptions: string[];
  rolePermissions: InstitutionPermission[];
  canGrantAdminRole: boolean;
  onChange: (key: UserFormKey, value: string) => void;
  onTenantRolesChange: (tenantRoles: AccessTenantRole[]) => void;
  onSave: () => void;
  onClose: () => void;
}) {
  const isGlobalSuperAdmin = form.tenantRoles.some((role) => role.role === "超级管理员");
  const availableInstitutions = institutionOptions.length ? institutionOptions : operatingTenantNames;
  const addTenantRole = () => {
    onTenantRolesChange([
      ...form.tenantRoles,
      { tenant: availableInstitutions[0], role: "操作员" },
    ]);
  };
  const updateTenantRole = (index: number, patch: Partial<AccessTenantRole>) => {
    onTenantRolesChange(
      form.tenantRoles.map((role, roleIndex) =>
        roleIndex === index ? { ...role, ...patch } : role,
      ),
    );
  };
  const removeTenantRole = (index: number) => {
    onTenantRolesChange(form.tenantRoles.filter((_, roleIndex) => roleIndex !== index));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[640px] rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <ModalHeader
          title={editing ? "编辑用户" : "添加用户"}
          desc="录入用户信息，并为用户授予具体机构下的管理员、操作员或自定义角色。"
          onClose={onClose}
        />
        <div className="grid gap-4 p-5 md:grid-cols-2">
          <ModelInput label="姓名" value={form.name} onChange={(value) => onChange("name", value)} />
          <ModelInput label="邮箱" value={form.email} onChange={(value) => onChange("email", value)} />
          <ModelInput label="部门" value={form.department} onChange={(value) => onChange("department", value)} />
          <label>
            <span className="mb-1.5 block text-[11px] text-[#8a8a8e]">状态</span>
            <select
              value={form.status}
              onChange={(event) => onChange("status", event.target.value)}
              className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
            >
              <option value="active">活跃</option>
              <option value="inactive">停用</option>
            </select>
          </label>
          <div className="md:col-span-2 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] text-[#1d1d1f]">机构角色授权</span>
              {!isGlobalSuperAdmin && (
                <button
                  type="button"
                  onClick={addTenantRole}
                  className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-[#636366] hover:bg-white"
                >
                  <Plus className="h-3 w-3" />
                  添加授权
                </button>
              )}
            </div>
            <div className="space-y-2">
              {form.tenantRoles.map((role, index) => {
                if (role.role === "超级管理员") {
                  return (
                    <div key={`${role.tenant}_${role.role}_${index}`} className="rounded-lg border border-[#f0f0f2] bg-white p-3 text-[12px] leading-[1.7] text-[#636366]">
                      超级管理员是全局唯一角色，不属于任何单个机构；这里只允许维护姓名、邮箱、部门和状态。
                    </div>
                  );
                }
                const roleOptions = roleOptionsForInstitution(role.tenant, rolePermissions, canGrantAdminRole, role.role);
                return (
                  <div key={`${role.tenant}_${role.role}_${index}`} className="grid gap-2 md:grid-cols-[1fr_1fr_32px]">
                    <select
                      value={role.tenant}
                      onChange={(event) => {
                        const nextTenant = event.target.value;
                        const nextRoleOptions = roleOptionsForInstitution(nextTenant, rolePermissions, canGrantAdminRole, role.role);
                        updateTenantRole(index, { tenant: nextTenant, role: nextRoleOptions[0] || "操作员" });
                      }}
                      className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                    >
                      {availableInstitutions.map((tenant) => (
                        <option key={tenant} value={tenant}>
                          {tenant}
                        </option>
                      ))}
                    </select>
                    <select
                      value={role.role}
                      onChange={(event) => updateTenantRole(index, { role: event.target.value })}
                      className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                    >
                      {roleOptions.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() => removeTenantRole(index)}
                      disabled={form.tenantRoles.length <= 1}
                      className="flex h-9 w-8 items-center justify-center rounded-lg text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025] disabled:cursor-not-allowed disabled:opacity-30"
                      aria-label="移除授权"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
          {isGlobalSuperAdmin && (
            <div className="md:col-span-2 rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-3 text-[12px] leading-[1.7] text-[#636366]">
              超级管理员是全局唯一角色，不属于任何单个机构；这里只允许维护姓名、邮箱、部门和状态，不允许改成机构角色。
            </div>
          )}
        </div>
        <div className="flex items-center justify-end gap-2 border-t border-[#f0f0f2] px-5 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onSave}
            disabled={!form.name.trim() || !form.email.trim() || !form.tenantRoles.length}
            className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40"
          >
            保存用户
          </button>
        </div>
      </div>
    </div>
  );
}

function RolePermissionView({
  institutions,
  onEdit,
}: {
  institutions: InstitutionPermission[];
  onEdit: (institutionId: string) => void;
}) {
  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-4 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h3 className="text-[14px] text-[#1d1d1f]">机构权限配置</h3>
            <p className="mt-0.5 text-[12px] text-[#8a8a8e]">
              点击机构卡片维护默认管理员、操作员和自定义角色权限；超级管理员能力不在机构内重复展示。
            </p>
          </div>
          <div className="rounded-lg bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
            {institutions.length} 个接入机构
          </div>
        </div>

        <div className="space-y-3">
          {institutions.map((institution) => {
            return (
              <div key={institution.id} className="rounded-lg border border-[#f0f0f2] bg-[#fafbfc] p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <Database className="h-4 w-4 text-[#8a8a8e]" />
                      <span className="text-[13px] text-[#1d1d1f]">{institution.institution}</span>
                    </div>
                    <div className="mt-1 text-[11px] text-[#aeaeb2]">
                      最近更新：{institution.updatedAt} · {institution.updatedBy}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => onEdit(institution.id)}
                    className="inline-flex w-fit items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 py-1.5 text-[11px] text-[#636366] transition-colors hover:bg-[#f2f2f7]"
                    aria-label={`编辑${institution.institution}权限`}
                  >
                    <Edit3 className="h-3.5 w-3.5" />
                    编辑权限
                  </button>
                </div>

                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <PermissionSummaryCard
                    title="机构管理员"
                    subtitle="授权机构内全量管理"
                    menus={institution.adminMenus}
                    dataScopes={institution.adminDataScopes}
                  />
                  <PermissionSummaryCard
                    title="机构操作员"
                    subtitle="机构管理员授权生效"
                    menus={institution.operatorAdminMenus}
                    dataScopes={institution.operatorAdminDataScopes}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function PermissionSummaryCard({
  title,
  subtitle,
  menus,
  dataScopes,
  tone = "default",
}: {
  title: PermissionRole;
  subtitle: string;
  menus: string[];
  dataScopes: string[];
  tone?: "default" | "dark" | "warning";
}) {
  const toneClass =
    tone === "dark"
      ? "border-[#1d1d1f]/10 bg-white"
      : tone === "warning"
        ? "border-[#ffe3aa] bg-[#fffaf0]"
        : "border-[#f0f0f2] bg-white";

  return (
    <div className={`rounded-lg border p-3 ${toneClass}`}>
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-[12px] text-[#1d1d1f]">{title}</span>
        <span className="text-[10px] text-[#aeaeb2]">{menus.length} 菜单</span>
      </div>
      <div className="text-[11px] text-[#8a8a8e]">{subtitle}</div>
      <div className="mt-3 flex flex-wrap gap-1">
        {menus.slice(0, 4).map((menu) => (
          <span key={menu} className="rounded-md bg-[#f2f2f7] px-1.5 py-0.5 text-[10px] text-[#636366]">
            {menu}
          </span>
        ))}
        {menus.length > 4 && (
          <span className="rounded-md bg-[#f2f2f7] px-1.5 py-0.5 text-[10px] text-[#8a8a8e]">
            +{menus.length - 4}
          </span>
        )}
      </div>
      <div className="mt-2 text-[10px] text-[#aeaeb2]">{dataScopes.length} 类数据范围</div>
    </div>
  );
}

function PermissionEditorModal({
  institution,
  activeRole,
  onRoleChange,
  onChange,
  onClose,
}: {
  institution: InstitutionPermission;
  activeRole: PermissionRole;
  onRoleChange: (role: PermissionRole) => void;
  onChange: (permission: InstitutionPermission) => Promise<void>;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState(() => ensurePermissionRoleConfigs(institution));
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const roleConfigs = getPermissionRoleConfigs(draft);
  const activeConfig = roleConfigs.find((role) => role.name === activeRole) ?? roleConfigs[0];
  const manageableOptions = roleConfigs
    .filter((role) => role.name !== "管理员")
    .map((role) => role.name);

  const updateRoleConfig = (name: string, patch: Partial<AccessRoleConfig>) => {
    setDraft((current) => {
      const nextConfigs = getPermissionRoleConfigs(current).map((role) =>
        role.name === name ? { ...role, ...patch } : role,
      );
      return syncPermissionFromRoleConfigs(current, nextConfigs);
    });
  };

  const updateRoleList = (field: "menus" | "dataScopes" | "manageableRoles", value: string) => {
    if (!activeConfig) return;
    const currentList = activeConfig[field];
    const nextList = currentList.includes(value)
      ? currentList.filter((item) => item !== value)
      : [...currentList, value];
    updateRoleConfig(activeConfig.name, { [field]: nextList });
  };

  const setRoleList = (field: "menus" | "dataScopes" | "manageableRoles", values: string[]) => {
    if (!activeConfig) return;
    updateRoleConfig(activeConfig.name, { [field]: values });
  };

  const addCustomRole = () => {
    const existingNames = new Set(roleConfigs.map((role) => role.name));
    let index = roleConfigs.filter((role) => role.roleType === "custom").length + 1;
    let name = `自定义角色${index}`;
    while (existingNames.has(name)) {
      index += 1;
      name = `自定义角色${index}`;
    }
    const nextRole: AccessRoleConfig = {
      roleId: `role:${draft.id}:${name}`,
      name,
      roleType: "custom",
      isSystem: false,
      menus: [],
      dataScopes: [],
      manageableRoles: [],
    };
    setDraft((current) => syncPermissionFromRoleConfigs(current, [...getPermissionRoleConfigs(current), nextRole]));
    onRoleChange(name);
  };

  const renameCustomRole = (nextName: string) => {
    if (!activeConfig || activeConfig.isSystem) return;
    const name = nextName.trim().slice(0, 40);
    if (!name || roleConfigs.some((role) => role.name === name && role.name !== activeConfig.name)) return;
    setDraft((current) => {
      const nextConfigs = getPermissionRoleConfigs(current).map((role) =>
        role.name === activeConfig.name ? { ...role, name } : role,
      );
      return syncPermissionFromRoleConfigs(current, nextConfigs);
    });
    onRoleChange(name);
  };

  const save = async () => {
    setSaving(true);
    setSaveError("");
    try {
      await onChange(syncPermissionFromRoleConfigs(draft, getPermissionRoleConfigs(draft)));
      onClose();
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : "保存失败，请稍后重试。");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
      <div className="w-full max-w-[1060px] overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <ModalHeader
          title={`${institution.institution}权限配置`}
          desc="在机构域内维护默认管理员、操作员和自定义角色；菜单、指标数据范围和可管理角色统一在此配置。"
          onClose={onClose}
        />
        <div className="grid max-h-[76vh] min-h-[560px] overflow-hidden lg:grid-cols-[220px_minmax(0,1fr)]">
          <div className="border-r border-[#f0f0f2] bg-[#fafbfc] p-4">
            <div className="mb-3 flex items-center justify-between">
              <span className="text-[12px] text-[#8a8a8e]">角色</span>
              <button
                type="button"
                onClick={addCustomRole}
                className="flex h-6 w-6 items-center justify-center rounded-md text-[#8a8a8e] hover:bg-white hover:text-[#1d1d1f]"
                aria-label="新增自定义角色"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
            {roleConfigs.map((role) => (
              <button
                key={role.name}
                type="button"
                onClick={() => onRoleChange(role.name)}
                className={`mb-2 flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[12px] transition-colors ${
                  activeConfig?.name === role.name ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#636366] hover:bg-white"
                }`}
              >
                <span className="min-w-0 truncate">{roleLabel(role)}</span>
                <ChevronRight className="h-3.5 w-3.5 text-[#c7c7cc]" />
              </button>
            ))}

            <div className="mt-5 rounded-lg border border-[#f0f0f2] bg-white p-3">
              <div className="text-[12px] text-[#1d1d1f]">授权优先级</div>
              <p className="mt-1 text-[11px] leading-[1.6] text-[#8a8a8e]">
                管理员默认可管理操作员和自定义角色；操作员与自定义角色只能使用被授予的菜单和指标权限。
              </p>
            </div>
          </div>

          <div className="overflow-y-auto p-5">
            {activeConfig && (
              <div className="space-y-4">
                <RoleAccessHeader
                  role={roleLabel(activeConfig)}
                  desc={
                    activeConfig.roleType === "admin"
                      ? `${institution.institution}管理员可管理本机构角色，并拥有指标新增和查询权限。`
                      : `${roleLabel(activeConfig)}只能使用被授予的菜单和指标范围，不能管理用户和角色。`
                  }
                />
                {!activeConfig.isSystem && (
                  <div className="rounded-lg border border-[#f0f0f2] bg-white p-4">
                    <ModelInput label="自定义角色名称" value={activeConfig.name} onChange={renameCustomRole} />
                  </div>
                )}
                <EditableMenuPermissionBlock
                  title="一二级菜单权限"
                  desc="二级菜单默认收起，点击一级菜单展开；选择一级菜单会同步选择其下二级菜单。"
                  selected={activeConfig.menus}
                  onToggle={(value) => updateRoleList("menus", value)}
                  onSetSelected={(values) => setRoleList("menus", values)}
                />
                <EditablePermissionBlock
                  title="指标与数据范围"
                  desc="勾选后该角色拥有本机构指标新增和查询权限；修改和删除仍受创建人校验。"
                  options={permissionDataScopes}
                  selected={activeConfig.dataScopes}
                  onToggle={(value) => updateRoleList("dataScopes", value)}
                  onSetSelected={(values) => setRoleList("dataScopes", values)}
                />
                {activeConfig.roleType === "admin" ? (
                  <EditablePermissionBlock
                    title="可管理角色"
                    desc="管理员只能管理本机构操作员和自定义角色，不管理超级管理员和其他机构角色。"
                    options={manageableOptions}
                    selected={activeConfig.manageableRoles}
                    onToggle={(value) => updateRoleList("manageableRoles", value)}
                    onSetSelected={(values) => setRoleList("manageableRoles", values)}
                  />
                ) : (
                  <ReadOnlyPermissionBlock
                    title="可管理角色"
                    items={[]}
                  />
                )}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center justify-between border-t border-[#f0f0f2] px-5 py-4">
          <span className={`text-[12px] ${saveError ? "text-[#d93025]" : "text-[#8a8a8e]"}`}>
            {saveError || "保存后立即更新该机构角色权限配置。"}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-[#e5e5ea] bg-white px-4 py-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
            >
              取消
            </button>
            <button
              type="button"
              onClick={() => void save()}
              disabled={saving}
              className="rounded-lg bg-[#1d1d1f] px-4 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40"
            >
              {saving ? "保存中" : "保存配置"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function RoleAccessHeader({ role, desc }: { role: PermissionRole; desc: string }) {
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-white p-4">
      <div className="flex items-center gap-2">
        <Shield className="h-4 w-4 text-[#636366]" />
        <h3 className="text-[14px] text-[#1d1d1f]">{role}</h3>
      </div>
      <p className="mt-2 text-[12px] leading-[1.7] text-[#636366]">{desc}</p>
    </div>
  );
}

function EditableMenuPermissionBlock({
  title,
  desc,
  selected,
  onToggle,
  onSetSelected,
}: {
  title: string;
  desc: string;
  selected: string[];
  onToggle: (value: string) => void;
  onSetSelected: (values: string[]) => void;
}) {
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);
  const toggleGroup = (group: string) => {
    setExpandedGroups((current) =>
      current.includes(group) ? current.filter((item) => item !== group) : [...current, group],
    );
  };
  const selectGroup = (children: string[]) => {
    const selectedSet = new Set(selected);
    const allSelected = children.every((child) => selectedSet.has(child));
    const next = allSelected
      ? selected.filter((item) => !children.includes(item))
      : Array.from(new Set([...selected, ...children]));
    onSetSelected(next);
  };

  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-white p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-[13px] text-[#1d1d1f]">{title}</div>
          <div className="mt-0.5 text-[11px] text-[#8a8a8e]">{desc}</div>
        </div>
        <PermissionBulkActions onAll={() => onSetSelected(permissionMenus)} onClear={() => onSetSelected([])} />
      </div>
      <div className="space-y-2">
        {permissionMenuGroups.map((group) => {
          const expanded = expandedGroups.includes(group.label);
          const selectedCount = group.children.filter((child) => selected.includes(child)).length;
          const allSelected = selectedCount === group.children.length;
          return (
            <div key={group.label} className="rounded-lg border border-[#f0f0f2]">
              <div className="flex items-center justify-between gap-2 px-3 py-2">
                <button
                  type="button"
                  onClick={() => toggleGroup(group.label)}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left text-[12px] text-[#1d1d1f]"
                >
                  <ChevronRight className={`h-3.5 w-3.5 text-[#c7c7cc] transition-transform ${expanded ? "rotate-90" : ""}`} />
                  <span className="truncate">{group.label}</span>
                  <span className="text-[10px] text-[#aeaeb2]">{selectedCount}/{group.children.length}</span>
                </button>
                <button
                  type="button"
                  onClick={() => selectGroup(group.children)}
                  className={`rounded-md px-2 py-1 text-[11px] ${allSelected ? "bg-[#1d1d1f] text-white" : "bg-[#f5f5f7] text-[#636366]"}`}
                >
                  {allSelected ? "取消" : "全选"}
                </button>
              </div>
              {expanded && (
                <div className="grid gap-2 border-t border-[#f0f0f2] bg-[#fafbfc] p-3 sm:grid-cols-2">
                  {group.children.map((child) => {
                    const checked = selected.includes(child);
                    return (
                      <label
                        key={child}
                        className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[12px] transition-colors ${
                          checked ? "border-[#d1d1d6] bg-white text-[#1d1d1f]" : "border-[#f0f0f2] bg-white text-[#636366]"
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => onToggle(child)}
                          className="h-3.5 w-3.5 accent-[#1d1d1f]"
                        />
                        {child}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function EditablePermissionBlock({
  title,
  desc,
  options,
  selected,
  onToggle,
  onSetSelected,
}: {
  title: string;
  desc: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  onSetSelected: (values: string[]) => void;
}) {
  return (
    <div className="rounded-lg border border-[#f0f0f2] bg-white p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <div className="text-[13px] text-[#1d1d1f]">{title}</div>
          <div className="mt-0.5 text-[11px] text-[#8a8a8e]">{desc}</div>
        </div>
        <PermissionBulkActions onAll={() => onSetSelected(options)} onClear={() => onSetSelected([])} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((option) => {
          const checked = selected.includes(option);
          return (
            <label
              key={option}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-[12px] transition-colors ${
                checked ? "border-[#d1d1d6] bg-[#f8f8fa] text-[#1d1d1f]" : "border-[#f0f0f2] bg-white text-[#636366]"
              }`}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => onToggle(option)}
                className="h-3.5 w-3.5 accent-[#1d1d1f]"
              />
              {option}
            </label>
          );
        })}
      </div>
    </div>
  );
}

function PermissionBulkActions({ onAll, onClear }: { onAll: () => void; onClear: () => void }) {
  return (
    <div className="flex shrink-0 items-center gap-1.5">
      <button type="button" onClick={onAll} className="text-[11px] text-[#1d1d1f] hover:underline">
        全选
      </button>
      <span className="text-[10px] text-[#d1d1d6]">/</span>
      <button type="button" onClick={onClear} className="text-[11px] text-[#8a8a8e] hover:underline">
        取消
      </button>
    </div>
  );
}

function ReadOnlyPermissionBlock({
  title,
  items,
  compact = false,
}: {
  title: string;
  items: string[];
  compact?: boolean;
}) {
  return (
    <div className={`rounded-lg border border-[#f0f0f2] bg-white ${compact ? "p-3" : "p-4"}`}>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-[13px] text-[#1d1d1f]">{title}</span>
        <span className="text-[11px] text-[#aeaeb2]">{items.length} 项</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span key={item} className="rounded-md bg-[#f2f2f7] px-2 py-1 text-[11px] text-[#636366]">
            {item}
          </span>
        ))}
        {!items.length && <span className="text-[12px] text-[#aeaeb2]">未配置</span>}
      </div>
    </div>
  );
}

function ensurePermissionRoleConfigs(permission: InstitutionPermission): InstitutionPermission {
  return syncPermissionFromRoleConfigs(permission, getPermissionRoleConfigs(permission));
}

function getPermissionRoleConfigs(permission: InstitutionPermission): AccessRoleConfig[] {
  if (permission.roleConfigs?.length) {
    return permission.roleConfigs.map((role) => ({
      ...role,
      menus: role.menus || [],
      dataScopes: role.dataScopes || [],
      manageableRoles: role.manageableRoles || [],
    }));
  }
  const customRoles = permission.customRoles || [];
  return [
    {
      roleId: `role:${permission.id}:管理员`,
      name: "管理员",
      roleType: "admin",
      isSystem: true,
      menus: permission.adminMenus || [],
      dataScopes: permission.adminDataScopes || [],
      manageableRoles: permission.manageableRoles || [],
    },
    {
      roleId: `role:${permission.id}:操作员`,
      name: "操作员",
      roleType: "operator",
      isSystem: true,
      menus: permission.operatorAdminMenus || [],
      dataScopes: permission.operatorAdminDataScopes || [],
      manageableRoles: [],
    },
    ...customRoles.map((name) => ({
      roleId: `role:${permission.id}:${name}`,
      name,
      roleType: "custom" as const,
      isSystem: false,
      menus: [] as string[],
      dataScopes: [] as string[],
      manageableRoles: [] as string[],
    })),
  ];
}

function roleOptionsForInstitution(
  institution: string,
  permissions: InstitutionPermission[],
  canGrantAdminRole: boolean,
  currentRole?: string,
) {
  const permission = permissions.find((item) => item.institution === institution);
  const configuredRoles = permission
    ? getPermissionRoleConfigs(permission).map((role) => role.name)
    : userRoleOptions;
  const filteredRoles = configuredRoles.filter((role) => canGrantAdminRole || role !== "管理员");
  return Array.from(new Set([...(currentRole ? [currentRole] : []), ...filteredRoles, "操作员"])).filter(Boolean);
}

function syncPermissionFromRoleConfigs(permission: InstitutionPermission, configs: AccessRoleConfig[]): InstitutionPermission {
  const admin = configs.find((role) => role.name === "管理员") ?? configs[0];
  const operator = configs.find((role) => role.name === "操作员");
  const customRoles = configs.filter((role) => role.roleType === "custom").map((role) => role.name);
  return {
    ...permission,
    adminMenus: admin?.menus || [],
    adminDataScopes: admin?.dataScopes || [],
    operatorSuperMenus: [],
    operatorSuperDataScopes: [],
    operatorAdminMenus: operator?.menus || [],
    operatorAdminDataScopes: operator?.dataScopes || [],
    manageableRoles: admin?.manageableRoles || [],
    customRoles,
    roleConfigs: configs,
  };
}

function roleLabel(role: AccessRoleConfig) {
  if (role.name === "管理员") return "机构管理员";
  if (role.name === "操作员") return "机构操作员";
  return role.name;
}

function SystemDataParamsPanel({
  params,
  onSave,
}: {
  params: SystemDataParam[];
  onSave: (param: SystemDataParam, value: string) => void;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  return (
    <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h3 className="text-[14px] text-gray-800">系统数据参数</h3>
          <p className="mt-1 text-[11px] text-[#aeaeb2]">沉淀刷新频率、并发、留存等运行参数，供分析和周报链路复用。</p>
        </div>
        <span className="rounded-full border border-[#e5e5ea] px-2 py-0.5 text-[11px] text-[#8a8a8e]">
          {params.length} 项
        </span>
      </div>
      <div className="space-y-2">
        {params.map((cfg) => {
          const value = drafts[cfg.id] ?? cfg.value;
          return (
            <div key={cfg.id} className="grid gap-3 rounded-lg bg-[#fafbfc] p-4 transition-colors hover:bg-[#f2f2f7] md:grid-cols-[minmax(0,1fr)_260px_64px] md:items-center">
              <div>
                <div className="text-[13px] text-gray-800">{cfg.name}</div>
                <div className="mt-0.5 text-[11px] text-gray-400">
                  {cfg.category === "security" ? "安全配置" : cfg.category === "data" ? "数据配置" : "系统配置"} · {cfg.description}
                </div>
              </div>
              <input
                value={value}
                onChange={(event) => setDrafts((current) => ({ ...current, [cfg.id]: event.target.value }))}
                className="h-9 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
              />
              <button
                type="button"
                onClick={() => onSave(cfg, value)}
                className="inline-flex h-9 items-center justify-center gap-1 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[12px] text-[#636366] hover:bg-[#f2f2f7]"
              >
                <Edit3 className="h-3.5 w-3.5" />
                保存
              </button>
            </div>
          );
        })}
        {!params.length && (
          <div className="rounded-lg bg-[#fafbfc] px-4 py-8 text-center text-[12px] text-[#aeaeb2]">
            暂无系统数据参数
          </div>
        )}
      </div>
    </div>
  );
}
function ModelAccessModal({
  models,
  form,
  speechIntegrations,
  speechForm,
  onFormChange,
  onSpeechFormChange,
  onAdd,
  onAddSpeech,
  onUpdate,
  onUpdateSpeech,
  onDelete,
  onDeleteSpeech,
  onTest,
  onTestSpeech,
  testingModelId,
  testingSpeechIntegrationId,
  testResults,
  speechTestResults,
  onClose,
}: {
  models: ModelIntegration[];
  form: typeof emptyModelForm;
  speechIntegrations: SpeechIntegration[];
  speechForm: typeof emptySpeechForm;
  onFormChange: (key: keyof typeof emptyModelForm, value: string) => void;
  onSpeechFormChange: <K extends keyof typeof emptySpeechForm>(key: K, value: (typeof emptySpeechForm)[K]) => void;
  onAdd: () => void;
  onAddSpeech: () => void;
  onUpdate: (model: ModelIntegration, patch: Partial<Pick<ModelIntegration, "name" | "modelName" | "applicationModule" | "key" | "value" | "availableModels" | "enabledModels" | "lastTestedAt" | "testStatus" | "testMessage" | "testResponse" | "status">>) => Promise<void>;
  onUpdateSpeech: (integration: SpeechIntegration, patch: Partial<Pick<SpeechIntegration, "name" | "provider" | "source" | "apiBase" | "apiKey" | "applicationModule" | "lastTestedAt" | "testStatus" | "testMessage" | "testResponse" | "status">>) => Promise<void>;
  onDelete: (id: string) => void;
  onDeleteSpeech: (id: string) => void;
  onTest: (model: ModelIntegration) => void;
  onTestSpeech: (integration: SpeechIntegration) => void;
  testingModelId: string;
  testingSpeechIntegrationId: string;
  testResults: Record<string, ModelIntegrationTestResult>;
  speechTestResults: Record<string, SpeechIntegrationTestResult>;
  onClose: () => void;
}) {
  const [activeAccessTab, setActiveAccessTab] = useState<"llm" | "speech">("llm");
  const [editingModelId, setEditingModelId] = useState("");
  const [editingSpeechId, setEditingSpeechId] = useState("");
  const [expandedModelId, setExpandedModelId] = useState("");
  const [expandedSpeechId, setExpandedSpeechId] = useState("");
  const [modelEditDraft, setModelEditDraft] = useState({ name: "", modelName: "中转站", applicationModule: "", key: "", value: "" });
  const [speechEditDraft, setSpeechEditDraft] = useState({ name: "", provider: "aliyun_fun_asr", source: "阿里云", apiBase: "", apiKey: "", applicationModule: "" });

  useEffect(() => {
    setExpandedModelId((current) => {
      if (current && models.some((model) => model.id === current)) return current;
      return "";
    });
  }, [models]);

  const saveModelEdit = async (model: ModelIntegration) => {
    if (!modelEditDraft.name.trim() || !modelEditDraft.key.trim()) return;
    try {
      await onUpdate(model, modelEditDraft);
      setEditingModelId("");
      setModelEditDraft({ name: "", modelName: "中转站", applicationModule: "", key: "", value: "" });
    } catch {
      // Parent owns user-facing notice; keep row editable.
    }
  };

  const saveSpeechEdit = async (integration: SpeechIntegration) => {
    if (!speechEditDraft.name.trim() || !speechEditDraft.apiBase.trim()) return;
    try {
      await onUpdateSpeech(integration, speechEditDraft);
      setEditingSpeechId("");
      setSpeechEditDraft({ name: "", provider: "aliyun_fun_asr", source: "阿里云", apiBase: "", apiKey: "", applicationModule: "" });
    } catch {
      // Parent owns user-facing notice; keep row editable.
    }
  };

  useEffect(() => {
    if (!editingModelId) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest(`[data-model-edit-row="${editingModelId}"]`)) return;
      const model = models.find((item) => item.id === editingModelId);
      if (model) void saveModelEdit(model);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [editingModelId, modelEditDraft, models]);

  useEffect(() => {
    if (!editingSpeechId) return;
    const handlePointerDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      if (target.closest(`[data-speech-edit-row="${editingSpeechId}"]`)) return;
      const integration = speechIntegrations.find((item) => item.id === editingSpeechId);
      if (integration) void saveSpeechEdit(integration);
    };
    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [editingSpeechId, speechEditDraft, speechIntegrations]);

  const startModelEdit = (model: ModelIntegration) => {
    setEditingModelId(model.id);
    setModelEditDraft({ name: model.name, modelName: modelSourceLabel(model.modelName), applicationModule: model.applicationModule || "", key: model.key, value: "" });
  };

  const startSpeechEdit = (integration: SpeechIntegration) => {
    setEditingSpeechId(integration.id);
    setSpeechEditDraft({
      name: integration.name,
      provider: integration.provider,
      source: integration.source || speechProviderLabel(integration.provider),
      apiBase: integration.apiBase,
      apiKey: "",
      applicationModule: integration.applicationModule || "realtime_voice_input",
    });
  };

  const toggleEnabledModel = (model: ModelIntegration, childModel: string) => {
    const current = model.enabledModels || [];
    const enabledModels = current.includes(childModel)
      ? current.filter((item) => item !== childModel)
      : [...current, childModel];
    void onUpdate(model, { enabledModels });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
      <div className="flex h-[min(760px,86vh)] w-full max-w-[1200px] flex-col overflow-hidden rounded-xl border border-[#e5e5ea] bg-white shadow-2xl shadow-black/20">
        <ModalHeader
          title="模型接入管理"
          desc="统一维护系统可调用的大模型、可选子模型和语音转文字能力；业务页面只选择这里已启用的模型配置。"
          onClose={onClose}
        />
        <div className="border-b border-[#f0f0f2] px-5 pt-4">
          <div className="inline-flex rounded-lg bg-[#f2f2f7] p-1">
            {[
              { key: "llm", label: "大模型接入" },
              { key: "speech", label: "语音转文字" },
            ].map((tab) => (
              <button
                key={tab.key}
                type="button"
                onClick={() => setActiveAccessTab(tab.key as "llm" | "speech")}
                className={`rounded-md px-3 py-1.5 text-[12px] transition-colors ${
                  activeAccessTab === tab.key ? "bg-white text-[#1d1d1f] shadow-sm" : "text-[#8a8a8e] hover:text-[#3a3a3c]"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-hidden">
        {activeAccessTab === "llm" && (
          <div className="grid h-full min-h-0 gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_340px]">
            <div className="flex min-h-0 flex-col overflow-hidden rounded-lg border border-[#f0f0f2]">
              <div className="grid grid-cols-[1fr_0.7fr_1fr_0.72fr_1fr_112px] gap-3 border-b border-[#f0f0f2] bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
                <span>模型名称</span>
                <span>模型来源</span>
                <span>API地址</span>
                <span>API密钥</span>
                <span>应用模块</span>
                <span className="text-right">操作</span>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto" data-model-integrations-scroll="true">
              {models.map((model) => {
                const isEditing = editingModelId === model.id;
                const availableModels = availableModelOptions(model);
                const enabledModels = model.enabledModels || [];
                const expanded = expandedModelId === model.id;
                const result = testResults[model.id];
                const isTesting = testingModelId === model.id;
                return (
                  <div key={model.id} className="border-b border-[#f8f8f8] last:border-b-0">
                    <div
                      data-model-edit-row={model.id}
                      onClick={() => {
                        if (!isEditing) setExpandedModelId(expanded ? "" : model.id);
                      }}
                      className={`grid grid-cols-[1fr_0.7fr_1fr_0.72fr_1fr_112px] items-center gap-3 px-3 py-2.5 transition-colors ${
                        isEditing ? "" : "cursor-pointer hover:bg-[#fafbfc]"
                      }`}
                    >
                      {isEditing ? (
                        <>
                          <input
                            value={modelEditDraft.name}
                            onChange={(event) => setModelEditDraft((current) => ({ ...current, name: event.target.value }))}
                            className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
                          />
                          <select value={modelEditDraft.modelName} onChange={(event) => setModelEditDraft((current) => ({ ...current, modelName: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]">
                            {modelSourceOptions.map((source) => <option key={source} value={source}>{source}</option>)}
                          </select>
                          <input value={modelEditDraft.key} onChange={(event) => setModelEditDraft((current) => ({ ...current, key: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]" />
                          <input value={modelEditDraft.value} type="password" placeholder="留空保持原密钥" onChange={(event) => setModelEditDraft((current) => ({ ...current, value: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]" />
                          <select value={modelEditDraft.applicationModule} onChange={(event) => setModelEditDraft((current) => ({ ...current, applicationModule: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]">
                            <option value="">未分配</option>
                            {modelApplicationModuleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                          </select>
                        </>
                      ) : (
                        <>
                          <span className="truncate text-left text-[12px] text-[#1d1d1f]">{model.name}</span>
                          <span className="truncate text-[11px] text-[#3a3a3c]">{modelSourceLabel(model.modelName)}</span>
                          <span className="truncate text-[11px] text-[#8a8a8e]" title="点击编辑后查看和修改">API地址已配置</span>
                          <span className="font-mono text-[11px] text-[#636366]" title="API密钥已隐藏">{maskApiSecret(model.value)}</span>
                          <span className="truncate text-[11px] text-[#3a3a3c]" title={modelApplicationModuleLabel(model.applicationModule)}>{modelApplicationModuleLabel(model.applicationModule)}</span>
                        </>
                      )}
                      <span className="flex justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setExpandedModelId(model.id);
                            onTest(model);
                          }}
                          disabled={Boolean(testingModelId) || isEditing}
                          className={`relative rounded-md p-1.5 transition-colors ${
                            isTesting
                              ? "cursor-wait bg-[#f2f2f7] text-[#c7c7cc]"
                              : "text-[#8a8a8e] hover:bg-[#eef8f1] hover:text-[#258a3f]"
                          } disabled:opacity-80`}
                          aria-label={`测试${model.name}模型接入`}
                        >
                          {isTesting && <span className="absolute -inset-1 rounded-full bg-[#d7efd9] opacity-70 animate-ping" />}
                          <Activity className="relative z-10 h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            if (isEditing) void saveModelEdit(model);
                            else startModelEdit(model);
                          }}
                          className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          aria-label={`修改${model.name}模型接入`}
                        >
                          {isEditing ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Edit3 className="h-3.5 w-3.5" />}
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onDelete(model.id);
                          }}
                          className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]"
                          aria-label={`删除${model.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                    {expanded && (
                      <div className="space-y-2 bg-[#fafbfc] px-3 pb-3 pt-1">
                        {result && (
                          <div className={`rounded-lg border px-3 py-2 text-[11px] leading-relaxed ${
                            result.callable
                              ? "border-[#d7efd9] bg-[#eef8f1] text-[#258a3f]"
                              : "border-[#ffe0b2] bg-[#fff8e8] text-[#9a6a00]"
                          }`}>
                            <div>{result.message}</div>
                            {result.response_preview && (
                              <div className="mt-1 text-[#636366]">返回：{result.response_preview}</div>
                            )}
                          </div>
                        )}
                        <div className="rounded-lg border border-[#f0f0f2] bg-white p-2">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <span className="text-[11px] text-[#8a8a8e]">可选模型</span>
                            {!result && !model.availableModels?.length && <span className="text-[10px] text-[#aeaeb2]">未测试时显示默认候选</span>}
                            {result?.available_models?.length ? <span className="text-[10px] text-[#aeaeb2]">测试返回模型已同步</span> : null}
                          </div>
                          <div className="grid gap-2 md:grid-cols-2">
                            {availableModels.map((childModel) => (
                              <label
                                key={childModel}
                                onClick={(event) => event.stopPropagation()}
                                className="flex cursor-pointer items-start gap-2 rounded-lg border border-[#e5e5ea] bg-white px-2.5 py-2 text-left hover:bg-[#fafbfc]"
                              >
                                <input
                                  type="checkbox"
                                  checked={enabledModels.includes(childModel)}
                                  onChange={() => toggleEnabledModel(model, childModel)}
                                  className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[#1d1d1f]"
                                />
                                <span className="min-w-0">
                                  <span className="block truncate font-mono text-[11px] text-[#3a3a3c]">{childModel}</span>
                                  <span className="mt-0.5 block text-[10px] leading-relaxed text-[#8a8a8e]">{modelOptionDescription(childModel)}</span>
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {!models.length && <div className="px-3 py-8 text-center text-[12px] text-[#aeaeb2]">暂无大模型接入</div>}
              </div>
            </div>
            <div className="overflow-y-auto rounded-lg bg-[#fafbfc] p-4">
              <div className="mb-3 text-[13px] text-[#1d1d1f]">新增模型</div>
              <ModelInput label="模型名称" value={form.name} onChange={(value) => onFormChange("name", value)} />
              <div className="grid grid-cols-2 gap-3">
                <ModelSelect label="模型来源" value={modelSourceOptions.includes(form.modelName) ? form.modelName : modelSourceOptions[0]} options={modelSourceOptions.map((source) => ({ label: source, value: source }))} onChange={(value) => onFormChange("modelName", value)} />
                <ModelSelect label="应用模块" value={form.applicationModule} options={[{ label: "请选择", value: "" }, ...modelApplicationModuleOptions]} onChange={(value) => onFormChange("applicationModule", value)} />
              </div>
              <ModelInput label="API地址" value={form.key} placeholder="https://zetatechs.com/api/v1/..." onChange={(value) => onFormChange("key", value)} />
              <ModelInput label="API密钥" value={form.value} type="password" placeholder="请输入 API 密钥" onChange={(value) => onFormChange("value", value)} />
              <button
                type="button"
                onClick={onAdd}
                disabled={!form.name.trim() || !form.modelName.trim() || !form.applicationModule.trim() || !form.key.trim() || !form.value.trim()}
                className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40"
              >
                <Plus className="h-3.5 w-3.5" />
                新增模型
              </button>
            </div>
          </div>
        )}

        {activeAccessTab === "speech" && (
          <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="overflow-hidden rounded-lg border border-[#f0f0f2]">
              <div className="grid grid-cols-[0.9fr_0.8fr_1.2fr_0.8fr_1.1fr_128px] gap-3 border-b border-[#f0f0f2] bg-[#fafbfc] px-3 py-2 text-[11px] text-[#8a8a8e]">
                <span>模型名称</span>
                <span>模型来源</span>
                <span>API地址</span>
                <span>API密钥</span>
                <span>应用模块</span>
                <span className="text-right">操作</span>
              </div>
              {speechIntegrations.map((integration) => {
                const isEditing = editingSpeechId === integration.id;
                const result = speechTestResults[integration.id];
                const expanded = expandedSpeechId === integration.id;
                const isTesting = testingSpeechIntegrationId === integration.id;
                return (
                  <div key={integration.id} className="border-b border-[#f8f8f8] last:border-b-0">
                    <div
                      data-speech-edit-row={integration.id}
                      onClick={() => {
                        if (!isEditing) setExpandedSpeechId(expanded ? "" : integration.id);
                      }}
                      className={`grid grid-cols-[0.9fr_0.8fr_1.2fr_0.8fr_1.1fr_128px] items-center gap-3 px-3 py-2.5 transition-colors ${
                        isEditing ? "" : "cursor-pointer hover:bg-[#fafbfc]"
                      }`}
                    >
                      {isEditing ? (
                        <>
                          <input value={speechEditDraft.name} onChange={(event) => setSpeechEditDraft((current) => ({ ...current, name: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                          <select
                            value={speechEditDraft.provider}
                            onChange={(event) => setSpeechEditDraft((current) => ({ ...current, provider: event.target.value, source: speechProviderLabel(event.target.value) }))}
                            className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]"
                          >
                            <option value="aliyun_fun_asr">阿里云 Fun-ASR</option>
                          </select>
                          <input value={speechEditDraft.apiBase} onChange={(event) => setSpeechEditDraft((current) => ({ ...current, apiBase: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                          <input value={speechEditDraft.apiKey} type="password" placeholder="留空保持原密钥" onChange={(event) => setSpeechEditDraft((current) => ({ ...current, apiKey: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]" />
                          <select value={speechEditDraft.applicationModule} onChange={(event) => setSpeechEditDraft((current) => ({ ...current, applicationModule: event.target.value }))} className="h-8 rounded-lg border border-[#e5e5ea] bg-white px-2 text-[11px] outline-none focus:border-[#c7c7cc]">
                            {modelApplicationModuleOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                          </select>
                        </>
                      ) : (
                        <>
                          <span className="text-[12px] text-[#8a8a8e]" title="点击编辑后查看和修改">模型名称已配置</span>
                          <span className="text-[12px] text-[#636366]">{integration.source || speechProviderLabel(integration.provider)}</span>
                          <span className="truncate text-[11px] text-[#8a8a8e]" title="点击编辑后查看和修改">API地址已配置</span>
                          <span className="font-mono text-[11px] text-[#636366]" title="API密钥已隐藏">{maskApiSecret(integration.apiKey)}</span>
                          <span className="truncate text-[11px] text-[#3a3a3c]" title={modelApplicationModuleLabel(integration.applicationModule)}>{modelApplicationModuleLabel(integration.applicationModule)}</span>
                        </>
                      )}
                      <span className="flex justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            setExpandedSpeechId(integration.id);
                            onTestSpeech(integration);
                          }}
                          disabled={isTesting || isEditing}
                          className={`relative rounded-md p-1.5 transition-colors ${
                            isTesting
                              ? "cursor-wait bg-[#f2f2f7] text-[#c7c7cc]"
                              : "text-[#8a8a8e] hover:bg-[#eef8f1] hover:text-[#258a3f]"
                          } disabled:opacity-80`}
                          aria-label={`测试${integration.name}语音转文字接入`}
                        >
                          {isTesting && <span className="absolute -inset-1 rounded-full bg-[#d7efd9] opacity-70 animate-ping" />}
                          <Activity className="relative z-10 h-3.5 w-3.5" />
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            if (isEditing) void saveSpeechEdit(integration);
                            else startSpeechEdit(integration);
                          }}
                          className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#f2f2f7] hover:text-[#1d1d1f]"
                          aria-label={`修改${integration.name}`}
                        >
                          {isEditing ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Edit3 className="h-3.5 w-3.5" />}
                        </button>
                        <button
                          type="button"
                          onClick={(event) => {
                            event.stopPropagation();
                            onDeleteSpeech(integration.id);
                          }}
                          className="rounded-md p-1.5 text-[#8a8a8e] hover:bg-[#fff0f0] hover:text-[#d93025]"
                          aria-label={`删除${integration.name}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </span>
                    </div>
                    {expanded && (
                      <div className="space-y-2 bg-[#fafbfc] px-3 pb-3 pt-1">
                        {result && (
                          <div className={`rounded-lg border px-3 py-2 text-[11px] leading-relaxed ${
                            result.callable
                              ? "border-[#d7efd9] bg-[#eef8f1] text-[#258a3f]"
                              : "border-[#ffe0b2] bg-[#fff8e8] text-[#9a6a00]"
                          }`}>
                            <div>{result.message}</div>
                            {result.response_preview && (
                              <div className="mt-1 truncate text-[#636366]">返回：{result.response_preview}</div>
                            )}
                          </div>
                        )}
                        <div className="rounded-lg border border-[#f0f0f2] bg-white p-2">
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <span className="text-[11px] text-[#8a8a8e]">语音转文字能力</span>
                            <span className="text-[10px] text-[#aeaeb2]">保存并启用后可直接使用；测试仅用于排查</span>
                          </div>
                          <div className="grid gap-2 md:grid-cols-2">
                            {speechCapabilityOptions(integration).map((capability) => (
                              <label
                                key={capability.model}
                                onClick={(event) => event.stopPropagation()}
                                className="flex cursor-default items-start gap-2 rounded-lg border border-[#e5e5ea] bg-white px-2.5 py-2 text-left"
                              >
                                <input type="checkbox" checked readOnly className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[#1d1d1f]" />
                                <span className="min-w-0">
                                  <span className="block text-[11px] text-[#3a3a3c]">{capability.title}</span>
                                  <span className="mt-0.5 block truncate font-mono text-[10px] text-[#8a8a8e]">{capability.model}</span>
                                  <span className="mt-0.5 block text-[10px] leading-relaxed text-[#8a8a8e]">{capability.description}</span>
                                </span>
                              </label>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {!speechIntegrations.length && <div className="px-3 py-8 text-center text-[12px] text-[#aeaeb2]">暂无语音转文字接入</div>}
            </div>
            <div className="rounded-lg bg-[#fafbfc] p-4">
              <div className="mb-3 text-[13px] text-[#1d1d1f]">新增语音转文字接入</div>
              <ModelInput label="模型名称" value={speechForm.name} onChange={(value) => onSpeechFormChange("name", value)} />
              <div className="grid grid-cols-2 gap-3">
                <ModelSelect label="模型来源" value={speechForm.provider} options={[{ label: "阿里云 Fun-ASR", value: "aliyun_fun_asr" }]} onChange={(value) => { onSpeechFormChange("provider", value); onSpeechFormChange("source", speechProviderLabel(value)); }} />
                <ModelSelect label="应用模块" value={speechForm.applicationModule} options={[...modelApplicationModuleOptions]} onChange={(value) => onSpeechFormChange("applicationModule", value)} />
              </div>
              <ModelInput label="API地址" value={speechForm.apiBase} placeholder="https://ws-xxx.cn-beijing.maas.aliyuncs.com/api/v1" onChange={(value) => onSpeechFormChange("apiBase", value)} />
              <ModelInput label="API密钥" value={speechForm.apiKey} type="password" placeholder="请输入 DashScope API Key" onChange={(value) => onSpeechFormChange("apiKey", value)} />
              <button
                type="button"
                onClick={onAddSpeech}
                disabled={!speechForm.name.trim() || !speechForm.provider.trim() || !speechForm.applicationModule.trim() || !speechForm.apiBase.trim() || !speechForm.apiKey.trim()}
                className="mt-2 inline-flex w-full items-center justify-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 py-2 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-40"
              >
                <Plus className="h-3.5 w-3.5" />
                新增语音接入
              </button>
            </div>
          </div>
        )}
        </div>
      </div>
    </div>
  );
}

function ModalHeader({ title, desc, onClose }: { title: string; desc: string; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between border-b border-[#f0f0f2] px-5 py-4">
      <div>
        <h3 className="text-[14px] text-[#1d1d1f]">{title}</h3>
        <p className="mt-0.5 text-[11px] text-[#aeaeb2]">{desc}</p>
      </div>
      <button
        type="button"
        onClick={onClose}
        className="flex h-8 w-8 items-center justify-center rounded-lg text-[#8a8a8e] hover:bg-[#f2f2f7]"
        aria-label="关闭弹窗"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}

function ModelInput({
  label,
  value,
  placeholder,
  type = "text",
  onChange,
}: {
  label: string;
  value: string;
  placeholder?: string;
  type?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="mb-3 block">
      <span className="mb-1.5 block text-[11px] text-[#8a8a8e]">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
      />
    </label>
  );
}

function ModelSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ label: string; value: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="mb-3 block">
      <span className="mb-1.5 block text-[11px] text-[#8a8a8e]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] outline-none focus:border-[#c7c7cc]"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  );
}
