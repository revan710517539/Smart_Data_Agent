import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, LoaderCircle, ShieldCheck } from "lucide-react";
import { usePlatformContext } from "../../platform/PlatformContext";
import { apiErrorMessage } from "../../services/apiClient";
import { fetchTrustedArtifactManifest, type TrustedArtifactManifest } from "../../services/analysisWorkspaceApi";

export function TrustedArtifactPanel({ taskId, compact = false }: { taskId?: string; compact?: boolean }) {
  const { tenantId, userId } = usePlatformContext();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [manifest, setManifest] = useState<TrustedArtifactManifest>();
  const [error, setError] = useState("");

  useEffect(() => {
    setOpen(false);
    setLoading(false);
    setManifest(undefined);
    setError("");
  }, [taskId, tenantId, userId]);

  if (!taskId) return null;

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (manifest || loading) return;
    setLoading(true);
    setError("");
    try {
      const result = await fetchTrustedArtifactManifest(taskId, { tenantId, userId });
      setManifest(result.manifest);
    } catch (requestError) {
      setError(apiErrorMessage(requestError, "可信证据加载失败。"));
    } finally {
      setLoading(false);
    }
  };

  const snapshot = objectValue(manifest?.dataset_snapshot);
  return (
    <div className={`${compact ? "mt-2" : "mt-4"} rounded-lg border border-[#e5e5ea] bg-white`} data-trusted-artifact-panel="true">
      <button type="button" onClick={() => void toggle()} className="flex w-full items-center gap-1.5 px-3 py-2 text-left text-[10px] text-[#636366] hover:bg-[#fafbfc]" aria-expanded={open}>
        <ShieldCheck className="h-3.5 w-3.5 text-[#8a8a8e]" />
        <span className="flex-1">数据口径 / 证据</span>
        <span className="max-w-[140px] truncate font-mono text-[9px] text-[#aeaeb2]">{taskId}</span>
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open ? (
        <div className="border-t border-[#f0f0f2] px-3 py-2.5 text-[9px] leading-4 text-[#8a8a8e]">
          {loading ? <div className="flex items-center gap-1.5"><LoaderCircle className="h-3 w-3 animate-spin" />正在校验可信清单…</div> : null}
          {error ? <div role="alert" className="text-[#b42318]">{error}</div> : null}
          {manifest ? (
            <div className="grid gap-x-3 gap-y-1 sm:grid-cols-2">
              <EvidenceValue label="数据版本" value={String(snapshot.version || snapshot.asset_version || snapshot.content_hash || "未记录")} />
              <EvidenceValue label="Schema" value={String(snapshot.schema_fingerprint || "未记录")} />
              <EvidenceValue label="指标版本" value={manifest.metric_versions.length ? manifest.metric_versions.map(versionLabel).join("、") : "未绑定"} />
              <EvidenceValue label="模型版本" value={manifest.model_version || "服务端默认"} />
              <EvidenceValue label="SQL 哈希" value={manifest.sql_hash} />
              <EvidenceValue label="结果哈希" value={manifest.result_hash} />
              <div className="sm:col-span-2"><EvidenceValue label="清单哈希" value={manifest.manifest_hash} /></div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function EvidenceValue({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><span className="text-[#aeaeb2]">{label}：</span><span className="break-all font-mono text-[#636366]">{shortHash(value)}</span></div>;
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function versionLabel(value: Record<string, unknown>) {
  return String(value.metric_id || value.metricId || value.metric_code || value.version || "已绑定");
}

function shortHash(value: string) {
  return /^[a-f0-9]{64}$/i.test(value) ? `${value.slice(0, 12)}…${value.slice(-6)}` : value;
}
