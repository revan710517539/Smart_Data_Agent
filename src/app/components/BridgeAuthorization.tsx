import { useEffect, useMemo, useState } from "react";
import { Check, Link2, ShieldCheck } from "lucide-react";
import { useSearchParams } from "react-router";
import { usePlatformContext } from "../platform/PlatformContext";
import {
  approveBridgeEnrollment,
  fetchBridgeEnrollmentPreview,
  type BridgeEnrollmentPreview,
} from "../services/bridgeApi";
import { apiErrorMessage } from "../services/apiClient";

const channelLabels: Record<string, string> = {
  workbuddy: "WorkBuddy",
  codex: "Codex",
  qwork: "QWork",
};

export function BridgeAuthorization() {
  const [searchParams] = useSearchParams();
  const { selectedInstitution } = usePlatformContext();
  const userCode = useMemo(() => (searchParams.get("user_code") || "").trim().toUpperCase(), [searchParams]);
  const [preview, setPreview] = useState<BridgeEnrollmentPreview | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "approving" | "approved" | "failed">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    if (!userCode) {
      setStatus("failed");
      setMessage("授权链接缺少设备授权码，请重新运行接入文档。");
      return () => undefined;
    }
    setStatus("loading");
    void fetchBridgeEnrollmentPreview(userCode)
      .then((result) => {
        if (cancelled) return;
        setPreview(result);
        setStatus(result.status === "approved" ? "approved" : "ready");
        setMessage(result.status === "approved" ? "此设备已获批准，可以关闭页面。" : "");
      })
      .catch((error) => {
        if (cancelled) return;
        setStatus("failed");
        setMessage(apiErrorMessage(error, "授权码无效或已经过期，请重新运行接入文档。"));
      });
    return () => {
      cancelled = true;
    };
  }, [userCode]);

  const approve = async () => {
    if (!preview || status !== "ready") return;
    setStatus("approving");
    setMessage("");
    try {
      await approveBridgeEnrollment(userCode);
      setStatus("approved");
      setMessage("连接已批准。CLI 会自动完成绑定，可以关闭此页面。 ");
    } catch (error) {
      setStatus("failed");
      setMessage(apiErrorMessage(error, "设备授权失败，请确认当前账号和机构后重试。"));
    }
  };

  const label = channelLabels[preview?.channel || ""] || "Bridge";
  return (
    <div className="mx-auto flex min-h-[calc(100vh-120px)] max-w-[620px] items-center px-5 py-10">
      <section className="w-full rounded-2xl border border-[#e7e8eb] bg-white p-7 shadow-[0_18px_55px_rgba(0,0,0,0.06)]">
        <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-[#f2f3f5] text-[#17181a]">
          {status === "approved" ? <Check className="h-5 w-5" /> : <Link2 className="h-5 w-5" />}
        </div>
        <h1 className="text-xl font-semibold text-[#17181a]">授权 {label} 连接 Smart Data Agent</h1>
        <p className="mt-2 text-sm leading-6 text-[#686b72]">
          连接后只能读取你明确设为“可分享”的原始表，并可回传报告及待复核分析材料。
        </p>

        <dl className="my-6 grid gap-3 rounded-xl bg-[#f7f7f8] p-4 text-sm">
          <div className="flex items-center justify-between gap-4"><dt className="text-[#777a81]">当前机构</dt><dd className="font-medium text-[#222327]">{selectedInstitution}</dd></div>
          <div className="flex items-center justify-between gap-4"><dt className="text-[#777a81]">连接渠道</dt><dd className="font-medium text-[#222327]">{label}</dd></div>
          <div className="flex items-center justify-between gap-4"><dt className="text-[#777a81]">设备</dt><dd className="max-w-[360px] truncate font-medium text-[#222327]">{preview?.device_name || "正在读取…"}</dd></div>
          <div className="flex items-center justify-between gap-4"><dt className="text-[#777a81]">授权码</dt><dd className="font-mono font-semibold tracking-wide text-[#222327]">{userCode || "—"}</dd></div>
        </dl>

        <button
          type="button"
          onClick={() => void approve()}
          disabled={status !== "ready"}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#17181a] px-4 py-3 text-sm font-semibold text-white disabled:cursor-default disabled:opacity-50"
        >
          <ShieldCheck className="h-4 w-4" />
          {status === "approved" ? "已允许连接" : status === "approving" ? "正在授权…" : "允许连接"}
        </button>
        {message ? <p role="status" className={`mt-4 text-sm ${status === "failed" ? "text-[#b42318]" : "text-[#4c6957]"}`}>{message}</p> : null}
        <p className="mt-5 text-xs leading-5 text-[#8a8d94]">授权码十分钟内有效且只能领取一次。凭据不会显示在页面、聊天或项目文件中。</p>
      </section>
    </div>
  );
}
