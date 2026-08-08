import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type DataAssetGovernanceFields = {
  lifecycleStatus?: "draft" | "review" | "active" | "rejected" | "archived";
  assetVersion?: number;
  schemaVersion?: string;
  lockVersion?: number;
  submittedBy?: string;
  reviewedBy?: string;
  reviewedAt?: string;
  publishedAt?: string;
};

export type RawField = {
  fieldNameEn: string;
  fieldNameCn: string;
  type: string;
  explanation: string;
  enumValues?: string;
  isPrimaryKey?: boolean;
  isTime?: boolean;
  isMetric?: boolean;
  metricLogic?: string;
  metricCode?: string;
  relatedMetrics?: string;
  notes?: string;
  exampleUsage?: string;
};

export type RawTableAsset = DataAssetGovernanceFields & {
  id: string;
  tableNameEn: string;
  tableNameCn: string;
  source: string;
  tableType: string;
  primaryKey: string;
  dateField: string;
  orgField: string;
  customerField: string;
  description: string;
  updateFrequency: string;
  restrictions: string;
  exampleSql: string;
  fields: RawField[];
  updatedAt: string;
  fileName?: string;
  objectFileName?: string;
  artifactId?: string;
  artifactObjectUri?: string;
  artifactContentHash?: string;
  artifactContentType?: string;
  artifactSizeBytes?: number;
  rowCount?: number;
  usageScenario?: string;
  relatedIntent?: string;
  connectionId?: string;
  sourceSnapshotId?: string;
  /** Project-relative CSV path. Present for the read-only CSV source catalog. */
  relativePath?: string;
  /** Bounded source preview. The catalog returns at most the first 10 rows. */
  previewRows?: Array<Record<string, string>>;
  contentHash?: string;
  /** The platform that owns credentials and execution for this table. */
  sourcePlatform?: "毓数" | "智能运营" | "本地CSV";
  /** Stable external-tool registry id used by future data calls. */
  linkedToolId?: string;
};

export type TopicTableAsset = DataAssetGovernanceFields & {
  id: string;
  name: string;
  code: string;
  description: string;
  sql: string;
  fields: RawField[] | string;
  fieldExplanations: string;
  applicableScene: string;
  relatedIntent: string;
  relatedExperience: string;
  quickDisplay: boolean;
  reportReference: string;
  source: string;
  updatedAt: string;
  datasetId?: string;
  metricCodes?: string[];
  defaultMetrics?: string[];
  dimensionCodes?: string[];
  defaultDimensions?: string[];
  chartTypes?: string[];
  analysisAngles?: string[];
  rowCount?: number;
  qualityReport?: string;
  systemManaged?: boolean;
  deletable?: boolean;
  dataSnapshot?: TopicDataReference | null;
};

export type TopicDataReference = {
  reference_type: "history" | "shortcut" | "topic" | "report";
  reference_id: string;
  folder: string;
  version_id?: string;
  task_id?: string;
  updated_at: string;
  row_count: number;
  has_data: boolean;
  version_count: 1;
};

export type TopicDataSnapshot = {
  tenant_id: string;
  reference_type: TopicDataReference["reference_type"];
  reference_id: string;
  data_type: "data" | "raw";
  folder: string;
  manifest: Record<string, unknown>;
  columns: string[];
  rows: Array<Record<string, string>>;
  row_count: number;
  truncated: boolean;
};

export type IntentAsset = DataAssetGovernanceFields & {
  id: string;
  scenario: string;
  purpose: string;
  description: string;
  keywords: string;
  relatedTopic: string;
  relatedMetrics: string;
  relatedExperience: string;
  pageScope: string;
  enabled: boolean;
  examples: string;
};

export type AnalysisExperienceAsset = DataAssetGovernanceFields & {
  id: string;
  title?: string;
  name: string;
  description?: string;
  analysisSteps?: string;
  scenario?: string;
  sourceVersionId?: string;
  sourceVersionName?: string;
  evidence?: string;
  relatedMetrics?: string;
  firstSeenAt?: string;
  lastSeenAt?: string;
  frequency?: number;
  weight?: number;
  status?: string;
  confidence?: number;
  relatedTopic: string;
  relatedIntent: string;
  steps: string;
  metrics: string;
  rules: string;
  commonConclusions: string;
  riskTips: string;
  summaryTemplate: string;
  institutionScope: string;
  enabled: boolean;
  updatedAt: string;
};

export type BehaviorHabitAsset = DataAssetGovernanceFields & {
  id: string;
  title: string;
  habitType: "分析习惯" | "运营习惯" | "汇报习惯";
  description: string;
  behaviorDetail: string;
  sourceVersionId: string;
  sourceVersionName?: string;
  evidence: string;
  relatedMetrics: string;
  relatedOrgs: string;
  firstSeenAt: string;
  lastSeenAt: string;
  frequency: number;
  weight: number;
  status: string;
  confidence: number;
  updatedAt: string;
};

export type KnowledgeFileAsset = DataAssetGovernanceFields & {
  id: string;
  title: string;
  coverage: string;
  items: number;
  updated: string;
  owner: string;
  tags: string;
};

export type AnalysisSkillAsset = DataAssetGovernanceFields & {
  id: string;
  name: string;
  category: "场景" | "主题";
  description: string;
  memoryRefs: string[];
  toolRefs: string[];
  analysisMethod: string;
  documentAbstraction: string;
  outputFormat: string;
  viewpointStrategy: string;
  recommendedSkillIds: string[];
  enabled: boolean;
  sortOrder: number;
};

