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
  /** Business role used by every data picker and visualization consumer. */
  semanticRole?: "metric" | "dimension" | "date";
  /** Display contract for date fields; source values remain unchanged. */
  dateFormat?: "yyyy-MM-dd";
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
  primaryKeys?: string[];
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
  /** Stable logical source identity; persists across daily CSV deliveries. */
  sourceKey?: string;
  /** Hash of current field names/types; a changed schema fails closed. */
  schemaFingerprint?: string;
  /** SDA-side policy only; it never changes the CSV file. */
  externalReferenceMode?: "private" | "shared";
  externalReferenceUpdatedAt?: string;
  externalReferenceSchemaChanged?: boolean;
  /** The platform that owns credentials and execution for this table. */
  sourcePlatform?: "毓数" | "智能运营" | "本地CSV" | "静态工作簿";
  /** Stable external-tool registry id used by future data calls. */
  linkedToolId?: string;
  /** Stable id/version of the SDA-side metadata overlay; CSV rows stay read-only. */
  metadataConfigId?: string;
  metadataConfigLockVersion?: number;
  metadataConfigSchemaChanged?: boolean;
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
  memoryTopic?: string;
  memoryAction?: string;
  memoryMergeKey?: string;
  occurrenceCount?: number;
  mergedFromIds?: string[];
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
  memoryTopic?: string;
  memoryAction?: string;
  memoryMergeKey?: string;
  occurrenceCount?: number;
  mergedFromIds?: string[];
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
  content?: string;
  coverage: string;
  items: number;
  updated: string;
  owner: string;
  tags: string;
};

export type AnalysisSkillDisplayLocation = "intelligent_analysis" | "hidden";

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
  displayLocation?: AnalysisSkillDisplayLocation;
  sortOrder: number;
  learningOrigin?: string;
  learningKind?: string;
  learningTrigger?: { datasetId?: string; intentRuleId?: string };
  learningEvolution?: Record<string, unknown>;
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

export type PageDataPageCode = "dashboard" | "weekly_report" | "institution_supervision" | "customer_segment_analysis";
export type PageDataConsumerCode = PageDataPageCode | "self_analysis" | "visual_report" | "my_reports";
export type PageDataInstitutionScope = "single_institution" | "multi_institution" | "customer_segment";

export type MultiInstitutionPageDataSource = {
  nodeId?: string;
  tenantId: string;
  institutionName: string;
  sourceKey: string;
  sourceTableId: string;
  sourceTableName: string;
  schemaFingerprint: string;
};

export type MultiInstitutionPageDataCandidate = {
  id: string;
  name: string;
  schemaFingerprint: string;
  fields: RawField[];
  sources: MultiInstitutionPageDataSource[];
  relationshipEdges?: TableRelationshipEdge[];
  institutionCount?: number;
  tableCount?: number;
};

export type TableRelationshipNode = {
  id: string;
  tenantId: string;
  institutionName: string;
  sourceKey: string;
  sourceTableId: string;
  sourceTableName: string;
  schemaFingerprint: string;
  position: { x: number; y: number };
  fields: RawField[];
};

export type TableRelationshipEdge = {
  id: string;
  sourceNodeId: string;
  sourceField: string;
  targetNodeId: string;
  targetField: string;
  joinType: "inner";
};

export type TableRelationshipAsset = DataAssetGovernanceFields & {
  id: string;
  name: string;
  relationshipScope: "single_institution" | "multi_institution";
  nodes: TableRelationshipNode[];
  edges: TableRelationshipEdge[];
  institutionCount: number;
  tableCount: number;
  updatedAt: string;
};

export type TableRelationshipCatalogTable = {
  tenantId: string;
  institutionName: string;
  id: string;
  sourceKey: string;
  tableNameEn: string;
  tableNameCn: string;
  schemaFingerprint: string;
  rowCount: number;
  fields: RawField[];
};

