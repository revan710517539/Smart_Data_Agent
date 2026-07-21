import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ClipboardEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  ChevronsDown,
  ChevronsUp,
  CheckCircle2,
  Download,
  FileText,
  Image as ImageIcon,
  MessageSquareText,
  MoreHorizontal,
  RefreshCcw,
  Save,
  Send,
  Sparkles,
  ThumbsUp,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePlatformContext } from "../../platform/PlatformContext";
import { fetchAnalysisTask, type BackendAnalysisResponse } from "../../services/analysisApi";
import { runApplicationAction } from "../../services/applicationApi";
import {
  analyzeWeeklyReportVersion,
  createReportComment,
  fetchReportComments,
  fetchSavedAnalysisResults,
  fetchWeeklyReportVersions,
  mutateReportComment,
  saveWeeklyReportVersion,
  type ReportComment,
  type SavedAnalysisResult as BackendSavedAnalysisResult,
  type WeeklyLearningTask,
} from "../../services/reportApi";
import { isDemoFallbackEnabled } from "../../services/apiContext";
import { fetchReportImageObjectUrl, uploadReportImage } from "../../services/reportAttachmentApi";

export type AnalysisStatus = "未生成" | "分析中" | "已停止" | "待确认" | "已确认";
export type ReportStatus = "待分析" | "已编辑" | "已完成";
export type CommentStatus = "open" | "resolved";
export type CommentResolvedReason = "manual" | "source_text_deleted" | "source_text_replaced";
export type CommentTargetKind = "paragraph" | "analysis" | "table" | "chart";

export type TableBlock = {
  id: string;
  type: "table";
  title: string;
  dataSource: string;
  updatedAt: string;
  fields: string[];
  rows: Record<string, string | number>[];
  analysisTaskId?: string;
  evidenceRef?: {
    verified?: boolean;
    reason?: string;
    analysis_task_id?: string;
    execution_id?: string;
    evidence_id?: string;
    evidence_hash?: string;
    rows_hash?: string;
    source_snapshot?: Record<string, unknown>;
    data_source?: string;
  };
  analysis: {
    status: AnalysisStatus;
    conclusion: string;
    contentItems?: RichContentItem[];
  };
};

export type TextBlock = {
  id: string;
  type: "text";
  title: string;
  content: string;
  contentItems: RichContentItem[];
};

export type ReportBlock = TableBlock | TextBlock;

export type RichContentItem =
  | {
      id: string;
      type: "paragraph";
      text: string;
    }
  | {
      id: string;
      type: "image";
      src: string;
      name: string;
      attachmentId?: string;
      artifactId?: string;
      contentHash?: string;
      width?: number;
      height?: number;
    };

export type ReportSection = {
  id: string;
  name: string;
  blocks: ReportBlock[];
};

export type ImageUploadContext = {
  tenantId: string;
  userId: string;
  reportId: string;
};

export type WeeklyInstitutionReport = {
  id: string;
  institutionName: string;
  projectNo: string;
  meetingTime: string;
  reporters: string;
  period: string;
  status: ReportStatus;
  owner: string;
  sections: ReportSection[];
};

export type CommentItem = {
  id: string;
  targetId: string;
  targetLabel: string;
  selectedText?: string;
  blockId?: string;
  itemId?: string;
  rangeStart?: number;
  rangeEnd?: number;
  anchorTop?: number;
  annotationKind?: "comment" | "analysis";
  status: CommentStatus;
  resolvedAt?: string;
  resolvedBy?: string;
  resolvedReason?: CommentResolvedReason;
  targetKind?: CommentTargetKind;
  author: string;
  time: string;
  text: string;
  replies: {
    id: string;
    author: string;
    time: string;
    text: string;
  }[];
};

export type CommentTarget = {
  id: string;
  contextTargetId?: string;
  label: string;
  type: "数据" | "图表" | "文本";
  targetKind: CommentTargetKind;
  selectedText?: string;
  blockId?: string;
  itemId?: string;
  rangeStart?: number;
  rangeEnd?: number;
  anchorTop?: number;
  anchorViewportTop?: number;
  annotationKind?: "comment" | "analysis";
};

export function makeAnalysisSelectionTarget(target: CommentTarget): CommentTarget {
  const hasTextRange = Boolean(target.selectedText?.trim())
    && typeof target.rangeStart === "number"
    && typeof target.rangeEnd === "number"
    && target.rangeEnd > target.rangeStart;
  if (!hasTextRange) return target;
  return {
    ...target,
    id: `${target.id}__analysis_${target.rangeStart}_${target.rangeEnd}`,
    contextTargetId: target.contextTargetId || target.id,
    annotationKind: "analysis",
  };
}