export type ExternalToolAsset = DataAssetGovernanceFields & {
  id: string;
  name: string;
  provider: string;
  toolType: string;
  description: string;
  endpoint: string;
  capabilities: string[];
  enabled: boolean;
  status: string;
};

export type AnalysisShortcutAsset = DataAssetGovernanceFields & {
  id: string;
  title: string;
  query: string;
  skillIds: string[];
  tableIds: string[];
  memoryIds: string[];
  visible: boolean;
  sortOrder: number;
  ownerUserId: string;
};

export type DataAssetBundle = {
  tenant_id: string;
  status?: "loading" | "ready";
  message?: string;
  source_mode?: "csv_folder" | "knowledge_only";
  csv_source?: {
    mode: "csv_folder";
    root: string;
    available: boolean;
    file_count: number;
    scanned_at: string;
    files: Array<{
      relative_path: string;
      file_name: string;
      size_bytes: number;
      modified_at: string;
      content_hash: string;
      row_count: number;
      columns: string[];
    }>;
  };
  raw_tables: RawTableAsset[];
  topic_tables: TopicTableAsset[];
  intents: IntentAsset[];
  analysis_experiences: AnalysisExperienceAsset[];
  behavior_habits: BehaviorHabitAsset[];
  knowledge_files: KnowledgeFileAsset[];
  analysis_skills: AnalysisSkillAsset[];
  external_tools: ExternalToolAsset[];
  analysis_shortcuts: AnalysisShortcutAsset[];
  count: Record<string, number>;
};

export type DataAssetItemType =
  | "raw_table"
  | "topic_table"
  | "intent"
  | "analysis_experience"
  | "user_behavior_habit"
  | "knowledge_file"
  | "analysis_skill"
  | "external_tool"
  | "analysis_shortcut";

type DataAssetParams = {
  tenantId: string;
  userId?: string;
  scope?: "knowledge";
};

export type RawFileUpload = {
  file_name: string;
  artifact_id: string;
  object_uri: string;
  content_hash: string;
  content_type: string;
  size_bytes: number;
};

export async function fetchDataAssets({
  tenantId,
  userId = getDefaultUserId(),
  scope,
}: DataAssetParams): Promise<DataAssetBundle> {
  const query = scope ? `?${new URLSearchParams({ scope }).toString()}` : "";
  return apiRequest<DataAssetBundle>(`/api/data-assets${query}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function fetchTopicData({
  tenantId,
  userId = getDefaultUserId(),
  referenceType,
  referenceId,
  dataType = "data",
}: DataAssetParams & {
  referenceType: TopicDataReference["reference_type"];
  referenceId: string;
  dataType?: "data" | "raw";
}): Promise<TopicDataSnapshot> {
  const params = new URLSearchParams({
    reference_type: referenceType,
    reference_id: referenceId,
    data_type: dataType,
  });
  return apiRequest<TopicDataSnapshot>(`/api/topic-data?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
  });
}

export async function saveDataAssetItem<T extends object>({
  tenantId,
  userId = getDefaultUserId(),
  itemType,
  item,
}: DataAssetParams & {
  itemType: DataAssetItemType;
  item: T;
}): Promise<{ tenant_id: string; item_type: DataAssetItemType; item: T }> {
  return apiRequest<{ tenant_id: string; item_type: DataAssetItemType; item: T }>("/api/data-assets/item", {
    method: "POST",
    context: { tenantId, userId },
    body: { item_type: itemType, item },
  });
}

export async function uploadRawDataFile({
  tenantId,
  userId = getDefaultUserId(),
  file,
}: DataAssetParams & { file: File }): Promise<{ tenant_id: string; file: RawFileUpload }> {
  const contentBase64 = await fileToBase64(file);
  return apiRequest<{ tenant_id: string; file: RawFileUpload }>("/api/data-assets/raw-file", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      file_name: file.name,
      content_base64: contentBase64,
    },
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("raw_file_read_failed"));
    reader.onload = () => {
      const result = String(reader.result || "");
      const separator = result.indexOf(",");
      if (separator < 0) {
        reject(new Error("raw_file_read_failed"));
        return;
      }
      resolve(result.slice(separator + 1));
    };
    reader.readAsDataURL(file);
  });
}

export async function deleteDataAssetItem({
  tenantId,
  userId = getDefaultUserId(),
  itemType,
  itemId,
}: DataAssetParams & {
  itemType: DataAssetItemType;
  itemId: string;
}): Promise<{ tenant_id: string; item_type: DataAssetItemType; item_id: string; deleted: boolean }> {
  const params = new URLSearchParams({ item_type: itemType, item_id: itemId });
  return apiRequest<{ tenant_id: string; item_type: DataAssetItemType; item_id: string; deleted: boolean }>(
    `/api/data-assets/item?${params.toString()}`,
    {
      method: "DELETE",
      context: { tenantId, userId },
    },
  );
}

export async function reviewDataAssetItem({
  tenantId,
  userId = getDefaultUserId(),
  itemType,
  itemId,
  expectedVersion,
  decision,
  comments = "",
}: DataAssetParams & {
  itemType: DataAssetItemType;
  itemId: string;
  expectedVersion: number;
  decision: "approved" | "rejected" | "changes_required";
  comments?: string;
}): Promise<{ tenant_id: string; item_type: DataAssetItemType; item: Record<string, unknown> }> {
  return apiRequest("/api/data-assets/item/review", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      item_type: itemType,
      item_id: itemId,
      expected_version: expectedVersion,
      decision,
      comments,
    },
  });
}