export type TableRelationshipCatalog = {
  tenant_id: string;
  status?: "loading" | "ready";
  institutions: Array<{ tenantId: string; institutionName: string; tables: TableRelationshipCatalogTable[] }>;
  count: { institutions: number; tables: number };
  source_read_only: true;
  message?: string;
};

export type PageDataAsset = DataAssetGovernanceFields & {
  id: string;
  name: string;
  sourceKey: string;
  sourceTableId: string;
  sourceTableName: string;
  sourceRelativePath?: string;
  schemaFingerprint: string;
  contentHash?: string;
  sourceFields: RawField[];
  targetPages: PageDataPageCode[];
  metricFields: string[];
  dimensionFields: string[];
  visualizationType: string;
  updatedAt: string;
  institutionScope?: PageDataInstitutionScope;
  relationshipGroupId?: string;
  institutionSources?: MultiInstitutionPageDataSource[];
  customerKeyField?: string;
};

export type DataAssetBundle = {
  tenant_id: string;
  status?: "loading" | "ready";
  message?: string;
  source_mode?: "csv_folder" | "knowledge_only" | "runtime_published";
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
  page_data: PageDataAsset[];
  table_relationships: TableRelationshipAsset[];
  relationships: DataAssetRelationship[];
  count: Record<string, number>;
};

type DataAssetBundleWire = Omit<DataAssetBundle, "table_relationships"> & {
  table_relationships?: unknown;
};

/** Keep additive frontend fields compatible with an API process that has not
 * restarted onto the latest bundle schema yet. Existing payload data is kept;
 * only the absent new collection receives its neutral empty value. */
export function normalizeDataAssetBundle(bundle: DataAssetBundleWire): DataAssetBundle {
  return {
    ...bundle,
    table_relationships: Array.isArray(bundle.table_relationships) ? bundle.table_relationships : [],
  };
}

export type DataAssetRelationship = {
  lineage_edge_id: string;
  source_type: string;
  source_id: string;
  target_type: string;
  target_id: string;
  edge_type: "reads" | "derives" | "aggregates" | "references" | "publishes" | "generates";
  confidence: number;
  expression_hash?: string;
  metadata?: Record<string, unknown>;
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
  | "analysis_shortcut"
  | "page_data"
  | "table_relationship";

type DataAssetParams = {
  tenantId: string;
  userId?: string;
  scope?: "knowledge" | "runtime" | "visualization";
};

export type RawFileUpload = {
  file_name: string;
  artifact_id: string;
  object_uri: string;
  content_hash: string;
  content_type: string;
  size_bytes: number;
  tables?: RawTableAsset[];
  table_count?: number;
  duplicate?: boolean;
  immutable?: boolean;
};

export async function fetchDataAssets({
  tenantId,
  userId = getDefaultUserId(),
  scope,
}: DataAssetParams): Promise<DataAssetBundle> {
  const query = scope ? `?${new URLSearchParams({ scope }).toString()}` : "";
  const bundle = await apiRequest<DataAssetBundleWire>(`/api/data-assets${query}`, {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: scope === "visualization" ? 60_000 : 20_000, tags: ["data-assets", scope ? `data-assets:${scope}` : "data-assets:catalog"] },
  });
  return normalizeDataAssetBundle(bundle);
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
    readCache: { ttlMs: 10_000, tags: ["topic-data"] },
  });
}

export type PageDataRows = {
  tenant_id: string;
  page_code: PageDataConsumerCode;
  page_data_id: string;
  source_key: string;
  schema_fingerprint: string;
  fields: string[];
  field_labels: Record<string, string>;
  row_count: number;
  rows: Array<Record<string, string>>;
  bounded: true;
  customer_segment?: {
    customer_count: number;
    matched_count: number;
    content_hash: string;
  };
};