export type PendingTextSelection = {
  target: CommentTarget;
  top: number;
  left: number;
};

export type StoredVisualizationType = "table" | "column" | "bar" | "line" | "radar";
export type SavedAnalysisResult = {
  id: string;
  title: string;
  query: string;
  plan: string;
  summary: string;
  visualTypes: {
    primary: StoredVisualizationType;
    secondary: StoredVisualizationType;
  };
  savedAt: string;
  analysisTaskId: string;
  rows: {
    branch: string;
    amount: number;
    completion: string;
    conversion: string;
  }[];
};

export type WeeklyReportVersion = {
  id: string;
  name: string;
  savedAt: string;
  tenantId: string;
  reportId: string;
  report: WeeklyInstitutionReport;
};

export const savedAnalysisStorageKey = "smart_data_agent_saved_analysis_results";
export const reportCommentsStoragePrefix = "smart_data_agent_report_comments";
export const weeklyReportVersionsStoragePrefix = "smart_data_agent_weekly_report_versions";

export const reportPeriod = {
  name: "机构经营周报",
  period: getCurrentWorkweekPeriod(),
  status: "草稿",
};

export function makeId(prefix: string) {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

export function makeStableIdSegment(value: string | number) {
  const encoded = encodeURIComponent(String(value).trim())
    .replace(/%/g, "")
    .replace(/[^a-zA-Z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return encoded.slice(0, 64) || "item";
}

export function tableHeaderItemId(blockId: string, fieldIndex: number) {
  return `${blockId}_table_header_${fieldIndex}`;
}

export function tableCellItemId(blockId: string, rowIndex: number, fieldIndex: number) {
  return `${blockId}_table_cell_${rowIndex}_${fieldIndex}`;
}

export function chartAxisItemId(blockId: string, axis: "x" | "y", value: string | number) {
  return `${blockId}_trend_axis_${axis}_${makeStableIdSegment(value)}`;
}

export function chartLegendItemId(blockId: string, seriesName: string) {
  return `${blockId}_trend_legend_${makeStableIdSegment(seriesName)}`;
}

export function createTextItems(prefix: string, content: string): RichContentItem[] {
  const lines = content.split("\n");
  return (lines.length ? lines : [""]).map((line, index) => ({
    id: `${prefix}_line_${index}`,
    type: "paragraph",
    text: line,
  }));
}

export function createAnalysisContentItems(blockId: string, content: string): RichContentItem[] {
  const lines = content.split("\n");
  return (lines.length ? lines : [""]).map((line, index) => ({
    id: index === 0 ? `${blockId}_analysis_conclusion` : `${blockId}_analysis_conclusion_line_${index}`,
    type: "paragraph",
    text: line,
  }));
}

export function hasMeaningfulRichContent(items: RichContentItem[]) {
  return items.some((item) => (item.type === "image" ? Boolean(item.src) : Boolean(item.text.trim())));
}

export function clampImageWidth(value: number, maxWidth = 760) {
  return Math.max(120, Math.min(Math.round(value), maxWidth));
}

export function clampImageHeight(value: number, maxHeight = 520) {
  return Math.max(96, Math.min(Math.round(value), maxHeight));
}

export function makeTextBlock(id: string, title: string, content: string): TextBlock {
  return {
    id,
    type: "text",
    title,
    content,
    contentItems: createTextItems(id, content),
  };
}

export function serializeContentItems(items: RichContentItem[]) {
  return items
    .map((item) => (item.type === "paragraph" ? item.text : `[图片：${item.name}]`))
    .join("\n");
}

export function createWeeklyReports(selectedInstitution = "当前机构", currentUserId = ""): WeeklyInstitutionReport[] {
  const demoMode = isDemoFallbackEnabled();
  const makeTable = (
    reportId: string,
    id: string,
    title: string,
    dataSource: string,
    fields: string[],
    rows: Record<string, string | number>[],
    conclusion = "",
    retainStructure = false,
  ): TableBlock => ({
    id: `${reportId}_${id}`,
    type: "table",
    title,
    dataSource: demoMode ? `演示模板：${dataSource}` : retainStructure ? dataSource : "未绑定真实分析任务",
    updatedAt: demoMode ? "2026-07-03 09:30" : retainStructure ? "等待自动分析" : "尚未加载",
    fields,
    rows: demoMode || retainStructure ? rows : [],
    analysis: {
      status: demoMode && conclusion ? "待确认" : "未生成",
      conclusion: demoMode ? conclusion : "",
      contentItems: createAnalysisContentItems(`${reportId}_${id}`, demoMode ? conclusion : ""),
    },
  });

  const makeDraftTextBlock = (id: string, title: string, content: string) =>
    makeTextBlock(id, title, demoMode ? content : "");

  const makeReport = (
    id: string,
    institutionName: string,
    projectNo: string,
    status: ReportStatus,
    owner: string,
    balance: string,
    completion: string,
    weekChange: string,
  ): WeeklyInstitutionReport => ({
    id,
    institutionName,
    projectNo,
    meetingTime: demoMode ? "7月3日 周五" : "",
    reporters: demoMode ? owner : currentUserId,
    period: getCurrentWorkweekPeriod(),
    status,
    owner,
    sections: [
      {
        id: `${id}_performance`,
        name: "一、业绩与业务波动",
        blocks: [
          makeTable(
            id,
            "core_metrics",
            "核心指标表现",
            "经营周报三指标（固定数据源）",
            ["日期", "在贷余额", "放款金额", "新增余额"],
            demoMode
              ? [
                  { 日期: "第24周", 在贷余额: "11.54亿", 放款金额: "1.86亿", 新增余额: "+0.42亿" },
                  { 日期: "第25周", 在贷余额: "12.08亿", 放款金额: "2.12亿", 新增余额: "+0.54亿" },
                  { 日期: "第26周", 在贷余额: "12.60亿", 放款金额: "2.28亿", 新增余额: "+0.52亿" },
                  { 日期: "第27周", 在贷余额: balance || "13.42亿", 放款金额: "2.46亿", 新增余额: weekChange || "+0.82亿" },
                ]
              : [],
            demoMode ? `${institutionName}核心指标本周整体保持增长；在贷余额、放款金额和新增余额需结合周度趋势同步判断。` : "",
            true,
          ),
        ],
      },
      {
        id: `${id}_fluctuation`,
        name: "一、业绩与业务波动",
        blocks: [],
      },
      {
        id: `${id}_progress`,
        name: "二、重点事项及进展",
        blocks: [
          makeDraftTextBlock(
            `${id}_progress_text`,
            "重点事项说明",
            "1. 已完成本周重点客户清单复核，进入客户经理分层跟进阶段。\n2. 消费贷线上转化波动需补充渠道侧原因，经营贷本周重点关注续贷客户留存。\n3. 下周需要同步客户级推进结果和活动转化质量。",
          ),
        ],
      },
      {
        id: `${id}_branch`,
        name: "三、机构推动方面",
        blocks: [
          makeDraftTextBlock(
            `${id}_branch_text`,
            "机构推动说明",
            "机构推动侧已完成两轮名单分发，待补充客户经理触达频次、未转化原因和下周责任动作。",
          ),
        ],
      },
      {
        id: `${id}_next`,
        name: "四、下一步计划",
        blocks: [
          makeDraftTextBlock(
            `${id}_next_text`,
            "计划说明",
            "围绕余额缺口、重点客户、渠道转化三条线形成下周推进清单；周一补齐客户经理跟进结果，周三复核动支与风险变化。",
          ),
        ],
      },
    ],
  });

  if (!demoMode) {
    return [
      makeReport(
        `weekly_${makeStableIdSegment(selectedInstitution)}`,
        selectedInstitution || "当前机构",
        "经营周报",
        "待分析",
        currentUserId,
        "",
        "",
        "",
      ),
    ];
  }

  return [
    makeReport("shanghai", "上海分行", "经营周报", "已编辑", "陆凯亮、陈施恩", "13.42亿", "74.6%", "+0.82亿"),
    makeReport("beijing", "北京分行", "经营周报", "待分析", "王渊、赵晨", "12.18亿", "67.7%", "+0.46亿"),
    makeReport("shenzhen", "深圳分行", "经营周报", "已完成", "陈施恩", "11.95亿", "71.4%", "+0.63亿"),
    makeReport("hangzhou", "杭州分行", "经营周报", "已编辑", "赵晨", "10.86亿", "72.2%", "+0.51亿"),
  ];
}

export function formatNow() {
  return new Date().toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function formatDate(date: Date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function getCurrentWorkweekPeriod() {
  const now = new Date();
  const day = now.getDay();
  const mondayOffset = day === 0 ? -6 : 1 - day;
  const monday = new Date(now);
  monday.setDate(now.getDate() + mondayOffset);
  const friday = new Date(monday);
  friday.setDate(monday.getDate() + 4);
  return `${formatDate(monday)} ~ ${formatDate(friday)}`;
}

export function statusClass(status: string) {
  if (status === "已完成" || status === "已确认") {
    return "bg-[#eef8f1] text-[#34a853] border-[#d7efd9]";
  }
  if (status === "待分析" || status === "待确认") {
    return "bg-[#fff7e6] text-[#b26a00] border-[#ffe3aa]";
  }
  if (status === "分析中") {
    return "bg-[#eef4ff] text-[#0a66c2] border-[#d7e7ff]";
  }
  if (status === "已停止") {
    return "bg-[#fff7ed] text-[#b45309] border-[#fed7aa]";
  }
  if (status === "未生成") {
    return "bg-[#f2f2f7] text-[#8a8a8e] border-[#e5e5ea]";
  }
  return "bg-[#f5f7fb] text-[#3a3a3c] border-[#e5e5ea]";
}

export function loadSavedAnalysisResults(): SavedAnalysisResult[] {
  try {
    const raw = window.localStorage.getItem(savedAnalysisStorageKey);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed)
      ? sortSavedAnalysisResultsNewestFirst(parsed.map(normalizeSavedAnalysisResult))
      : [];
  } catch {
    return [];
  }
}

export function reportCommentsStorageKey(tenantId: string, reportId: string) {
  return `${reportCommentsStoragePrefix}_${tenantId}_${reportId}`;
}

export function loadLocalReportComments(tenantId: string, reportId: string): CommentItem[] {
  try {
    const raw = window.localStorage.getItem(reportCommentsStorageKey(tenantId, reportId));
    const parsed = raw ? JSON.parse(raw) : [];
    return normalizeComments(parsed);
  } catch {
    return [];
  }
}

export function saveLocalReportComments(tenantId: string, reportId: string, comments: CommentItem[]) {
  window.localStorage.setItem(reportCommentsStorageKey(tenantId, reportId), JSON.stringify(comments));
}

export function weeklyReportVersionsStorageKey(tenantId: string) {
  return `${weeklyReportVersionsStoragePrefix}_${tenantId}`;
}

export function cloneWeeklyReport(report: WeeklyInstitutionReport): WeeklyInstitutionReport {
  return JSON.parse(JSON.stringify(report)) as WeeklyInstitutionReport;
}

export function buildWeeklyReportVersionName(report: WeeklyInstitutionReport) {
  return `${report.institutionName}经营周报：${report.period}`;
}

export function loadLocalWeeklyReportVersions(tenantId: string): WeeklyReportVersion[] {
  try {
    const raw = window.localStorage.getItem(weeklyReportVersionsStorageKey(tenantId));
    const parsed = raw ? JSON.parse(raw) : [];
    return normalizeWeeklyReportVersions(parsed);
  } catch {
    return [];
  }
}

export function saveLocalWeeklyReportVersions(tenantId: string, versions: WeeklyReportVersion[]) {
  window.localStorage.setItem(weeklyReportVersionsStorageKey(tenantId), JSON.stringify(versions));
}

export function normalizeWeeklyReportVersions(value: unknown): WeeklyReportVersion[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((version): version is Record<string, unknown> => Boolean(version) && typeof version === "object")
    .map((version) => {
      const report = normalizeWeeklyReport(version.report);
      if (!report) return null;
      const reportId = typeof version.reportId === "string" ? version.reportId : report.id;
      return {
        id: String(version.id || makeId("weekly_version")),
        name: String(version.name || buildWeeklyReportVersionName(report)),
        savedAt: String(version.savedAt || "未记录"),
        tenantId: String(version.tenantId || "default"),
        reportId,
        report,
      } satisfies WeeklyReportVersion;
    })
    .filter((version): version is WeeklyReportVersion => Boolean(version));
}

export function weeklyLearningTaskMap(tasks: WeeklyLearningTask[]) {
  return tasks.reduce((items, task) => {
    if (task.version_id) items[task.version_id] = task;
    return items;
  }, {} as Record<string, WeeklyLearningTask>);
}

export function normalizeWeeklyReport(value: unknown): WeeklyInstitutionReport | null {
  if (!value || typeof value !== "object") return null;
  const report = value as Partial<WeeklyInstitutionReport>;
  if (!report.id || !report.institutionName || !Array.isArray(report.sections)) return null;
  return {
    id: String(report.id),
    institutionName: String(report.institutionName),
    projectNo: String(report.projectNo || "经营周报"),
    meetingTime: String(report.meetingTime || ""),
    reporters: String(report.reporters || ""),
    period: String(report.period || reportPeriod.period),
    status: report.status === "待分析" || report.status === "已完成" || report.status === "已编辑" ? report.status : "已编辑",
    owner: String(report.owner || report.reporters || ""),
    sections: report.sections.map((section) => ({
      id: String(section.id || makeId("section")),
      name: String(section.name || ""),
      blocks: Array.isArray(section.blocks)
        ? section.blocks
            .map((block) => normalizeReportBlock(block))
            .filter((block): block is ReportBlock => Boolean(block))
        : [],
    })),
  };
}

export function normalizeReportBlock(value: unknown): ReportBlock | null {
  if (!value || typeof value !== "object") return null;
  const block = value as Partial<ReportBlock>;
  if (block.type === "table") {
    return {
      id: String(block.id || makeId("table")),
      type: "table",
      title: String(block.title || ""),
      dataSource: String(block.dataSource || ""),
      updatedAt: String(block.updatedAt || formatNow()),
      fields: Array.isArray(block.fields) ? block.fields.map(String) : [],
      rows: Array.isArray(block.rows)
        ? block.rows
            .filter((row): row is Record<string, string | number> => Boolean(row) && typeof row === "object")
            .map((row) => ({ ...row }))
        : [],
      analysisTaskId: typeof block.analysisTaskId === "string" ? block.analysisTaskId : undefined,
      evidenceRef:
        block.evidenceRef && typeof block.evidenceRef === "object"
          ? { ...(block.evidenceRef as TableBlock["evidenceRef"]) }
          : undefined,
      analysis: {
        status:
          block.analysis?.status === "已确认" || block.analysis?.status === "待确认" || block.analysis?.status === "未生成" || block.analysis?.status === "分析中" || block.analysis?.status === "已停止"
            ? block.analysis.status
            : "未生成",
        conclusion: String(block.analysis?.conclusion || ""),
        contentItems: Array.isArray(block.analysis?.contentItems)
          ? normalizeContentItems(`${block.id || makeId("table")}_analysis`, block.analysis.contentItems)
          : createAnalysisContentItems(String(block.id || makeId("table")), String(block.analysis?.conclusion || "")),
      },
    };
  }
  if (block.type === "text") {
    const contentItems = Array.isArray(block.contentItems)
      ? normalizeContentItems(block.id || makeId("text"), block.contentItems)
      : createTextItems(String(block.id || makeId("text")), String(block.content || ""));
    return {
      id: String(block.id || makeId("text")),
      type: "text",
      title: String(block.title || ""),
      content: String(block.content || serializeContentItems(contentItems)),
      contentItems,
    };
  }
  return null;
}

export function normalizeContentItems(prefix: string, value: unknown[]): RichContentItem[] {
  const items = value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item, index) => {
      if (item.type === "image") {
        const rawSrc = String(item.src || "");
        return {
          id: String(item.id || `${prefix}_image_${index}`),
          type: "image" as const,
          src: !isDemoFallbackEnabled() && rawSrc.startsWith("data:") ? "" : rawSrc,
          name: String(item.name || "图片"),
          attachmentId: typeof item.attachmentId === "string" ? item.attachmentId : undefined,
          artifactId: typeof item.artifactId === "string" ? item.artifactId : undefined,
          contentHash: typeof item.contentHash === "string" ? item.contentHash : undefined,
          width: typeof item.width === "number" ? clampImageWidth(item.width) : undefined,
          height: typeof item.height === "number" ? clampImageHeight(item.height) : undefined,
        };
      }
      return {
        id: String(item.id || `${prefix}_line_${index}`),
        type: "paragraph" as const,
        text: String(item.text || ""),
      };
    });
  return items.length ? items : createTextItems(prefix, "");
}

export function normalizeComments(value: unknown): CommentItem[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((comment): comment is Record<string, unknown> => Boolean(comment) && typeof comment === "object")
    .map((comment) => ({
      id: String(comment.id || ""),
      targetId: String(comment.targetId || ""),
      targetLabel: String(comment.targetLabel || ""),
      selectedText: typeof comment.selectedText === "string" ? comment.selectedText : undefined,
      blockId: typeof comment.blockId === "string" ? comment.blockId : undefined,
      itemId: typeof comment.itemId === "string" ? comment.itemId : undefined,
      rangeStart: typeof comment.rangeStart === "number" ? comment.rangeStart : undefined,
      rangeEnd: typeof comment.rangeEnd === "number" ? comment.rangeEnd : undefined,
      anchorTop: typeof comment.anchorTop === "number" ? comment.anchorTop : undefined,
      status: normalizeCommentStatus(comment.status),
      resolvedAt: typeof comment.resolvedAt === "string" ? comment.resolvedAt : undefined,
      resolvedBy: typeof comment.resolvedBy === "string" ? comment.resolvedBy : undefined,
      resolvedReason: normalizeResolvedReason(comment.resolvedReason),
      targetKind: inferCommentTargetKind(comment),
      author: String(comment.author || "当前用户"),
      time: String(comment.time || ""),
      text: String(comment.text || ""),
      replies: normalizeReplies(comment.replies),
    }))
    .filter((comment) => Boolean(comment.id && comment.targetId && comment.text));
}

const contextFieldLabels: Record<string, string> = {
  bank: "分行",
  month: "月份",
  metric: "指标",
  consumer: "消费贷",
  business: "经营贷",
  cLoan: "消费贷放款",
  cDrawdown: "消费贷动支率",
  cM1: "消费贷M1逾期率",
  cBalance: "消费贷余额",
  bLoan: "经营贷放款",
  bDrawdown: "经营贷动支率",
  bM1: "经营贷M1逾期率",
  bBalance: "经营贷余额",
};

export function readableContextText(value: unknown, fallback = "对选中区域添加评论", maxLength = 360) {
  if (typeof value !== "string") return compactContextText(summarizeContextValue(value), fallback, maxLength);
  const normalized = value.trim();
  if (!normalized) return fallback;
  if (!normalized.startsWith("[") && !normalized.startsWith("{")) {
    return compactContextText(normalized, fallback, maxLength);
  }
  try {
    return compactContextText(summarizeContextValue(JSON.parse(normalized)), fallback, maxLength);
  } catch {
    return compactContextText(normalized, fallback, maxLength);
  }
}

export function summarizeContextValue(value: unknown, maxLength = 1200) {
  return compactContextText(summarizeContextNode(value), "当前选中内容", maxLength);
}

function summarizeContextNode(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    if (!value.length) return "暂无数据";
    const items = value.slice(0, 12).map((item) => summarizeContextNode(item)).filter(Boolean);
    return `${items.join("；")}${value.length > items.length ? `；另有 ${value.length - items.length} 项` : ""}`;
  }
  if (typeof value !== "object") return String(value);

  const record = value as Record<string, unknown>;
  if (typeof record.label === "string" && record.value !== undefined) {
    const change = record.change === undefined || record.change === "" ? "" : `（${String(record.change)}）`;
    return `${record.label}：${summarizeContextNode(record.value)}${change}`;
  }
  return Object.entries(record)
    .filter(([key]) => key !== "positive")
    .slice(0, 12)
    .map(([key, item]) => `${contextFieldLabels[key] || key}：${summarizeContextNode(item)}`)
    .join("，");
}

function compactContextText(value: string, fallback: string, maxLength: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (!normalized) return fallback;
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(1, maxLength - 1)).trimEnd()}…`;
}

export function normalizeCommentStatus(value: unknown): CommentStatus {
  return value === "resolved" ? "resolved" : "open";
}

export function normalizeResolvedReason(value: unknown): CommentResolvedReason | undefined {
  return value === "manual" || value === "source_text_deleted" || value === "source_text_replaced" ? value : undefined;
}

export function normalizeTargetKind(value: unknown): CommentTargetKind | undefined {
  return value === "paragraph" || value === "analysis" || value === "table" || value === "chart" ? value : undefined;
}

export function inferCommentTargetKind(comment: Record<string, unknown>): CommentTargetKind | undefined {
  const explicit = normalizeTargetKind(comment.targetKind);
  if (explicit) return explicit;
  const targetId = String(comment.targetId || "");
  const itemId = String(comment.itemId || "");
  if (targetId.includes("_analysis_text") || itemId.includes("_analysis_conclusion")) return "analysis";
  if (targetId.endsWith("_trend")) return "chart";
  if (targetId.endsWith("_data")) return "table";
  if (itemId || targetId.includes("_selection") || targetId.endsWith("_text")) return "paragraph";
  return undefined;
}

export function inferCommentItemTargetKind(comment: CommentItem): CommentTargetKind | undefined {
  return inferCommentTargetKind(comment as unknown as Record<string, unknown>);
}

export function normalizeReplies(value: unknown): CommentItem["replies"] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((reply): reply is Record<string, unknown> => Boolean(reply) && typeof reply === "object")
    .map((reply) => ({
      id: String(reply.id || ""),
      author: String(reply.author || "当前用户"),
      time: String(reply.time || ""),
      text: String(reply.text || ""),
    }))
    .filter((reply) => Boolean(reply.id && reply.text));
}

export function normalizeSavedAnalysisResult(result: BackendSavedAnalysisResult | SavedAnalysisResult): SavedAnalysisResult {
  const visualTypes = result.visualTypes || { primary: "bar", secondary: "table" };
  return {
    id: String(result.id || ""),
    title: String(result.title || result.query || "未命名分析结果"),
    query: String(result.query || result.title || ""),
    plan: String(result.plan || ""),
    summary: String(result.summary || ""),
    visualTypes: {
      primary: normalizeStoredVisualizationType(visualTypes.primary),
      secondary: normalizeStoredVisualizationType(visualTypes.secondary),
    },
    savedAt: String(result.savedAt || "未记录"),
    analysisTaskId: String(result.analysisTaskId || ""),
    rows: normalizeSavedAnalysisRows(result.rows),
  };
}

export function sortSavedAnalysisResultsNewestFirst(results: SavedAnalysisResult[]) {
  return [...results].sort((left, right) => savedAnalysisTimestamp(right.savedAt) - savedAnalysisTimestamp(left.savedAt));
}

export function formatSavedAnalysisOptionLabel(result: SavedAnalysisResult) {
  const savedAt = parseSavedAnalysisDate(result.savedAt);
  const dateTime = savedAt
    ? `${savedAt.getFullYear()}-${padDatePart(savedAt.getMonth() + 1)}-${padDatePart(savedAt.getDate())}：${padDatePart(savedAt.getHours())}:${padDatePart(savedAt.getMinutes())}`
    : "时间未记录";
  const question = String(result.query || result.title || "未命名分析问题").replace(/\s+/g, " ").trim();
  const characters = Array.from(question);
  const summary = characters.length > 20 ? `${characters.slice(0, 20).join("")}…` : question;
  return `${dateTime}\u00a0\u00a0\u00a0${summary}`;
}

function savedAnalysisTimestamp(value: string) {
  return parseSavedAnalysisDate(value)?.getTime() ?? 0;
}

function parseSavedAnalysisDate(value: string) {
  const source = String(value || "").trim();
  if (!source) return null;
  if (/(?:Z|[+-]\d{2}:?\d{2})$/i.test(source)) {
    const timestamp = Date.parse(source);
    return Number.isFinite(timestamp) ? new Date(timestamp) : null;
  }
  const match = source.match(/^(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?:[T\s]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/);
  if (!match) {
    const timestamp = Date.parse(source);
    return Number.isFinite(timestamp) ? new Date(timestamp) : null;
  }
  const [, year, month, day, hour = "0", minute = "0", second = "0"] = match;
  const parsed = new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function padDatePart(value: number) {
  return String(value).padStart(2, "0");
}

export function normalizeStoredVisualizationType(value: unknown): StoredVisualizationType {
  return value === "table" || value === "column" || value === "bar" || value === "line" || value === "radar"
    ? value
    : "bar";
}

export function normalizeSavedAnalysisRows(rows: unknown): SavedAnalysisResult["rows"] {
  if (!Array.isArray(rows)) return [];
  return rows
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object")
    .map((row, index) => ({
      branch: String(row.branch ?? row.branch_name ?? row.productLine ?? row.product_line ?? `维度${index + 1}`),
      amount: Number(row.amount ?? row.metric_value ?? 0),
      completion: String(row.completion ?? "—"),
      conversion: String(row.conversion ?? "—"),
    }));
}

export type PublishableAnalysisMaterial = {
  rows: Record<string, string | number>[];
  fields: string[];
  conclusion: string;
  dataSource: string;
  updatedAt: string;
  evidence: NonNullable<BackendAnalysisResponse["skill_results"]>[number]["evidence"];
};

export function extractPublishableAnalysisMaterial(task: BackendAnalysisResponse): PublishableAnalysisMaterial {
  const review = task.review && typeof task.review === "object" ? task.review : {};
  if (task.status !== "completed" || review.status !== "passed" || review.publication_gate !== "allowed") {
    throw new Error("该分析任务尚未完成服务端复核，不能载入经营周报");
  }
  const result = task.skill_results?.[0];
  if (!result) throw new Error("该分析任务没有可用执行结果");
  const semantic = result.semantic_info && typeof result.semantic_info === "object" ? result.semantic_info : {};
  if (semantic.execution_mode !== "real" || semantic.publishable !== true) {
    throw new Error("该分析结果不是已验证的真实数据，不能用于经营汇报");
  }
  const evidence = result.evidence;
  const sourceSnapshot = evidence?.source_snapshot;
  if (!evidence?.evidence_id || !sourceSnapshot || !Object.keys(sourceSnapshot).length) {
    throw new Error("该分析结果缺少证据编号或数据快照，不能用于经营汇报");
  }
  if (!Array.isArray(result.data) || !result.data.length) {
    throw new Error("该分析任务没有返回数据行");
  }
  const rows: Record<string, string | number>[] = result.data.map((rawRow) => {
    if (!rawRow || typeof rawRow !== "object" || Array.isArray(rawRow)) {
      throw new Error("分析结果包含不支持的数据行");
    }
    const row: Record<string, string | number> = {};
    Object.entries(rawRow).forEach(([field, value]) => {
      if (typeof value !== "string" && typeof value !== "number") {
        throw new Error(`字段“${field}”包含周报表格暂不支持的值类型`);
      }
      row[field] = value;
    });
    return row;
  });
  const fields = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  if (!fields.length) throw new Error("分析结果没有可展示字段");
  const intelligentConclusions = task.intelligent_analysis?.possible_conclusions?.filter(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  );
  const resultConclusions = result.intelligent_analysis?.possible_conclusions?.filter(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  );
  const reviewedConclusions = intelligentConclusions?.length
    ? intelligentConclusions
    : resultConclusions?.length
      ? resultConclusions
      : (task.conclusions || []).filter((item) => typeof item === "string" && Boolean(item.trim()));
  const snapshotTime = String(
    sourceSnapshot.observed_at || sourceSnapshot.snapshot_at || sourceSnapshot.watermark_at || "",
  ).trim();
  return {
    rows,
    fields,
    conclusion: reviewedConclusions.join("\n"),
    dataSource: String(evidence.data_source || semantic.data_source || "已验证分析任务"),
    updatedAt: snapshotTime || "已绑定服务端数据快照",
    evidence,
  };
}

export function extractCoreWeeklyAnalysisMaterial(task: BackendAnalysisResponse): PublishableAnalysisMaterial {
  const result = task.skill_results?.[0];
  if (!result || !Array.isArray(result.data) || !result.data.length) {
    throw new Error("核心指标分析没有返回可展示的数据行");
  }
  const rows = result.data
    .filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === "object" && !Array.isArray(row))
    .map((row) => ({
      日期: String(row.stat_week || row.month || "—"),
      在贷余额: formatCoreMetricAmount(row.loan_balance),
      放款金额: formatCoreMetricAmount(row.loan_amount),
      新增余额: formatCoreMetricAmount(row.new_balance),
    }))
    .sort((left, right) => String(left.日期).localeCompare(String(right.日期)));
  const possibleConclusions = task.intelligent_analysis?.possible_conclusions?.filter(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  ) || result.intelligent_analysis?.possible_conclusions?.filter(
    (item): item is string => typeof item === "string" && Boolean(item.trim()),
  ) || (task.conclusions || []).filter((item): item is string => typeof item === "string" && Boolean(item.trim()));
  const semantic = result.semantic_info && typeof result.semantic_info === "object" ? result.semantic_info : {};
  const snapshot = result.evidence?.source_snapshot;
  return {
    rows,
    fields: ["日期", "在贷余额", "放款金额", "新增余额"],
    conclusion: possibleConclusions.join("\n"),
    dataSource: String(result.evidence?.data_source || semantic.data_source || "weekly_core_metrics_mart"),
    updatedAt: String(snapshot?.observed_at || snapshot?.snapshot_at || snapshot?.watermark_at || formatNow()),
    evidence: result.evidence,
  };
}

function formatCoreMetricAmount(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  return Number.isFinite(numeric) ? `${(numeric / 100_000_000).toFixed(2)}亿` : "—";
}

export function visualizationLabel(type: StoredVisualizationType) {
  const labels: Record<StoredVisualizationType, string> = {
    table: "表格",
    column: "柱状图",
    bar: "条形图",
    line: "趋势图",
    radar: "雷达图",
  };
  return labels[type];
}
