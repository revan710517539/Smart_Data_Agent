import { apiRequest, getApiBaseUrl } from "./apiClient";
import { apiContextHeaders, getDefaultTenantId, getDefaultUserId } from "./apiContext";

type UploadReportImageResponse = {
  status: string;
  attachment: {
    attachment_id: string;
    artifact_id: string;
    file_name: string;
  };
  artifact: {
    artifact_id: string;
    content_hash: string;
    content_type: string;
    size_bytes: number;
  };
  content_url: string;
};

export async function uploadReportImage({
  file,
  reportId,
  blockId,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: {
  file: File;
  reportId: string;
  blockId: string;
  tenantId?: string;
  userId?: string;
}): Promise<UploadReportImageResponse & { absoluteContentUrl: string }> {
  const contentBase64 = await fileToBase64(file);
  const response = await apiRequest<UploadReportImageResponse>("/api/attachments/image", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      file_name: file.name || "pasted-image",
      content_base64: contentBase64,
      report_id: reportId,
      block_id: blockId,
      classification: "internal",
    },
    timeoutMs: 60_000,
  });
  if (response.status !== "ready") throw new Error("图片未通过安全扫描，不能写入周报");
  return {
    ...response,
    absoluteContentUrl: `${getApiBaseUrl()}${response.content_url}`,
  };
}

export async function fetchReportImageObjectUrl({
  attachmentId,
  tenantId = getDefaultTenantId(),
  userId = getDefaultUserId(),
}: {
  attachmentId: string;
  tenantId?: string;
  userId?: string;
}) {
  const params = new URLSearchParams({ attachment_id: attachmentId });
  const response = await fetch(`${getApiBaseUrl()}/api/attachments/content?${params.toString()}`, {
    method: "GET",
    credentials: "include",
    headers: apiContextHeaders({ tenantId, userId }),
  });
  if (!response.ok) throw new Error("report_image_download_failed");
  return URL.createObjectURL(await response.blob());
}

function fileToBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const value = String(reader.result || "");
      const separator = value.indexOf(",");
      if (separator < 0) {
        reject(new Error("image_base64_encode_failed"));
        return;
      }
      resolve(value.slice(separator + 1));
    };
    reader.onerror = () => reject(reader.error || new Error("image_read_failed"));
    reader.readAsDataURL(file);
  });
}
