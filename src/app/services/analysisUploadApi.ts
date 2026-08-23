import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";

export type UploadedAnalysisClassification = "data_source" | "text_document" | "unsupported_media";

export type UploadedAnalysisSource = {
  classification: UploadedAnalysisClassification;
  message: string;
  file_name: string;
  content_type: string;
  content_hash: string;
  extracted_text: string;
  table?: Record<string, unknown>;
  row_count?: number;
};

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("analysis_upload_read_failed"));
    reader.onload = () => {
      const result = String(reader.result || "");
      const separator = result.indexOf(",");
      if (separator < 0) {
        reject(new Error("analysis_upload_read_failed"));
        return;
      }
      resolve(result.slice(separator + 1));
    };
    reader.readAsDataURL(file);
  });
}

export async function classifyAnalysisUpload({
  tenantId,
  userId = getDefaultUserId(),
  file,
}: {
  tenantId: string;
  userId?: string;
  file: File;
}): Promise<{ tenant_id: string; source: UploadedAnalysisSource }> {
  const contentBase64 = await fileToBase64(file);
  return apiRequest<{ tenant_id: string; source: UploadedAnalysisSource }>("/api/analysis/uploaded-source", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      file_name: file.name,
      content_type: file.type,
      content_base64: contentBase64,
    },
  });
}
