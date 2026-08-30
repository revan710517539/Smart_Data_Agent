import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router";
import {
  AlertTriangle,
  Bell,
  BellRing,
  CheckCircle2,
  Clock,
  ChevronDown,
  Edit3,
  Mail,
  MessageSquare,
  Plus,
  Smartphone,
  Send,
  ToggleLeft,
  ToggleRight,
  X,
} from "lucide-react";
import { usePlatformContext } from "../platform/PlatformContext";
import { fetchMarketBundle, type MarketBundle, type MarketRule } from "../services/marketApi";
import {
  enableTeamsMetricSubscription,
  fetchTeamsConnection,
  fetchNotificationBundle,
  pollTeamsConnectionAuthorization,
  startTeamsConnectionAuthorization,
  testTeamsMetricSubscription,
  updateNotificationSubscription,
  type NotificationBundle,
  type NotificationDelivery,
  type NotificationSubscription,
  type TeamsConnection,
  type TeamsMessageTemplate,
} from "../services/notificationApi";
import { fetchMetricDictionary } from "../services/metricDictionaryApi";
import { apiErrorMessage } from "../services/apiClient";
import { FormDialog, FormDialogCancelButton, FormDialogPrimaryButton } from "./ui/FormDialog";

type NotificationSection = "alerts" | "subscriptions" | "history";

function getNotificationSection(pathname: string): NotificationSection {
  if (pathname.endsWith("/subscriptions")) return "subscriptions";
  if (pathname.endsWith("/history")) return "history";
  return "alerts";
}

const EMPTY_NOTIFICATIONS: NotificationBundle = {
  tenant_id: "",
  subscriptions: [],
  in_app_deliveries: [],
  count: { subscriptions: 0, in_app_deliveries: 0 },
};

const EMPTY_MARKET: MarketBundle = {
  tenant_id: "",
  sources: [],
  entities: [],
  observations: [],
  rules: [],
  events: [],
};

const DISCONNECTED_TEAMS: TeamsConnection = { connected: false, provider: "360teams_self" };
const TEAMS_TEST_METRICS: Array<Record<string, unknown>> = [
  { metricId: "SYS_TEAMS_TEST_AMOUNT", metricName: "【测试】经营金额", metricCode: "sda_teams_test_amount", datasetId: "sda_teams_test", unit: "万元", isTestMetric: true },
  { metricId: "SYS_TEAMS_TEST_CUSTOMERS", metricName: "【测试】活跃客户数", metricCode: "sda_teams_test_customers", datasetId: "sda_teams_test", unit: "户", isTestMetric: true },
];
const SMART_DATA_AGENT_SUBSCRIPTIONS_URL = "https://xujingbo-smart-data-agent.qifudigitech.com/notifications/subscriptions";

function teamsSelectableMetrics(metrics: Array<Record<string, unknown>>) {
  return [...metrics, ...TEAMS_TEST_METRICS.filter((testMetric) => !metrics.some((metric) => String(metric.metricId) === String(testMetric.metricId)))];
}

