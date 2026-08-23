import { apiRequest } from "./apiClient";
import { getDefaultUserId } from "./apiContext";
import type { ApplicationModuleResponse } from "./applicationApi";

export type CustomerSegmentListPreview = {
  file_name: string;
  content_hash: string;
  customer_count: number;
  duplicate_count: number;
  blank_count: number;
  other_columns_ignored: boolean;
  valid: true;
};

export type CustomerSegmentListMetadata = {
  artifactId: string;
  ownerUserId: string;
  contentHash: string;
  sourceContentHash: string;
  fileName: string;
  customerCount: number;
  duplicateCount: number;
  blankCount: number;
  confirmedAt: string;
};

export async function previewCustomerSegmentList({
  tenantId,
  userId = getDefaultUserId(),
  file,
}: {
  tenantId: string;
  userId?: string;
  file: File;
}) {
  return apiRequest<{ tenant_id: string; preview: CustomerSegmentListPreview }>("/api/customer-segment/list/preview", {
    method: "POST",
    context: { tenantId, userId },
    body: { file_name: file.name, content_base64: await fileToBase64(file) },
  });
}

export async function confirmCustomerSegmentList({
  tenantId,
  userId = getDefaultUserId(),
  file,
  expectedContentHash,
}: {
  tenantId: string;
  userId?: string;
  file: File;
  expectedContentHash: string;
}) {
  return apiRequest<{
    tenant_id: string;
    customer_list: CustomerSegmentListMetadata;
    module: ApplicationModuleResponse<{ customerSegmentList?: CustomerSegmentListMetadata | null }>;
  }>("/api/customer-segment/list/confirm", {
    method: "POST",
    context: { tenantId, userId },
    body: {
      file_name: file.name,
      content_base64: await fileToBase64(file),
      expected_content_hash: expectedContentHash,
    },
  });
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = typeof reader.result === "string" ? reader.result : "";
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("customer_segment_file_read_failed"));
    reader.readAsDataURL(file);
  });
}
