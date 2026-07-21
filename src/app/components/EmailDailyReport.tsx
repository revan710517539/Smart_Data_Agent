import { useEffect, useMemo, useState } from "react";
import { Mail, RefreshCw, Send, Sparkles } from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { apiErrorMessage } from "../services/apiClient";
import {
  fetchDailyEmailState,
  generateDailyEmail,
  sendDailyEmail,
  type DailyEmailState,
} from "../services/dailyEmailApi";

const EMPTY_STATE: DailyEmailState = {
  tenant_id: "",
  runs: [],
  latest: null,
  email_subscription_count: 0,
  delivery_summary: {},
};

export function EmailDailyReport() {
  const { tenantId, userId } = usePlatformContext();
  const [state, setState] = useState(EMPTY_STATE);
  const [busyAction, setBusyAction] = useState("");
  const [notice, setNotice] = useState("");

  const loadState = async () => {
    const response = await fetchDailyEmailState({ tenantId, userId });
    setState(response);
  };

  useEffect(() => {
    let cancelled = false;
    fetchDailyEmailState({ tenantId, userId })
      .then((response) => {
        if (!cancelled) setState(response);
      })
      .catch((error) => {
        if (!cancelled) {
          setState(EMPTY_STATE);
          setNotice(apiErrorMessage(error, "邮件日报状态加载失败。"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const modules = useMemo(() => [
    {
      title: "经营日报摘要",
      desc: "仅从证据完整、允许发布的报告版本生成不可变 HTML 正文。",
      status: state.latest ? "已生成" : "暂无可用产物",
    },
    {
      title: "证据与发布门禁",
      desc: "正文保留来源版本、内容校验值和已验证数据块摘要。",
      status: state.latest?.evidence_summary.publishable === true ? "证据通过" : "待满足门禁",
    },
    {
      title: "收件人与订阅规则",
      desc: "只向当前用户已配置的 report.daily.ready 邮件订阅投递。",
      status: state.email_subscription_count > 0 ? `${state.email_subscription_count} 个有效订阅` : "尚未配置",
    },
  ], [state]);

  const runDailyAction = async (action: "generate" | "send") => {
    setBusyAction(action);
    setNotice("");
    try {
      if (action === "generate") {
        await generateDailyEmail({ tenantId, userId });
        setNotice("日报正文已从可发布报告证据生成，并保存为不可变产物。");
      } else if (state.latest) {
        await sendDailyEmail({ tenantId, userId, dailyReportRunId: state.latest.daily_report_run_id });
        setNotice("日报已进入可靠投递队列；页面将在刷新后显示渠道真实回执。 ");
      }
      await loadState();
    } catch (error) {
      setNotice(apiErrorMessage(error, action === "generate" ? "日报生成失败。" : "日报入队失败。"));
    } finally {
      setBusyAction("");
    }
  };

  const canSend = Boolean(
    state.latest
    && state.email_subscription_count > 0
    && ["generated", "failed"].includes(state.latest.status),
  );

  return (
    <div className="p-7">
      <div className="mb-7 flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#f2f2f7]"><Mail className="h-[18px] w-[18px] text-[#636366]" /></div>
          <div>
            <h2 className="text-[18px] tracking-tight text-[#1d1d1f]">邮件日报</h2>
            <p className="mt-0.5 text-[13px] text-[#aeaeb2]">经营指标自动汇总 · 风险异常提醒 · 邮件订阅分发</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void runDailyAction("generate")} disabled={Boolean(busyAction)} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#636366] hover:bg-[#f2f2f7] disabled:opacity-50">
            <RefreshCw className={`h-3.5 w-3.5 ${busyAction === "generate" ? "animate-spin" : ""}`} />重新生成
          </button>
          <button onClick={() => void runDailyAction("send")} disabled={Boolean(busyAction) || !canSend} title={!canSend ? "需要已生成的日报和有效邮件订阅" : undefined} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white hover:bg-[#2c2c2e] disabled:opacity-50">
            <Send className="h-3.5 w-3.5" />发送日报
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice}</div>}

      <div className="grid gap-4 lg:grid-cols-3">
        {modules.map((module) => (
          <div key={module.title} className="rounded-xl border border-[#f0f0f2] bg-white p-5">
            <div className="mb-3 flex items-center justify-between"><Sparkles className="h-4 w-4 text-[#8a8a8e]" /><span className="rounded-full border border-[#e5e5ea] bg-[#fafbfc] px-2 py-0.5 text-[11px] text-[#636366]">{module.status}</span></div>
            <h3 className="text-[14px] text-[#1d1d1f]">{module.title}</h3>
            <p className="mt-2 text-[12px] leading-[1.7] text-[#8a8a8e]">{module.desc}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-xl border border-[#f0f0f2] bg-white p-5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[14px] text-[#1d1d1f]">今日邮件预览</span>
          {state.latest && <span className="text-[10px] text-[#aeaeb2]">{statusLabel(state.latest.status)} · {state.latest.report_date}</span>}
        </div>
        <div className="rounded-lg bg-[#fafbfc] p-4 text-[12px] leading-[1.8] text-[#636366] whitespace-pre-wrap">
          {state.latest?.preview_text || "暂无真实邮件正文。请先保存证据完整的经营周报版本，再生成日报。"}
        </div>
        {state.latest && (
          <div className="mt-3 text-[10px] leading-5 text-[#aeaeb2]">
            来源版本 {state.latest.source_report_version_id} · 正文产物 {state.latest.body_artifact_id}<br />
            SHA-256 {state.latest.content_hash} · 投递 {formatDeliverySummary(state.delivery_summary)}
          </div>
        )}
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  return ({ generated: "已生成", queued: "排队中", sending: "投递中", delivered: "已送达", failed: "投递失败" } as Record<string, string>)[status] || status;
}

function formatDeliverySummary(summary: Record<string, number>) {
  const entries = Object.entries(summary);
  return entries.length ? entries.map(([status, count]) => `${statusLabel(status)} ${count}`).join(" / ") : "尚无渠道回执";
}
