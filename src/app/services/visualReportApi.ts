import type { RawField } from "./dataAssetApi";
import { fetchApplicationModule, runApplicationAction } from "./applicationApi";
import type { VisualizationType } from "../components/self-analysis/domain";
import type { VisualizationCardConfig } from "../components/visualization/visualizationDataModel";
import type { StickyNoteRecord } from "../components/notes/richNote";

export type VisualReportDestination = "mine" | "topic" | "experience" | "weekly";

export type VisualReportDatasetReference = {
  id: string;
  kind: "raw" | "topic" | "page_data";
  name: string;
  code: string;
  sourceKey?: string;
  schemaFingerprint?: string;
  relationshipGroupId?: string;
  fields: RawField[];
};

export type VisualReportCard = {
  id: string;
  title: string;
  type: VisualizationType;
  dataset: VisualReportDatasetReference;
  config: VisualizationCardConfig;
};

export type VisualReport = {
  id: string;
  title: string;
  cards: VisualReportCard[];
  destinations: VisualReportDestination[];
  stickyNote?: StickyNoteRecord;
  ownerUserId?: string;
  createdAt: string;
  updatedAt: string;
};

type VisualReportState = { visualReports?: VisualReport[] };

type VisualReportParams = {
  tenantId: string;
  userId: string;
};

export async function fetchVisualReports({ tenantId, userId }: VisualReportParams) {
  const response = await fetchApplicationModule<VisualReportState>({ tenantId, userId, moduleKey: "self_analysis" });
  return Array.isArray(response.state.visualReports) ? response.state.visualReports : [];
}

export async function upsertVisualReport({ tenantId, userId, report }: VisualReportParams & { report: VisualReport }) {
  const response = await runApplicationAction<VisualReportState>({
    tenantId,
    userId,
    moduleKey: "self_analysis",
    action: "upsert_visual_report",
    payload: { report },
  });
  return response.result.report as VisualReport;
}

export async function deleteVisualReport({ tenantId, userId, reportId }: VisualReportParams & { reportId: string }) {
  await runApplicationAction<VisualReportState>({
    tenantId,
    userId,
    moduleKey: "self_analysis",
    action: "delete_visual_report",
    payload: { reportId },
  });
}
