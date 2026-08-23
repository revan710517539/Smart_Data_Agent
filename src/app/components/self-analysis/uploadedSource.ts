import type { KnowledgeFileAttachment } from "./domain";
import { detectAttachmentInstitutions, readKnowledgeAttachment } from "./domain";
import { classifyAnalysisUpload } from "../../services/analysisUploadApi";

export const UPLOADED_MEDIA_UNSUPPORTED_MESSAGE = "暂不支持视频、语音类文件。";

const MEDIA_SUFFIX = /\.(mp4|mov|avi|mkv|webm|mpeg|mpg|wmv|flv|m4v|3gp|mp3|wav|aac|flac|ogg|m4a|wma|aiff|opus|amr|weba)$/i;

export function classifyLocalUpload(file: File): "data_source" | "text_document" | "unsupported_media" {
  const name = file.name || "";
  const type = (file.type || "").toLowerCase();
  if (MEDIA_SUFFIX.test(name) || type.startsWith("video/") || type.startsWith("audio/")) return "unsupported_media";
  if (/\.(xlsx|csv|tsv|json)$/i.test(name) || type.includes("spreadsheet") || type === "text/csv" || type === "application/json") return "data_source";
  return "text_document";
}

export function uploadedAnalysisGate(files: KnowledgeFileAttachment[]) {
  const dataFiles = files.filter((file) => file.classification === "data_source" && file.parsedTable);
  const textFiles = files.filter((file) => file.classification === "text_document");
  const mediaFiles = files.filter((file) => file.classification === "unsupported_media");
  return {
    hasDataSource: dataFiles.length > 0,
    hasTextDocument: textFiles.length > 0,
    mediaOnly: mediaFiles.length > 0 && dataFiles.length === 0 && textFiles.length === 0,
    dataFiles,
    textFiles,
  };
}

export function uploadedTablesFromFiles(files: KnowledgeFileAttachment[]) {
  return files
    .map((file) => file.parsedTable)
    .filter((table): table is Record<string, unknown> => Boolean(table) && typeof table === "object");
}

export async function ingestAnalysisUploads(
  files: File[],
  options: { tenantId: string; userId: string },
): Promise<{ accepted: KnowledgeFileAttachment[]; rejectedMessage: string }> {
  const accepted: KnowledgeFileAttachment[] = [];
  let rejectedMessage = "";
  for (const file of files) {
    if (classifyLocalUpload(file) === "unsupported_media") {
      rejectedMessage = UPLOADED_MEDIA_UNSUPPORTED_MESSAGE;
      continue;
    }
    const local = await readKnowledgeAttachment(file);
    try {
      const classified = await classifyAnalysisUpload({
        tenantId: options.tenantId,
        userId: options.userId,
        file,
      });
      const source = classified.source;
      if (source.classification === "unsupported_media") {
        rejectedMessage = source.message || UPLOADED_MEDIA_UNSUPPORTED_MESSAGE;
        continue;
      }
      accepted.push({
        ...local,
        classification: source.classification,
        classifyMessage: source.message,
        extractedText: source.extracted_text,
        contentHash: source.content_hash,
        parsedTable: source.table,
        contentPreview: source.extracted_text || local.contentPreview,
        detectedInstitutions: detectAttachmentInstitutions(local.name, source.extracted_text || local.contentPreview || ""),
      });
    } catch (error) {
      if (classifyLocalUpload(file) === "data_source") {
        rejectedMessage = error instanceof Error ? error.message : "无法识别该上传文件。";
        continue;
      }
      accepted.push({
        ...local,
        classification: "text_document",
        extractedText: local.contentPreview,
      });
    }
  }
  return { accepted, rejectedMessage };
}