export function Notifications() {
  const location = useLocation();
  const { tenantId, userId } = usePlatformContext();
  const activeTab = getNotificationSection(location.pathname);
  const [notifications, setNotifications] = useState(EMPTY_NOTIFICATIONS);
  const [market, setMarket] = useState(EMPTY_MARKET);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState("");
  const [metrics, setMetrics] = useState<Array<Record<string, unknown>>>([]);
  const [teamsSetupOpen, setTeamsSetupOpen] = useState(false);
  const [teamsBusy, setTeamsBusy] = useState(false);
  const [teamsDeviceCode, setTeamsDeviceCode] = useState("");
  const [teamsConnection, setTeamsConnection] = useState<TeamsConnection>(DISCONNECTED_TEAMS);
  const [teamsDraft, setTeamsDraft] = useState<TeamsRuleDraft>({ metricIds: [], subscriptionName: "", scheduleTime: "09:00", messageTemplate: defaultTeamsTemplate([]) });
  const [teamsModalNotice, setTeamsModalNotice] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotice("");
    Promise.all([fetchNotificationBundle({ tenantId, userId }), fetchMarketBundle({ tenantId, userId }), fetchMetricDictionary({ tenantId, userId }), fetchTeamsConnection({ tenantId, userId })])
      .then(([notificationBundle, marketBundle, metricBundle, teamsConnectionResponse]) => {
        if (cancelled) return;
        setNotifications(notificationBundle);
        setMarket(marketBundle);
        const subscriptionMetrics = teamsSelectableMetrics(metricBundle.metrics as Array<Record<string, unknown>>);
        setMetrics(subscriptionMetrics);
        setTeamsConnection(teamsConnectionResponse.connection);
        const executable = subscriptionMetrics.find((item) => String(item.metricId).startsWith("SYS_TEAMS_TEST_") && item.metricCode && item.datasetId) || subscriptionMetrics.find((item) => item.metricCode && item.datasetId);
        if (executable) setTeamsDraft((current) => current.metricIds.length ? current : withDraftMetricIds(current, [String(executable.metricId || "")], subscriptionMetrics));
      })
      .catch((error) => {
        if (cancelled) return;
        setNotifications(EMPTY_NOTIFICATIONS);
        setMarket(EMPTY_MARKET);
        setTeamsConnection(DISCONNECTED_TEAMS);
        setNotice(apiErrorMessage(error, "推送与订阅数据加载失败。"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenantId, userId]);

  const stats = useMemo(() => {
    const activeRules = market.rules.filter((rule) => rule.status === "active").length;
    const today = new Date().toDateString();
    const deliveredToday = notifications.in_app_deliveries.filter(
      (delivery) => delivery.status === "delivered" && new Date(delivery.delivered_at || delivery.created_at).toDateString() === today,
    ).length;
    return [
      { label: "活跃预警规则", value: String(activeRules), icon: BellRing },
      { label: "今日已送达", value: String(deliveredToday), icon: Bell },
      { label: "我的订阅", value: String(notifications.subscriptions.length), icon: Mail },
      { label: "投递记录", value: String(notifications.in_app_deliveries.length), icon: MessageSquare },
    ];
  }, [market.rules, notifications]);

  const unsupported = (message: string) => setNotice(message);
  const availableTeamsMetrics = teamsSelectableMetrics(metrics);
  const selectedMetrics = teamsDraft.metricIds.map((metricId) => availableTeamsMetrics.find((metric) => String(metric.metricId) === metricId)).filter((metric): metric is Record<string, unknown> => Boolean(metric));
  const selectedMetricExecutable = selectedMetrics.length === teamsDraft.metricIds.length && selectedMetrics.length > 0 && selectedMetrics.every((metric) => String(metric.metricCode || "").trim() && String(metric.datasetId || "").trim());
  const scheduleExpression = timeToDailyCron(teamsDraft.scheduleTime);
  const startTeamsConnection = async () => {
    const authorizationWindow = window.open("", "teams-authorization", "width=1080,height=760");
    if (authorizationWindow) authorizationWindow.opener = null;
    setTeamsBusy(true);
    try {
      const response = await startTeamsConnectionAuthorization({ tenantId, userId });
      setTeamsDeviceCode(response.authorization.device_code);
      if (authorizationWindow) authorizationWindow.location.assign(response.authorization.sso_url);
      else window.open(response.authorization.sso_url, "_blank", "noopener,noreferrer");
      const message = "已打开 Teams 授权页，请完成页面中的全部授权步骤；系统会在授权完成后自动确认连接。";
      setNotice(message);
      setTeamsModalNotice(message);
    } catch (error) {
      authorizationWindow?.close();
      const message = apiErrorMessage(error, "Teams 授权启动失败。");
      setNotice(message);
      setTeamsModalNotice(message);
    } finally { setTeamsBusy(false); }
  };
  useEffect(() => {
    if (!teamsDeviceCode) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const response = await pollTeamsConnectionAuthorization({ tenantId, userId, deviceCode: teamsDeviceCode });
        if (cancelled || !response.completed) return;
        setTeamsConnection(response.connection);
        setTeamsDeviceCode("");
        const message = "Teams 已连接，可发送测试消息或启用订阅。";
        setNotice(message);
        setTeamsModalNotice(message);
      } catch (error) {
        if (!cancelled) {
          setTeamsDeviceCode("");
          const message = apiErrorMessage(error, "Teams 授权状态确认失败，请重新连接。");
          setNotice(message);
          setTeamsModalNotice(message);
        }
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2_000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [teamsDeviceCode, tenantId, userId]);
  const enableTeamsRule = async () => {
    if (!teamsConnection.connected) { setTeamsModalNotice("Teams 尚未连接。请先关闭弹窗，点击页面右上角“连接 Teams”完成授权后再启用。"); return; }
    if (!teamsDraft.metricIds.length || !selectedMetricExecutable) { setTeamsModalNotice("请选择至少一个可执行指标后再启用。"); return; }
    setTeamsBusy(true);
    try {
      const response = await enableTeamsMetricSubscription({ tenantId, userId, metricIds: teamsDraft.metricIds, subscriptionName: teamsDraft.subscriptionName, scheduleExpression, messageTemplate: teamsDraft.messageTemplate });
      setNotifications((current) => ({ ...current, subscriptions: [response.subscription, ...current.subscriptions] }));
      setTeamsSetupOpen(false);
      setTeamsModalNotice("");
      setNotice("Teams 每日指标订阅已启用，将仅向当前已连接的 Teams 账号发送。");
    } catch (error) {
      const message = apiErrorMessage(error, "Teams 规则启用失败。");
      setTeamsModalNotice(message);
      setNotice(message);
    } finally { setTeamsBusy(false); }
  };
  const testTeamsRule = async () => {
    if (!teamsConnection.connected) { setTeamsModalNotice("Teams 尚未连接，因此未发送。请先关闭弹窗，点击页面右上角“连接 Teams”完成授权。"); return; }
    if (!teamsDraft.metricIds.length || !selectedMetricExecutable) { setTeamsModalNotice("请选择至少一个可执行指标后再测试；系统已提供两个【测试】指标。 "); return; }
    setTeamsBusy(true);
    try {
      const response = await testTeamsMetricSubscription({ tenantId, userId, metricIds: teamsDraft.metricIds, subscriptionName: teamsDraft.subscriptionName, scheduleExpression, messageTemplate: teamsDraft.messageTemplate });
      const message = `Teams 测试消息已发送，回执：${response.provider_message_id}。未创建定时订阅。`;
      setTeamsModalNotice(message);
      setNotice(message);
    } catch (error) {
      const message = apiErrorMessage(error, "Teams 测试消息发送失败。请确认授权和网络后重试。");
      setTeamsModalNotice(message);
      setNotice(message);
    } finally { setTeamsBusy(false); }
  };
  const manageSubscription = async (subscription: NotificationSubscription) => {
    const nextStatus = subscription.status === "active" ? "paused" : "active";
    setNotice(nextStatus === "paused" ? "正在暂停订阅…" : "正在启用订阅…");
    try {
      const response = await updateNotificationSubscription({
        tenantId,
        userId,
        subscriptionId: subscription.subscription_id,
        expectedLockVersion: subscription.lock_version,
        changes: { status: nextStatus },
      });
      setNotifications((current) => ({
        ...current,
        subscriptions: current.subscriptions.map((item) =>
          item.subscription_id === response.subscription.subscription_id ? response.subscription : item,
        ),
      }));
      setNotice(nextStatus === "paused" ? "订阅已暂停，后续事件不会再生成投递。" : "订阅已启用，后续事件将按原渠道投递。");
    } catch (error) {
      setNotice(apiErrorMessage(error, "订阅状态更新失败。"));
    }
  };

  return (
    <div className="p-7">
      <div className="flex items-center justify-between mb-7">
        <div>
          <h2 className="text-[18px] text-[#1d1d1f] tracking-tight">推送与订阅</h2>
          <p className="text-[13px] text-[#aeaeb2] mt-1">智能预警规则 · 定期报告订阅 · 推送记录追踪</p>
        </div>
        <div className="flex w-fit min-h-9 shrink-0 items-center gap-[0.2cm]" data-page-header-actions="true">
          <button onClick={() => void startTeamsConnection()} disabled={teamsBusy} className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-[#e5e5ea] bg-white px-3 text-[12px] text-[#3a3a3c] transition-colors hover:bg-[#f2f2f7] disabled:opacity-50">
            <Send className="w-3.5 h-3.5" />
            {teamsConnection.connected ? "Teams 已连接" : teamsDeviceCode ? "Teams 授权中" : "连接 Teams"}
          </button>
          <button onClick={() => { setNotice(""); setTeamsModalNotice(""); setTeamsSetupOpen(true); }} className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-[#1d1d1f] px-3 text-[12px] text-white transition-colors hover:bg-[#2c2c2e]">
            <Plus className="w-3.5 h-3.5" />
            新建规则
          </button>
        </div>
      </div>

      {notice && <div className="mb-4 rounded-lg border border-[#e5e5ea] bg-white px-4 py-3 text-[12px] text-[#636366]">{notice}</div>}

      {teamsSetupOpen && <TeamsRuleModal
        metrics={availableTeamsMetrics}
        draft={teamsDraft}
        selectedMetrics={selectedMetrics}
        selectedMetricExecutable={selectedMetricExecutable}
        busy={teamsBusy}
        teamsConnected={teamsConnection.connected}
        notice={teamsModalNotice}
        onClose={() => setTeamsSetupOpen(false)}
        onDraftChange={setTeamsDraft}
        onEnable={() => void enableTeamsRule()}
        onTest={() => void testTeamsRule()}
        onConnect={() => void startTeamsConnection()}
      />}

      <div className="grid grid-cols-4 gap-4 mb-6">
        {stats.map((item) => (
          <div key={item.label} className="bg-white p-4 rounded-xl border border-[#f0f0f2]">
            <item.icon className="w-4 h-4 text-[#636366] mb-2" />
            <div className="text-[22px] text-gray-900 tracking-tight">{loading ? "—" : item.value}</div>
            <div className="text-[12px] text-gray-400 mt-0.5">{item.label}</div>
          </div>
        ))}
      </div>

      {activeTab === "alerts" && (
        <div className="space-y-2">
          {market.rules.map((rule) => (
            <AlertRuleCard
              key={rule.market_rule_id}
              rule={rule}
              subscriptions={notifications.subscriptions}
              triggerCount={market.events.filter((event) => event.market_rule_id === rule.market_rule_id).length}
              lastTrigger={market.events.find((event) => event.market_rule_id === rule.market_rule_id)?.detected_at}
              onUnsupported={unsupported}
            />
          ))}
          {!loading && market.rules.length === 0 && <EmptyState text="暂无已配置且有权限查看的真实预警规则。" />}
        </div>
      )}

      {activeTab === "subscriptions" && (
        <div className="space-y-2">
          {notifications.subscriptions.map((subscription) => (
            <SubscriptionCard key={subscription.subscription_id} subscription={subscription} onManage={manageSubscription} />
          ))}
          {!loading && notifications.subscriptions.length === 0 && <EmptyState text="暂无订阅。创建订阅后，事件才会进入相应投递渠道。" />}
        </div>
      )}

      {activeTab === "history" && (
        <div className="bg-white rounded-xl border border-[#f0f0f2] p-5">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-gray-400 text-[11px]">
                <th className="text-left py-2.5 px-3">时间</th>
                <th className="text-left py-2.5 px-3">标题</th>
                <th className="text-center py-2.5 px-3">类型</th>
                <th className="text-left py-2.5 px-3">渠道</th>
                <th className="text-center py-2.5 px-3">真实状态</th>
                <th className="text-center py-2.5 px-3">回执</th>
              </tr>
            </thead>
            <tbody>
              {notifications.in_app_deliveries.map((delivery) => <DeliveryRow key={delivery.delivery_id} delivery={delivery} />)}
            </tbody>
          </table>
          {!loading && notifications.in_app_deliveries.length === 0 && <div className="py-10 text-center text-[12px] text-[#aeaeb2]">暂无真实投递记录。</div>}
        </div>
      )}
    </div>
  );
}

function AlertRuleCard({
  rule,
  subscriptions,
  triggerCount,
  lastTrigger,
  onUnsupported,
}: {
  rule: MarketRule;
  subscriptions: NotificationSubscription[];
  triggerCount: number;
  lastTrigger?: string;
  onUnsupported: (message: string) => void;
}) {
  const enabled = rule.status === "active";
  const channels = subscriptions
    .filter((subscription) => subscription.status === "active" && subscription.event_types.includes("market.monitoring.triggered"))
    .map((subscription) => subscription.channel_type);
  return (
    <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 hover:border-[#d1d1d6] transition-colors">
      <div className="flex items-start gap-4">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0 bg-[#f2f2f7]">
          <AlertTriangle className={`w-4 h-4 ${enabled ? "text-[#636366]" : "text-[#c7c7cc]"}`} />
        </div>
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[14px] text-gray-900">{rule.rule_name}</span>
            <span className="text-[10px] px-2 py-0.5 rounded bg-[#f2f2f7] text-[#636366]">{enabled ? "已启用" : rule.status}</span>
          </div>
          <div className="flex items-center gap-4 text-[11px] text-gray-400 mb-2">
            <span>指标：{rule.metric_code}</span>
            <span>条件：{formatCondition(rule.condition_expression)}</span>
            <span>级别：{rule.severity}</span>
          </div>
          <div className="flex items-center gap-3">
            {channels.map((channel) => <ChannelBadge key={channel} channel={channel} />)}
            {channels.length === 0 && <span className="text-[10px] text-[#aeaeb2]">尚未绑定订阅渠道</span>}
            <span className="text-[10px] text-gray-400 ml-auto">触发 {triggerCount} 次 · 最近 {formatTime(lastTrigger)}</span>
          </div>
        </div>
        <div className="flex gap-1.5">
          <button onClick={() => onUnsupported("规则编辑需要回到市场监控的证据与口径审核流程。")} className="p-2 bg-[#f5f5f7] rounded-lg hover:bg-[#f0f0f2]">
            <Edit3 className="w-3.5 h-3.5 text-gray-400" />
          </button>
          <button onClick={() => onUnsupported("规则状态不能在展示页直接切换，请通过有审计记录的规则管理接口处理。") } className="p-2 bg-[#f5f5f7] rounded-lg hover:bg-[#f0f0f2]">
            {enabled ? <ToggleRight className="w-3.5 h-3.5 text-[#34c759]" /> : <ToggleLeft className="w-3.5 h-3.5 text-gray-400" />}
          </button>
        </div>
      </div>
    </div>
  );
}

type TeamsRuleDraft = { metricIds: string[]; subscriptionName: string; scheduleTime: string; messageTemplate: TeamsMessageTemplate };

const TEMPLATE_COLORS: Record<TeamsMessageTemplate["metrics"][number]["color"], { label: string; className: string }> = {
  slate: { label: "深灰", className: "text-[#3a3a3c]" },
  blue: { label: "蓝色", className: "text-[#007aff]" },
  green: { label: "绿色", className: "text-[#248a3d]" },
  amber: { label: "橙色", className: "text-[#b26a00]" },
  red: { label: "红色", className: "text-[#d70015]" },
};

function defaultTeamsTemplate(metricIds: string[]): TeamsMessageTemplate {
  return {
    title: "每日经营快报",
    subtitle: "当前机构 · T+1",
    footer: "只发送已授权数据，不展示 JSON。",
    metrics: metricIds.map((metricId) => ({ metricId, fontSize: "normal", color: "slate" })),
    bodyHtml: defaultTemplateBody([]),
  };
}

function escapeTemplateHtml(value: string) {
  return value.replace(/[&<>\"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[character] || character);
}

function defaultTemplateBody(metrics: Array<Record<string, unknown>>) {
  const metricLines = metrics.length
    ? metrics.map((metric) => `<div>{{metric:${escapeTemplateHtml(String(metric.metricId))}}}</div>`).join("")
    : "<div>在这里输入指标名称，系统会自动识别为指标占位符。</div>";
  return `<h2>每日经营快报</h2><p>当前机构 · T+1</p><hr><p><strong>核心指标</strong></p>${metricLines}<hr><p>只发送已授权数据，不展示 JSON。</p><p>详情请在 PC 端点击：<a href="${SMART_DATA_AGENT_SUBSCRIPTIONS_URL}">Smart Data Agent</a></p>`;
}

function safeTemplateMarkup(value: string, metrics: Array<Record<string, unknown>>, displayPlaceholders: boolean) {
  const parser = new DOMParser();
  const source = parser.parseFromString(value, "text/html").body;
  const allowedMetricIds = new Set(metrics.map((metric) => String(metric.metricId)));
  const metricById = new Map(metrics.map((metric) => [String(metric.metricId), String(metric.metricName || "指标")]));
  const allowed = new Set(["div", "p", "br", "strong", "b", "em", "i", "u", "h1", "h2", "h3", "span", "font", "hr", "a"]);
  const clean = (node: Node): Node | null => {
    if (node.nodeType === Node.TEXT_NODE) {
      const fragment = document.createDocumentFragment();
      const text = node.textContent || "";
      const tokenPattern = /\{\{metric:([^}]+)\}\}/g;
      let cursor = 0;
      for (const match of text.matchAll(tokenPattern)) {
        fragment.append(document.createTextNode(text.slice(cursor, match.index)));
        const metricId = match[1];
        if (allowedMetricIds.has(metricId)) {
          const placeholder = document.createElement("span");
          placeholder.dataset.metricId = metricId;
          placeholder.contentEditable = "false";
          placeholder.className = "inline-flex rounded-md border border-[#b8cee8] bg-[#edf4fb] px-1.5 py-0.5 font-medium text-[#0a66c2]";
          placeholder.textContent = displayPlaceholders ? `${metricById.get(metricId) || "指标"}：指标值` : `${metricById.get(metricId) || "指标"}：发送时查询`;
          fragment.append(placeholder);
        }
        cursor = (match.index || 0) + match[0].length;
      }
      fragment.append(document.createTextNode(text.slice(cursor)));
      return fragment;
    }
    if (node.nodeType !== Node.ELEMENT_NODE || !allowed.has(node.nodeName.toLowerCase())) return null;
    const sourceElement = node as HTMLElement;
    const tag = sourceElement.nodeName.toLowerCase() === "font" ? "span" : sourceElement.nodeName.toLowerCase();
    const element = document.createElement(tag);
    const color = sourceElement.style.color || sourceElement.getAttribute("color") || "";
    const fontSize = sourceElement.style.fontSize || ({ "1": "11px", "2": "12px", "3": "14px", "4": "16px", "5": "20px", "6": "24px" }[sourceElement.getAttribute("size") || ""] || "");
    const textAlign = sourceElement.style.textAlign;
    if (/^(rgb\([\d, ]+\)|#[0-9a-fA-F]{3,8})$/.test(color)) element.style.color = color;
    if (/^(11|12|13|14|16|18|20|24)px$/.test(fontSize)) element.style.fontSize = fontSize;
    if (["left", "center", "right"].includes(textAlign)) element.style.textAlign = textAlign;
    if (tag === "a") {
      const href = sourceElement.getAttribute("href") || "";
      if (href !== SMART_DATA_AGENT_SUBSCRIPTIONS_URL) return document.createTextNode(sourceElement.textContent || "");
      element.setAttribute("href", SMART_DATA_AGENT_SUBSCRIPTIONS_URL);
      element.setAttribute("target", "_blank");
      element.setAttribute("rel", "noreferrer");
      element.className = "font-medium text-[#0a66c2] underline decoration-[#0a66c2]/35 underline-offset-2";
    }
    const metricId = sourceElement.dataset.metricId;
    if (metricId && allowedMetricIds.has(metricId)) {
      element.dataset.metricId = metricId;
      element.contentEditable = "false";
      element.className = "inline-flex rounded-md border border-[#b8cee8] bg-[#edf4fb] px-1.5 py-0.5 font-medium text-[#0a66c2]";
      element.textContent = displayPlaceholders ? `${metricById.get(metricId) || "指标"}：指标值` : `${metricById.get(metricId) || "指标"}：发送时查询`;
      return element;
    }
    Array.from(node.childNodes).forEach((child) => { const result = clean(child); if (result) element.append(result); });
    return element;
  };
  const target = document.createElement("div");
  Array.from(source.childNodes).forEach((child) => { const result = clean(child); if (result) target.append(result); });
  return target.innerHTML.slice(0, 8000);
}

function saveTemplateMarkup(value: string, metrics: Array<Record<string, unknown>>) {
  const parser = new DOMParser();
  const root = parser.parseFromString(safeTemplateMarkup(value, metrics, true), "text/html").body;
  root.querySelectorAll<HTMLElement>("[data-metric-id]").forEach((element) => element.replaceWith(document.createTextNode(`{{metric:${element.dataset.metricId}}}`)));
  const metricMatches = [...metrics]
    .map((metric) => ({ id: String(metric.metricId), name: String(metric.metricName || "").trim() }))
    .filter((metric) => metric.name)
    .sort((left, right) => right.name.length - left.name.length);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const textNodes: Text[] = [];
  while (walker.nextNode()) textNodes.push(walker.currentNode as Text);
  for (const node of textNodes) {
    let text = node.textContent || "";
    for (const metric of metricMatches) text = text.replaceAll(metric.name, `{{metric:${metric.id}}}`);
    node.textContent = text;
  }
  // `root` was built from the strict allow-list above. Keep tokens as tokens so
  // a later metric selection does not append a second visual placeholder.
  return root.innerHTML.slice(0, 8000);
}

function removeTemplateMetricPlaceholders(value: string, metricId: string) {
  const escapedId = metricId.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return value
    .replace(new RegExp(`\\{\\{metric:${escapedId}\\}\\}`, "g"), "")
    .replace(new RegExp(`<span[^>]*data-metric-id=["']${escapedId}["'][^>]*>[\\s\\S]*?<\\/span>`, "g"), "");
}

function detectTemplateMetricIds(value: string, metrics: Array<Record<string, unknown>>) {
  const text = new DOMParser().parseFromString(value, "text/html").body.textContent || "";
  return metrics.filter((metric) => String(metric.metricName || "").trim() && text.includes(String(metric.metricName))).map((metric) => String(metric.metricId));
}

function withDraftMetricIds(current: TeamsRuleDraft, metricIds: string[], metrics: Array<Record<string, unknown>>): TeamsRuleDraft {
  const selectedIds = [...new Set(metricIds.filter(Boolean))];
  const previous = new Map(current.messageTemplate.metrics.map((item) => [item.metricId, item]));
  const template = {
    ...current.messageTemplate,
    metrics: selectedIds.map((metricId) => previous.get(metricId) || { metricId, fontSize: "normal" as const, color: "slate" as const }),
    bodyHtml: selectedIds.reduce((body, metricId) => body.includes(`{{metric:${metricId}}}`) ? body : `${body}<div>{{metric:${metricId}}}</div>`, current.messageTemplate.bodyHtml || defaultTemplateBody([])),
  };
  const selectedNames = selectedIds.map((metricId) => String(metrics.find((metric) => String(metric.metricId) === metricId)?.metricName || "指标"));
  return {
    ...current,
    metricIds: selectedIds,
    messageTemplate: template,
    subscriptionName: current.subscriptionName || `${selectedNames.slice(0, 2).join("、") || "指标"}${selectedNames.length > 2 ? "等" : ""}每日快报`,
  };
}

function TeamsRuleModal({
  metrics,
  draft,
  selectedMetrics,
  selectedMetricExecutable,
  busy,
  teamsConnected,
  notice,
  onClose,
  onDraftChange,
  onEnable,
  onTest,
  onConnect,
}: {
  metrics: Array<Record<string, unknown>>;
  draft: TeamsRuleDraft;
  selectedMetrics: Array<Record<string, unknown>>;
  selectedMetricExecutable: boolean;
  busy: boolean;
  teamsConnected: boolean;
  notice: string;
  onClose: () => void;
  onDraftChange: (next: TeamsRuleDraft | ((current: TeamsRuleDraft) => TeamsRuleDraft)) => void;
  onEnable: () => void;
  onTest: () => void;
  onConnect: () => void;
}) {
  const [metricPickerOpen, setMetricPickerOpen] = useState(false);
  const [templateEditing, setTemplateEditing] = useState(false);
  const [templateDraft, setTemplateDraft] = useState<TeamsMessageTemplate>(draft.messageTemplate);
  const templateEditorRef = useRef<HTMLDivElement>(null);
  const selectedMetricIds = new Set(draft.metricIds);
  const selectableMetrics = teamsSelectableMetrics(metrics);
  const applyMetricIds = (nextMetricIds: string[]) => {
    onDraftChange((current) => withDraftMetricIds(current, nextMetricIds, metrics));
    setTemplateDraft((current) => ({ ...withDraftMetricIds({ ...draft, messageTemplate: current }, nextMetricIds, metrics).messageTemplate }));
  };
  const removeMetric = (metricId: string) => {
    const nextMetricIds = draft.metricIds.filter((item) => item !== metricId);
    onDraftChange((current) => {
      const next = withDraftMetricIds(current, nextMetricIds, metrics);
      return { ...next, messageTemplate: { ...next.messageTemplate, bodyHtml: removeTemplateMetricPlaceholders(String(current.messageTemplate.bodyHtml || ""), metricId) } };
    });
    setTemplateDraft((current) => ({ ...current, metrics: current.metrics.filter((item) => item.metricId !== metricId), bodyHtml: removeTemplateMetricPlaceholders(String(current.bodyHtml || ""), metricId) }));
  };
  const cancelTemplateEdit = () => { setTemplateDraft(draft.messageTemplate); setTemplateEditing(false); };
  const saveTemplateEdit = () => {
    const editorHtml = templateEditorRef.current?.innerHTML || templateDraft.bodyHtml || defaultTemplateBody(selectedMetrics);
    const detectedMetricIds = detectTemplateMetricIds(editorHtml, metrics);
    const bodyHtml = saveTemplateMarkup(editorHtml, metrics);
    onDraftChange((current) => {
      const next = withDraftMetricIds(current, [...current.metricIds, ...detectedMetricIds], metrics);
      return { ...next, messageTemplate: { ...templateDraft, metrics: next.messageTemplate.metrics, bodyHtml } };
    });
    setTemplateDraft((current) => ({ ...current, bodyHtml }));
    setTemplateEditing(false);
  };
  const beginTemplateEdit = () => {
    const bodyHtml = templateDraft.bodyHtml || defaultTemplateBody(selectedMetrics);
    setTemplateDraft((current) => ({ ...current, bodyHtml }));
    setTemplateEditing(true);
  };
  const applyEditorCommand = (command: string, value?: string) => {
    templateEditorRef.current?.focus();
    document.execCommand(command, false, value);
  };
  useEffect(() => {
    if (!templateEditing || !templateEditorRef.current) return;
    templateEditorRef.current.innerHTML = safeTemplateMarkup(templateDraft.bodyHtml || defaultTemplateBody(selectedMetrics), selectedMetrics, true);
  // Populate the editable canvas only when it opens; do not reset the caret during typing.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateEditing]);
  return (
    <FormDialog
      open
      title="新建 Teams 指标规则"
      description="推送与订阅 · 按固定经营快报格式，每天仅发送给本人（当前） Teams 账号。"
      widthClassName="max-w-[1180px]"
      heightClassName="h-[min(860px,calc(100vh-2rem))]"
      busy={busy}
      onClose={onClose}
      bodyClassName="px-6 py-5"
      footer={<><div className="mr-auto min-w-0"><span className={`block text-[11px] ${teamsConnected ? "text-[#34a853]" : "text-[#8a8a8e]"}`}>{teamsConnected ? "Teams 已连接，发送对象固定为本人。" : "请先点击页面上的“连接 Teams”完成授权。"}</span>{notice && <span className={`mt-1 block max-w-[680px] text-[11px] ${notice.includes("已发送") ? "text-[#248a3d]" : "text-[#d06b35]"}`}>{notice}</span>}</div>{!teamsConnected && <FormDialogCancelButton disabled={busy} onClick={onConnect}>连接 Teams</FormDialogCancelButton>}<FormDialogCancelButton disabled={busy} onClick={onTest}>测试</FormDialogCancelButton><FormDialogCancelButton onClick={onClose}>取消</FormDialogCancelButton><FormDialogPrimaryButton disabled={busy} onClick={onEnable}>启用</FormDialogPrimaryButton></>}
    >
          <div className="space-y-5 pr-1">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <label className="block text-[12px] font-medium text-[#636366]">规则名称
              <input value={draft.subscriptionName} placeholder="例如：放款金额每日快报" onChange={(event) => onDraftChange((current) => ({ ...current, subscriptionName: event.target.value }))} className="mt-2 h-10 w-full rounded-lg border border-[#d1d1d6] bg-white px-3 text-[13px] text-[#1d1d1f] outline-none placeholder:text-[#c7c7cc] focus:border-[#1d1d1f]" />
            </label>
            <div className="relative block text-[12px] font-medium text-[#636366]">订阅指标
              <button type="button" onClick={() => setMetricPickerOpen((current) => !current)} className="mt-2 flex h-10 w-full items-center justify-between rounded-lg border border-[#d1d1d6] bg-white px-3 text-left text-[13px] text-[#1d1d1f] outline-none focus:border-[#1d1d1f]">
                <span className="truncate">{selectedMetrics.length ? selectedMetrics.map((metric) => String(metric.metricName)).join("、") : "请选择指标（可多选）"}</span><ChevronDown className="ml-2 h-4 w-4 shrink-0 text-[#8a8a8e]" />
              </button>
              {selectedMetrics.length > 0 && <div className="mt-1.5 flex flex-wrap gap-1">{selectedMetrics.map((metric) => <span key={String(metric.metricId)} className="inline-flex items-center gap-1 rounded-md bg-[#edf4fb] px-2 py-1 text-[10px] text-[#0a66c2]">{String(metric.metricName)}<button type="button" onClick={() => removeMetric(String(metric.metricId))} className="rounded px-0.5 text-[#0a66c2] hover:bg-[#d8e9fa]" aria-label={`移除${String(metric.metricName)}`}>×</button></span>)}</div>}
              {metricPickerOpen && <div className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-lg border border-[#d1d1d6] bg-white p-1 shadow-lg"><div className="px-2 py-1.5 text-[10px] font-medium text-[#0a66c2]">系统测试指标</div>{selectableMetrics.map((metric) => { const metricId = String(metric.metricId); const executable = Boolean(String(metric.metricCode || "").trim() && String(metric.datasetId || "").trim()); const systemTest = metricId.startsWith("SYS_TEAMS_TEST_"); return <label key={metricId} className={`flex cursor-pointer items-center gap-2 rounded px-2 py-2 text-[12px] ${executable ? "hover:bg-[#f5f5f7]" : "cursor-not-allowed text-[#aeaeb2]"}`}><input type="checkbox" disabled={!executable} checked={selectedMetricIds.has(metricId)} onChange={() => applyMetricIds(selectedMetricIds.has(metricId) ? draft.metricIds.filter((item) => item !== metricId) : [...draft.metricIds, metricId])} /><span>{String(metric.metricName)}{systemTest ? "（测试值）" : executable ? "" : "（待配置数据集）"}</span></label>; })}</div>}
              {!selectedMetrics.length && <span className="mt-1 block text-[11px] font-normal text-[#aeaeb2]">可多选；只能选择已绑定指标编码与数据集的指标。</span>}
              {selectedMetrics.length > 0 && !selectedMetricExecutable && <span className="mt-1 block text-[11px] font-normal text-[#d06b35]">含未配置数据集的指标，不能创建真实订阅。</span>}
              {selectedMetricExecutable && <span className="mt-1 block text-[11px] font-normal text-[#34a853]">已选 {selectedMetrics.length} 个可执行指标。</span>}
            </div>
            <label className="block text-[12px] font-medium text-[#636366]">每日发送时间
              <input type="time" value={draft.scheduleTime} onChange={(event) => onDraftChange((current) => ({ ...current, scheduleTime: event.target.value }))} className="mt-2 h-10 w-full rounded-lg border border-[#d1d1d6] bg-white px-3 text-[13px] text-[#1d1d1f] outline-none focus:border-[#1d1d1f]" />
              <span className="mt-1 block text-[11px] font-normal text-[#aeaeb2]">Asia/Shanghai · 每日执行</span>
            </label>
          </div>

          <div className="min-h-[400px] rounded-xl border border-[#e5e5ea] bg-[#fafafa] p-4">
            <div className="mb-3 flex items-center gap-2"><Send className="h-3.5 w-3.5 text-[#636366]" /><span className="text-[12px] font-medium text-[#1d1d1f]">Teams 消息预览</span><span className="ml-auto rounded-full bg-[#f0f0f2] px-2 py-0.5 text-[10px] text-[#636366]">固定经营快报</span><button type="button" onClick={beginTemplateEdit} disabled={templateEditing} className="ml-2 rounded-md border border-[#d1d1d6] bg-white px-2 py-1 text-[10px] text-[#636366] disabled:opacity-45">编辑</button><button type="button" onClick={cancelTemplateEdit} disabled={!templateEditing} className="rounded-md border border-[#d1d1d6] bg-white px-2 py-1 text-[10px] text-[#636366] disabled:opacity-45">取消</button><button type="button" onClick={saveTemplateEdit} disabled={!templateEditing} className="rounded-md bg-[#1d1d1f] px-2 py-1 text-[10px] text-white disabled:opacity-45">保存</button></div>
            {templateEditing && <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded-lg border border-[#d1d1d6] bg-white p-2"><span className="mr-1 text-[10px] text-[#8a8a8e]">直接编辑模板</span><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("fontSize", "2")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">小字</button><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("fontSize", "3")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">常规</button><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("fontSize", "5")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">大字</button><span className="mx-1 h-4 border-l border-[#e5e5ea]" />{Object.entries(TEMPLATE_COLORS).map(([color, option]) => <button key={color} type="button" title={option.label} onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("foreColor", color === "slate" ? "#3a3a3c" : color === "blue" ? "#007aff" : color === "green" ? "#248a3d" : color === "amber" ? "#b26a00" : "#d70015")} className={`h-6 w-6 rounded-full border border-white shadow-sm ${color === "slate" ? "bg-[#3a3a3c]" : color === "blue" ? "bg-[#007aff]" : color === "green" ? "bg-[#248a3d]" : color === "amber" ? "bg-[#b26a00]" : "bg-[#d70015]"}`} aria-label={`文字${option.label}`} />)}<span className="mx-1 h-4 border-l border-[#e5e5ea]" /><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("justifyLeft")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">左对齐</button><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("justifyCenter")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">居中</button><button type="button" onMouseDown={(event) => event.preventDefault()} onClick={() => applyEditorCommand("justifyRight")} className="rounded border border-[#e5e5ea] px-2 py-1 text-[10px]">右对齐</button><span className="ml-auto text-[10px] text-[#8a8a8e]">输入指标名称后保存，系统自动转为占位符</span></div>}
            <div ref={templateEditorRef} contentEditable={templateEditing} suppressContentEditableWarning onInput={() => undefined} className={`min-h-[310px] rounded-lg border border-[#ececf0] bg-white px-5 py-4 text-[12px] leading-6 text-[#3a3a3c] ${templateEditing ? "cursor-text outline-none ring-2 ring-[#0a66c2]/10" : ""}`} dangerouslySetInnerHTML={{ __html: safeTemplateMarkup(templateDraft.bodyHtml || defaultTemplateBody(selectedMetrics), selectedMetrics, templateEditing) }} />
            <div className="mt-2 text-[10px] text-[#aeaeb2]">已识别的指标会显示为占位符；发送时会在原位置填入指标名称、指标值、统计周期与环比变化。</div>
          </div>
          </div>
    </FormDialog>
  );
}

function SubscriptionCard({ subscription, onManage }: { subscription: NotificationSubscription; onManage: (subscription: NotificationSubscription) => void }) {
  return (
    <div className="bg-white rounded-xl border border-[#f0f0f2] p-5 hover:border-[#d1d1d6] transition-colors">
      <div className="flex items-center gap-4">
        <div className="w-9 h-9 rounded-lg bg-[#f2f2f7] flex items-center justify-center shrink-0"><Mail className="w-4 h-4 text-[#636366]" /></div>
        <div className="flex-1">
          <div className="text-[14px] text-gray-900 mb-1">{subscription.subscription_name}</div>
          <div className="flex items-center gap-4 text-[11px] text-gray-400">
            <span className="flex items-center gap-1"><Clock className="w-3 h-3" />事件触发</span>
            <span>{subscription.event_types.join("、")}</span>
            <span>渠道：{channelLabel(subscription.channel_provider || subscription.channel_type)}</span>
            <span>状态：{subscription.status}</span>
          </div>
        </div>
        <button onClick={() => onManage(subscription)} className="px-3 py-1.5 border border-[#e5e5ea] rounded-lg text-[11px] text-[#636366] hover:bg-[#f2f2f7]">{subscription.status === "active" ? "暂停" : "启用"}</button>
      </div>
    </div>
  );
}

function DeliveryRow({ delivery }: { delivery: NotificationDelivery }) {
  const delivered = delivery.status === "delivered";
  const title = String(delivery.payload.summary || delivery.payload.task_name || delivery.event_type);
  return (
    <tr className="border-t border-gray-50 text-gray-700 hover:bg-[#f5f5f7]">
      <td className="py-3 px-3 text-gray-400">{formatTime(delivery.delivered_at || delivery.created_at)}</td>
      <td className="py-3 px-3 text-gray-800">{title}</td>
      <td className="py-3 px-3 text-center"><span className="text-[10px] px-2 py-0.5 rounded-full bg-[#007aff]/8 text-[#007aff]">{delivery.event_type}</span></td>
      <td className="py-3 px-3">{channelLabel(delivery.channel_type)}</td>
      <td className="py-3 px-3 text-center">
        <span className={`text-[10px] px-2 py-0.5 rounded flex items-center gap-0.5 w-fit mx-auto ${delivered ? "text-[#34a853] bg-[#34a853]/6" : "text-[#8a8a8e] bg-[#f2f2f7]"}`}>
          {delivered && <CheckCircle2 className="w-3 h-3" />}{deliveryStatusLabel(delivery.status)}
        </span>
      </td>
      <td className="py-3 px-3 text-center text-gray-600">{delivery.provider_message_id || delivery.error_code || "—"}</td>
    </tr>
  );
}

function ChannelBadge({ channel }: { channel: string }) {
  const Icon = channel === "email" ? Mail : channel === "webhook" ? Smartphone : MessageSquare;
  return <span className="text-[10px] text-gray-500 bg-[#f5f5f7] px-2 py-0.5 rounded-full flex items-center gap-1"><Icon className="w-3 h-3" />{channelLabel(channel)}</span>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="rounded-xl border border-[#f0f0f2] bg-white px-5 py-10 text-center text-[12px] text-[#aeaeb2]">{text}</div>;
}

function formatCondition(condition: { operator?: string; threshold?: number }) {
  const labels: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=", change_pct_gt: "变化率 >", change_pct_lt: "变化率 <" };
  return `${labels[String(condition.operator)] || condition.operator || "—"} ${condition.threshold ?? "—"}`;
}

function channelLabel(channel: string) {
  return ({ in_app: "站内信", email: "邮件", webhook: "Webhook", "360teams_self": "360Teams（仅本人）" } as Record<string, string>)[channel] || channel;
}

function timeToDailyCron(value: string) {
  const [hourText, minuteText] = String(value || "09:00").split(":", 2);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) return "0 9 * * *";
  return `${minute} ${hour} * * *`;
}

function deliveryStatusLabel(status: string) {
  return ({ queued: "排队中", sending: "发送中", delivered: "已送达", failed: "失败待重试", suppressed: "已抑制", dead_letter: "死信" } as Record<string, string>)[status] || status;
}

function formatTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}