export async function fetchPageDataRows({
  tenantId,
  userId = getDefaultUserId(),
  pageDataId,
  pageCode,
}: DataAssetParams & { pageDataId: string; pageCode: PageDataConsumerCode }) {
  const params = new URLSearchParams({ page_data_id: pageDataId, page_code: pageCode });
  return apiRequest<PageDataRows>(`/api/data-assets/page-data/rows?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 15_000, tags: ["page-data", `page-data:${pageDataId}`] },
  });
}

export type PageDataWorkspace = {
  tenant_id: string;
  page_code: PageDataPageCode;
  assets: PageDataAsset[];
  layout: string[];
  notes: unknown[];
  rows: Record<string, PageDataRows>;
  row_errors: Record<string, string>;
};

const pageDataWorkspaceMemory = new Map<string, PageDataWorkspace>();

export function pageDataWorkspaceMemoryKey(tenantId: string, userId: string, pageCode: PageDataPageCode) {
  return `${tenantId}:${userId}:${pageCode}`;
}

export function readPageDataWorkspaceMemory(tenantId: string, userId: string, pageCode: PageDataPageCode) {
  return pageDataWorkspaceMemory.get(pageDataWorkspaceMemoryKey(tenantId, userId, pageCode)) || null;
}

export function writePageDataWorkspaceMemory(tenantId: string, userId: string, pageCode: PageDataPageCode, workspace: PageDataWorkspace) {
  pageDataWorkspaceMemory.set(pageDataWorkspaceMemoryKey(tenantId, userId, pageCode), workspace);
}

export async function fetchPageDataWorkspace({
  tenantId,
  userId = getDefaultUserId(),
  pageCode,
}: DataAssetParams & { pageCode: PageDataPageCode }) {
  const params = new URLSearchParams({ page_code: pageCode });
  const workspace = await apiRequest<PageDataWorkspace>(`/api/data-assets/page-data/workspace?${params.toString()}`, {
    method: "GET",
    context: { tenantId, userId },
    // Pointer/focus/down preloads and the route mount must share one governed
    // request. A short cache still revalidates changes promptly, while failed
    // reads are never cached by apiRequest.
    readCache: { ttlMs: 8_000, tags: ["page-data", `page-data-workspace:${pageCode}`] },
  });
  writePageDataWorkspaceMemory(tenantId, userId, pageCode, workspace);
  return workspace;
}

export async function fetchMultiInstitutionPageDataCandidates({
  tenantId,
  userId = getDefaultUserId(),
}: DataAssetParams) {
  return apiRequest<{
    tenant_id: string;
    candidates: MultiInstitutionPageDataCandidate[];
    count: number;
    relationship_required: true;
    source_read_only: true;
  }>("/api/data-assets/page-data/multi-institution-candidates", {
    method: "GET",
    context: { tenantId, userId },
    readCache: { ttlMs: 10_000, tags: ["data-assets", "page-data", "page-data:multi-institution-candidates"] },
  });
}

export async function fetchTableRelationshipCatalog({
  tenantId,
  userId = getDefaultUserId(),
}: DataAssetParams) {
  return apiRequest<TableRelationshipCatalog>("/api/data-assets/table-relationships/catalog", {
    method: "GET",
    context: { tenantId, userId },
    timeoutMs: 30_000,
    readCache: { ttlMs: 15_000, tags: ["data-assets", "table-relationships"] },
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

export async function updateRawTableExternalReference({
  tenantId,
  userId = getDefaultUserId(),
  sourceKey,
  mode,
  schemaFingerprint,
}: DataAssetParams & {
  sourceKey: string;
  mode: "private" | "shared";
  schemaFingerprint: string;
}): Promise<{ tenant_id: string; external_reference: { sourceKey: string; mode: "private" | "shared"; schemaFingerprint: string; updatedAt: string } }> {
  return apiRequest("/api/data-assets/raw-table/external-reference", {
    method: "POST",
    context: { tenantId, userId },
    body: { source_key: sourceKey, mode, schema_fingerprint: schemaFingerprint },
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
